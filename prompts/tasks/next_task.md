请在 postgraduate-ai 项目中优化数据库 SQL 日志与高频列表查询，目标是：默认不再把 SQLAlchemy 的完整 SQL 语句刷到业务日志里，同时保留慢查询/异常 SQL 的可观测性，并优化 question_imports 列表查询不要拉取大字段。

背景：
当前日志里大量出现类似：

2026-06-27 12:20:01 | INFO | sqlalchemy.engine.Engine |
SELECT question_imports.id, question_imports.batch_id, question_imports.source_type, question_imports.source_file, question_imports.subject, question_imports.question_type, question_imports.raw_data, question_imports.parsed_content, question_imports.parsed_options, question_imports.parsed_answer, question_imports.parsed_analysis, question_imports.question_hash, question_imports.duplicate_status, question_imports.duplicate_of_question_id, question_imports.duplicate_of_import_id, question_imports.status, question_imports.review_note, question_imports.question_id, question_imports.reject_reason, question_imports.reviewed_by, question_imports.reviewed_at, question_imports.ai_generated, question_imports.ai_source, question_imports.ai_confidence, question_imports.ai_metadata, question_imports.ai_raw_response, question_imports.ai_reviewed_at, question_imports.ai_answer_flag, question_imports.math_regions, question_imports.superseded_by_batch_id, question_imports.superseded_at, question_imports.created_at, question_imports.updated_at
FROM question_imports
WHERE question_imports.status = ? ORDER BY question_imports.created_at DESC, question_imports.id DESC
LIMIT ? OFFSET ?

这类日志价值很低，会淹没有价值的 OCR trace / AI repair / import pipeline 日志；同时这条 SQL 暴露出列表页查询把 raw_data、parsed_content、parsed_options、ai_raw_response、math_regions 等大字段全部查出来了，列表页没有必要。

请直接修改代码，不要只解释。

一、全局 SQLAlchemy 日志降噪

目标：
1. 默认情况下，不再输出普通 SQLAlchemy Engine INFO 日志。
2. 保留 SQL 错误、连接池错误和应用异常日志。
3. 支持通过环境变量临时打开 SQL 全量日志，用于本地调试。
4. SQL 参数默认隐藏，避免敏感数据和超长 prompt/response 打日志。

请查找项目中的数据库 engine 初始化位置，可能在：
- app/db.py
- app/core/database.py
- app/database.py
- app/core/config.py
- 或其他创建 create_async_engine/create_engine 的文件

请完成：
1. 增加配置项：
   - SQL_ECHO，默认 false
   - SQL_LOG_LEVEL，默认 WARNING
   - SLOW_QUERY_MS，默认 500
   命名风格请和项目 settings 保持一致。

2. create_async_engine/create_engine 中：
   - echo 使用 settings.SQL_ECHO
   - hide_parameters=True
   - 不要在生产默认 echo=True

示例：

    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=settings.SQL_ECHO,
        hide_parameters=True,
        pool_pre_ping=True,
        ...
    )

3. logging 配置中把以下 logger 默认设为 WARNING：
   - sqlalchemy.engine
   - sqlalchemy.pool
   - sqlalchemy.dialects

示例：

    logging.getLogger("sqlalchemy.engine").setLevel(settings.SQL_LOG_LEVEL)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.dialects").setLevel(logging.WARNING)

注意：
- 如果项目已有统一 logging config，请在现有配置中改，不要散落多处重复配置。
- SQL_LOG_LEVEL 需要从字符串安全转换为 logging level。
- 默认值必须让普通 SELECT/INSERT/UPDATE 不再刷屏。
- 本地需要排查 SQL 时，可以通过 SQL_ECHO=true 或 SQL_LOG_LEVEL=INFO 临时开启。

二、新增慢查询日志

目标：
关闭全量 SQL 后，仍然能看到真正值得关注的慢查询。

请在 engine 初始化后注册 SQLAlchemy event listener：
- before_cursor_execute 记录开始时间
- after_cursor_execute 计算耗时
- 如果 duration_ms >= settings.SLOW_QUERY_MS，则用 logger warning 打印慢查询
- handle_error 或异常事件可以记录 SQL 执行异常，如果项目已有异常日志可不重复

