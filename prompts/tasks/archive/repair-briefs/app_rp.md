你是一名资深 Python/FastAPI 后端性能、可靠性和生产工程师。请直接审计并修改当前代码仓库，使后端达到可上线状态。

## 总目标

修复后端中的：

1. asyncio 事件循环阻塞；
2. OCR、PDF、Excel、图片处理造成的 CPU/内存问题；
3. 不可靠的进程内后台任务；
4. Redis 缓存、分布式锁和权限问题；
5. 数据库查询与连接池问题；
6. 生产配置和健康检查问题；
7. 多 worker 下的任务一致性问题。

优先级严格按照 P0 → P1 → P2 执行。先阅读 `CLAUDE.md`、README、部署文件、requirements、Alembic 和现有测试，再修改代码。

不要只输出建议，必须实际修改代码、补充测试并运行测试。

## 已发现的 P0 问题

### P0-1：同步 OCR 阻塞 asyncio 事件循环

重点检查：

- `services/import_pipeline_service.py`
  - `_run_image_pipeline_with_db`
  - 当前直接执行 `ocr_image(image_content)`
- `services/batch_answer_image_service.py`
  - `generate_image_preview`
  - 当前在异步请求中串行调用 `ocr_image`
- 所有 async 函数中的：
  - PaddleOCR 调用
  - PyMuPDF 页面渲染
  - Pillow 解码/缩放
  - OpenPyXL 解析
  - 大文件同步读写
  - Matplotlib/SymPy 运算

要求：

1. 所有同步 CPU 密集或阻塞操作不得直接运行在 FastAPI 事件循环。
2. 本地 OCR 使用专门的有界执行器或独立 worker，不得无限使用默认线程池。
3. 增加进程级并发信号量，并与 OCR profile 的并发限制保持一致。
4. OCR 超时必须可观测；超时后不能继续无限占用请求 worker。
5. 不要在持有 SQLAlchemy AsyncSession 或数据库事务时执行 OCR、AI 网络请求或长时间 CPU 运算。
6. 为事件循环响应性编写测试：mock 一个耗时 OCR，同时并发请求轻量健康接口，健康接口不能被 OCR 阻塞。

### P0-2：PDF 在异步函数中同步、重复渲染全部页面

重点检查：

- `features/pipeline_orchestrator.py`
  - `_plan_chunks`
  - `_render_page_images`
  - `_render_page_image_refs`
  - `ImportPipeline.run`

当前问题包括：

- 在 async `run()` 中同步调用 PyMuPDF。
- 同一 PDF 页面先渲染为内存 PNG，又重复渲染到临时文件。
- 一次性保存全部页面图片。
- 对长 PDF 产生 CPU 峰值和内存峰值。

要求：

1. PyMuPDF 的解析和渲染必须移出事件循环。
2. 同一页面最多渲染一次。
3. 优先采用按 chunk、按需、流式处理，不要将整本 PDF 的全部 PNG 保存在内存。
4. 页面图片使用临时文件或受控缓存，并保证异常及取消时清理。
5. 增加页面级和任务级内存上限。
6. 保持现有 pipeline 状态、断点恢复和 API 响应结构兼容。

### P0-3：缓存管理接口越权且可能清空整个 Redis

重点检查：

- `api/v1/cache.py`
- `core/cache.py`

要求：

1. 普通小程序用户不得访问缓存管理接口。
2. 缓存管理接口应移到管理员 API，并要求明确的系统管理权限；不再使用普通 `get_current_user`。
3. 删除或严格禁止任意 pattern 和 `FLUSHDB`。
4. 缓存删除只能操作应用自身 namespace 白名单。
5. 将 Redis `KEYS` 改成基于 `SCAN` 的分批删除。
6. 不得删除任务队列、JWT 黑名单、分布式锁或其他业务 namespace。
7. 增加未授权、越权、namespace 隔离及大 keyspace 的测试。

### P0-4：长任务不能继续使用裸 `asyncio.create_task` 或请求内 BackgroundTasks

检查仓库内所有 `asyncio.create_task` 和 FastAPI `BackgroundTasks`，尤其是：

- PDF/Excel/图片导入；
- pipeline resume；
- 批量图片 OCR；
- 公式批量生成；
- AI 预热 fallback。

要求：

1. 长任务改为可靠、可恢复的队列。
2. 优先复用项目已有 Redis、数据库 job 表和状态机；若引入新库，选择轻量且可维护的方案，并更新 requirements 和部署配置。
3. Web worker 只负责校验、持久化原始文件或对象存储引用、创建 job、入队并立即返回。
4. worker 从持久化存储获取任务，不依赖创建请求的进程内存或本地临时文件。
5. 支持：
   - 幂等；
   - 重试与退避；
   - 最大重试次数；
   - dead-letter/failed 状态；
   - 心跳或 lease；
   - worker 崩溃后的任务回收；
   - 优雅停机；
   - 部署重启后继续处理。
6. 不能破坏现有 job_id、pipeline_id、SSE 和查询接口。
7. 对历史停留在 `queued/running/processing` 的任务提供启动恢复或超时标记机制。

### P0-5：生产配置必须 fail-fast

重点检查：

- `core/config.py`
- `main.py`
- `core/database.py`
- 部署环境变量和 Compose/Gunicorn 配置

在 `APP_ENV=production` 时，启动前必须验证：

1. `APP_SECRET` 不是默认值，长度和随机性满足要求。
2. 数据库必须为 PostgreSQL，不能使用 SQLite。
3. `REDIS_URL` 必填且 Redis ping 成功。
4. CORS 不能包含 localhost、通配符或非法 origin。
5. 数据库迁移版本已经达到 Alembic head。
6. 必需的微信、AI、OCR、向量配置根据已启用功能进行条件校验。
7. 本地 OCR 启用时必须验证实际设备能力；不要在 profile 中硬编码 `use_gpu=True`，应尊重 `OCR_USE_GPU`。
8. 静态目录和持久化目录必须可写。
9. 任何 P0 配置错误都应阻止应用启动，不得只记录 warning 后继续。

不要在日志中打印 secret、token、完整 DSN 或 API key。

### P0-6：资源和连接池必须适配 2 核、约 1.8GB 内存

当前默认配置可能为：

- 4 个 Gunicorn worker；
- 每 worker `pool_size=10`、`max_overflow=20`；
- Matplotlib、NumPy、SymPy 在所有 worker 中加载；
- 每 worker 一个 2 进程的图形渲染 ProcessPool；
- 可选 PaddleOCR 模型。

要求：

1. 根据 CPU、内存和数据库连接预算设置合理默认值。
2. 计算并限制总数据库连接数：
   `web_workers × (pool_size + max_overflow) + background_workers`。
3. 添加 `pool_pre_ping`、连接获取超时和明确的 pool timeout。
4. 重型可选模块采用延迟加载，未使用公式或 OCR 功能时不应占用每个 Web worker 的大量内存。
5. 图形渲染不要在每个 Gunicorn worker 各自创建多进程池；改为独立受控 worker，或使用全局受控并发方案。
6. 给出针对 2 核/1.8GB 环境的推荐 worker、线程、连接池和 OCR 配置。
7. 更新 `.env.example`、部署文档和生产 Compose。

### P0-7：修复 readiness/liveness

要求提供无需认证的：

- `/health/live`
- `/health/ready`

语义：

1. live 仅表示进程事件循环仍可响应。
2. ready 必须检查生产必需依赖。
3. DB、Redis、迁移版本或必需配置异常时，ready 返回 HTTP 503。
4. 不得因为本地缓存 fallback 而把 Redis 判断为正常。
5. 检查必须设置短超时，不能反过来阻塞事件循环。
6. 根 `/health` 不得始终无条件返回 ok。
7. 更新 Nginx、Docker Compose 或容器探针配置。

### P0-8：异常信息不得直接泄露

检查 `main.py` 全局异常处理器。

要求：

1. 客户端只返回稳定错误码、通用消息、request_id 和 trace_id。
2. 原始异常只写服务端结构化日志和 Sentry。
3. 不得向客户端返回 SQL、路径、第三方响应体、异常类名或 secret。
4. 为生产和开发环境保留合理差异，但生产默认必须安全。

## P1 性能和一致性修复

### P1-1：上传和内存控制

重点检查：

- 答案图片预览最多 50 张、单张 10MB；
- 批量图片导入；
- PDF、Excel 和单图上传；
- 所有 `await UploadFile.read()`。

要求：

1. 增加单文件和整个请求的 aggregate size 限制。
2. 不要把所有文件同时保存在 `list[bytes]`。
3. 使用流式读、`SpooledTemporaryFile` 或持久化临时存储。
4. 在解码前验证 MIME、magic bytes、图片像素数和解压炸弹风险。
5. 临时文件必须在成功、异常、取消和重启恢复路径中有明确生命周期。
6. 返回 413 或明确业务错误，不允许 OOM。

### P1-2：消除低效随机查询

搜索所有：

- `ORDER BY random()`
- `func.random()`

重点包括：

- `services/question_service.py`
- `services/practice_service.py`
- `services/knowledge_path_service.py`
- 公式随机卡片接口

要求：

1. 不对大表做全表随机排序。
2. 采用可扩展的随机采样方案，例如基于 ID 范围、候选 ID 集、预计算随机键或 PostgreSQL 合适的采样策略。
3. 保证过滤条件、排除题目、推荐策略和随机性语义基本兼容。
4. `services/practice_service.py` 的知识点补齐查询必须在数据库层 `LIMIT`，不能加载全部结果后在 Python 截断。
5. 为大数据量查询补充 EXPLAIN/基准说明。

### P1-3：消除 N+1 和循环数据库访问

静态搜索 async 循环中的：

- `db.get`
- `db.execute`
- `db.flush`
- `db.commit`

重点检查：

- practice knowledge states；
- wrong question batch operations；
- import duplicate checks；
- publish/review；
- knowledge-point sync；
- formula batch review；
- review result组装。

要求：