慢查询日志要求：
1. logger 名称建议为 app.db.slow_query 或项目已有命名风格。
2. 日志级别 warning。
3. SQL 语句要压缩空白并截断，避免一条日志几千行。
4. 默认最多打印 1000 或 1500 字符。
5. 不打印完整 parameters，避免敏感信息；最多打印 param_count / executemany。
6. 记录 duration_ms、rowcount、sql。
7. 对 async engine 使用 engine.sync_engine 注册事件。

示例形态：

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        context._query_start_time = time.perf_counter()
    
    @event.listens_for(engine.sync_engine, "after_cursor_execute")
    def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        start = getattr(context, "_query_start_time", None)
        if start is None:
            return
        duration_ms = (time.perf_counter() - start) * 1000
        if duration_ms >= settings.SLOW_QUERY_MS:
            compact_sql = " ".join(statement.split())
            if len(compact_sql) > 1200:
                compact_sql = compact_sql[:1200] + "..."
            slow_query_logger.warning(
                "slow query duration_ms=%.1f rowcount=%s executemany=%s sql=%s",
                duration_ms,
                getattr(cursor, "rowcount", None),
                executemany,
                compact_sql,
            )

注意：
- 如果 SLOW_QUERY_MS <= 0，可以关闭慢查询日志。
- 不要因 logger 代码异常影响正常 SQL 执行。
- listener 不要重复注册多次；如果项目测试会多次创建 engine，需要避免重复注册或保持幂等。

三、优化 question_imports 列表查询：摘要查询，不拉大字段

目标：
审核池/导入列表页只查列表所需字段，不要 SELECT question_imports.* 或 ORM model 全量实体。

请搜索以下相关接口或服务：
- question_imports
- review pool
- import review
- imports list
- pending imports
- status = ?
- order_by QuestionImport.created_at.desc(), QuestionImport.id.desc()

现状问题：
列表查询把这些大字段都查出来：
- raw_data
- parsed_content
- parsed_options
- parsed_analysis
- ai_metadata
- ai_raw_response
- math_regions

要求：
1. 列表接口改成 select 指定字段，或者使用 load_only/defer，优先推荐 select 指定字段 + DTO/schema。
2. 列表页只返回必要摘要字段，例如：
   - id
   - batch_id
   - source_type
   - source_file
   - subject
   - question_type
   - status
   - duplicate_status
   - duplicate_of_question_id / duplicate_of_import_id 如页面需要
   - ai_generated
   - ai_source
   - ai_confidence
   - ai_answer_flag 如页面需要
   - review_note / reject_reason 如页面需要
   - question_id
   - created_at
   - updated_at
   - 一个短的 stem_preview / content_preview
3. 如果页面需要题干预览，不要返回完整 parsed_content/raw_data，请使用数据库 substr 或后端截断：
   - SQLite: func.substr(QuestionImport.parsed_content, 1, 120)
   - 其他 DB 也兼容 SQLAlchemy func.substr
   - 或查出必要短文本后 Python 截断
4. 详情接口保持全量字段，不要破坏审核详情页。
5. 如果前端列表目前依赖 parsed_content / parsed_options 全量字段，请同步改前端为只展示 preview；点击详情再请求详情接口。
6. 保持 API 返回结构尽量兼容；如果必须变更字段，请检查前端调用并同步修改。

建议后端查询形态：

    stmt = (
        select(
            QuestionImport.id,
            QuestionImport.batch_id,
            QuestionImport.source_type,
            QuestionImport.source_file,
            QuestionImport.subject,
            QuestionImport.question_type,
            QuestionImport.status,
            QuestionImport.duplicate_status,
            QuestionImport.duplicate_of_question_id,
            QuestionImport.duplicate_of_import_id,
            QuestionImport.ai_generated,
            QuestionImport.ai_source,
            QuestionImport.ai_confidence,
            QuestionImport.ai_answer_flag,
            QuestionImport.review_note,
            QuestionImport.question_id,
            QuestionImport.created_at,
            QuestionImport.updated_at,
            func.substr(QuestionImport.parsed_content, 1, 160).label("content_preview"),
        )
        .where(QuestionImport.status == status)
        .order_by(QuestionImport.created_at.desc(), QuestionImport.id.desc())
        .limit(limit)
        .offset(offset)
    )
    
    rows = (await db.execute(stmt)).mappings().all()