1. 改为批量 SELECT、IN 查询、JOIN、UPSERT、批量 UPDATE/INSERT。
2. 不在循环中 commit。
3. 对批量操作设置合理 batch size。
4. 为关键接口增加 SQL 查询次数测试，避免回归。

### P1-4：修复分布式锁

重点检查：

- `core/cache.py`
- `services/pomodoro_scheduler_service.py`
- `services/audit_cleanup_scheduler.py`

要求：

1. 抢锁失败必须立即跳过任务，不能继续执行。
2. 使用唯一 token。
3. 释放锁必须使用 Lua compare-and-delete，不能 `GET` 后 `DELETE`。
4. 长任务支持 lease 续期或锁 TTL 明确覆盖最大执行时间。
5. Redis 不可用时，生产环境不能静默退化为多进程本地锁。
6. 编写两个 scheduler 实例并发执行的测试，保证同一任务只被认领一次。

### P1-5：HTTP Client 和 shutdown

1. 复用有连接池的 AsyncClient，不要频繁创建客户端。
2. 设置 connect/read/write/pool timeout 和连接数限制。
3. lifespan shutdown 时关闭：
   - HTTP clients；
   - Redis clients；
   - SQLAlchemy engine；
   - scheduler；
   - executor/process pool；
   - 后台 worker。
4. shutdown 应等待正在处理的短任务，长任务释放 lease 后安全退出。

### P1-6：数据库索引和查询审计

根据实际 PostgreSQL schema、Alembic 和查询补充索引，重点覆盖：

- practice records 的 user/time/subject；
- review schedules 的 user/next_review_at/status；
- wrong questions 的 user/status/updated_at；
- pipeline/job 状态；
- recommendation logs；
- audit logs；
- active question + subject/type；
- 幂等键和任务认领字段。

不要仅在 ORM model 中添加 index；必须创建 Alembic migration。

对 `%keyword%`、JSON LIKE 和模糊搜索评估 GIN、pg_trgm、规范化关联表或其他适当方案。

## 测试与验收

至少增加以下测试：

1. 慢 OCR 时事件循环仍能快速响应 live health。
2. PDF 渲染不在事件循环执行。
3. 普通用户无法清缓存。
4. 缓存删除不使用 `KEYS` 和 `FLUSHDB`。
5. worker 重启后 queued/running 任务可以恢复。
6. 同一幂等请求不会生成两个任务。
7. Redis 不可用时 production 启动失败。
8. 默认 APP_SECRET 或 SQLite production 配置启动失败。
9. ready 在 DB/Redis 异常时返回 503。
10. 多 scheduler 实例只执行一次。
11. 大批量图片请求触发 aggregate 限制，不造成内存暴涨。
12. 随机出题查询不再全表 `ORDER BY random()`。
13. 关键批量接口没有循环 SQL 回归。
14. 全局异常响应不包含原始异常文本。

运行并记录：

- formatter；
- lint；
- type check；
- unit tests；
- integration tests；
- Alembic upgrade/downgrade 检查；
- 最小启动 smoke test；
- PostgreSQL/Redis 集成测试；
- 一个轻量并发压测。

## 性能验收标准

在与生产资源接近的 2 核、约 1.8GB 环境中验证：

1. OCR 或 PDF 导入运行时，`/health/live` p95 小于 200ms。
2. 普通读接口不会因后台 OCR 停顿数秒。
3. Web worker 不因单次允许范围内的上传发生 OOM。
4. 数据库连接总数不超过配置预算。
5. 同时只能运行配置允许数量的 OCR、PDF 渲染和图形渲染任务。
6. 任务失败、超时、部署重启后状态可解释且可恢复。
7. 不允许通过降低安全性、删除功能或吞掉错误来达标。

## 兼容性约束

1. 尽量保持现有 API 路径、请求字段、响应字段、pipeline_id、job_id 和状态枚举兼容。
2. 不修改题目业务规则、OCR 模型结果和推荐算法，除非是修复明确 bug。
3. 不使用无限队列、无限线程池或无限重试。
4. 不把长任务重新塞回 Web worker。
5. 不在生产运行时执行 schema DDL。
6. 不执行会停止数据库、Redis 或 Nginx 的部署操作。
7. 所有新增环境变量必须进入 `.env.example` 和部署文档。
8. 所有数据库修改必须有 Alembic migration。
9. 对无法一次安全迁移的地方增加 feature flag 和回滚方案。

## 执行方式

按以下顺序工作：

1. 输出当前架构和问题复核；
2. 建立修改清单；
3. 先完成 P0；
4. 运行测试；
5. 再完成 P1；
6. 再次运行完整测试和压测；
7. 检查 git diff，删除临时代码；
8. 输出最终报告。

最终报告必须包含：

- 修改文件列表；
- 每个问题的根因和修复方式；
- 新增迁移；
- 新增环境变量；
- 测试命令和结果；
- 压测结果；
- 尚未解决的风险；
- 推荐生产参数；
- 部署步骤；
- 回滚步骤；
- 最终 `GO` 或 `NO-GO` 判断。

发现阻塞问题或测试失败时继续修复，不要仅留下 TODO。除非受到外部凭据或基础设施限制，否则不得以“无法验证”为由停止。