如果项目使用 Pydantic schema，请新增 QuestionImportListItem / ReviewPoolListItem，避免复用详情 schema 导致又要求大字段。

四、为列表查询添加或确认复合索引

目标：
优化以下查询模式：

    WHERE question_imports.status = ?
    ORDER BY question_imports.created_at DESC, question_imports.id DESC
    LIMIT ? OFFSET ?

请检查模型和迁移：
1. 如果没有索引，新增复合索引：
   - status, created_at, id
2. 如果经常按 batch_id + status 查，也新增：
   - batch_id, status, created_at, id

SQLAlchemy 模型示例：

    __table_args__ = (
        Index("ix_question_imports_status_created_id", "status", "created_at", "id"),
        Index("ix_question_imports_batch_status_created_id", "batch_id", "status", "created_at", "id"),
    )

如果项目使用 Alembic：
- 新增 migration，创建索引
- downgrade 删除索引

注意：
- SQLite 对 DESC 索引支持和其他 DB 有差异，普通升序复合索引也可接受。
- 不要创建重复索引；先搜索已有索引。

五、保留临时 SQL 调试能力

请在 .env.example / 文档 / README 中补充说明：

    SQL_ECHO=false
    SQL_LOG_LEVEL=WARNING
    SLOW_QUERY_MS=500

说明：
- 日常开发默认 SQL_ECHO=false
- 临时排查 SQL 时可以设置 SQL_ECHO=true 或 SQL_LOG_LEVEL=INFO
- 慢查询超过 SLOW_QUERY_MS 才会 warning 输出

六、测试要求

请按项目现有测试框架补充测试。

后端测试建议：

1. test_sqlalchemy_engine_echo_default_false
   - 验证默认 settings.SQL_ECHO 为 false
   - 验证 engine.echo 为 false
   - 如果 engine 不方便直接断言，至少断言 settings 默认值

2. test_slow_query_logger_truncates_sql
   - 对慢查询格式化函数做单元测试
   - 输入超长 SQL，断言输出被截断
   - 断言不包含完整 parameters

3. test_question_import_list_query_excludes_large_columns
   - 对列表查询 builder 做断言，或通过 SQL compile 断言 SELECT 中不包含：
     raw_data
     parsed_options
     parsed_analysis
     ai_raw_response
     math_regions
   - 允许包含 substr(parsed_content) 或 content_preview，但不要 SELECT parsed_content 全量

4. test_question_import_detail_still_returns_full_fields
   - 详情接口仍能返回 parsed_content / parsed_options / raw_data 等必要字段

5. 如果新增 Alembic migration，确认迁移文件包含 create_index/drop_index。

如果前端有测试：
1. 列表页展示 content_preview。
2. 点击详情仍能展示完整题干、选项、AI 原始信息。

七、验收标准

完成后必须满足：
1. 默认启动后，普通 SQLAlchemy SELECT/INSERT/UPDATE 不再以 INFO 形式刷屏。
2. SQL 错误和应用异常仍然能正常打印。
3. 超过 SLOW_QUERY_MS 的慢查询会输出一条 compact warning 日志。
4. 慢查询日志不会打印完整参数和超长 SQL。
5. question_imports 列表接口不再查询 raw_data、parsed_options、parsed_analysis、ai_raw_response、math_regions 等大字段。
6. 详情接口不受影响。
7. 列表查询具备合适复合索引。
8. .env.example 或文档说明如何临时打开 SQL 日志。
9. 现有 OCR trace / import pipeline 日志可读性显著提升。

完成后请输出：
1. 修改过的文件列表。
2. 日志配置新增环境变量说明。
3. 慢查询日志示例。
4. question_imports 列表查询改动摘要。
5. 新增索引/迁移说明。
6. 运行过的测试命令和结果。
7. 如果有测试因本地环境依赖缺失无法运行，请明确说明。
