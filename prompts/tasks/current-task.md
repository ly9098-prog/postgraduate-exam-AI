------

# OCR Pipeline 数据生命周期审计与流式架构改造

请先进行架构审计，不要直接修改代码。

> ## 当前进度（2026-06-05）
>
> - [x] **审计阶段**：完成 → `docs/audit/ocr-pipeline-lifecycle-audit.md`
> - [x] **P0-2 区域检测 OCR 工作量降为 1/N**：完成
>   - `EXERCISE_DETECTION_SAMPLE_STEP=3` 默认采样
>   - lightweight OCR 工作量降为 1/3（**注意：这不是"消除双 OCR"** ——
>     区域检测仍是独立扫描，全量 OCR 仍从零开始；实际链路为
>     `lightweight 1/N + full(region)`，最优场景 33% + 部分页，
>     最坏场景 33% + 100%。task 文档原"消除双 OCR"措辞夸大，已修正。）
>   - region 边界 ±(step-1) 扩展 + 重叠合并
>   - max_empty_pages 在采样模式下自动放大
>   - **漏检 fallback 保护（P0 隐患修复 2026-06-05）**：当 `step>1` 检测
>     一无所获时，先退化到 `step=1` 重新探测一次再决定是否走全本 OCR。
>     避免王道教材关键词恰好落在跳过页时，整体工作量比不开检测更高。
>   - 39 个 detector 测试通过（含 7 个新增采样模式测试）
> - [x] **P0-1 PDF 字节落盘 + 闭包不持有**：完成
>   - API 入口 `_run_pipeline_with_db`：`tempfile.mkstemp` 落盘后 `del file_content`，`finally` 块 `os.unlink`
>   - 链路改造：`run_pipeline_background` / `run_import_pipeline` / `ImportPipeline.run` 接受 `file_path`
>   - 底层 `_open_pdf_doc` 统一处理 bytes/path，path 走 `fitz.open(filename)` 即 mmap
>   - `_extract_pdf_blocks` / `_ocr_scanned_pdf` / `_extract_text_blocks` / `detect_exercise_regions_from_pdf` / `_lightweight_page_ocr` 全部接受 `bytes | str`
>   - extract 完成后 `data.pop("file_content")` 和 `data.pop("file_path")`，避免后续 8+ 个 stage 持有引用
>   - 82 个相关测试通过（detector 39 + orchestrator 43），新增/已有功能均无回归
> - [x] **P0-3 `_pipeline_store` 瘦身 + diagnostics 单独存**：完成
>   - 主 store 仅保留 `_PIPELINE_STORE_FIELDS` 白名单（pipeline_id/status/source_type/source_file/current_stage/stages/stats/errors/started_at/finished_at/batch_id/raw_text_preview/question_count）
>   - 新增 `_pipeline_diagnostics_store` 内存字典 + Redis key `import:pipeline:diagnostics:{id}`，TTL 24h 与主 store 同步
>   - `_set_pipeline_store` 自动剥离 `data["diagnostics"]`，主 store / Redis 不再写大字段
>   - `_prune_store` 同步淘汰 diagnostics 内存条目，不留泄漏
>   - `get_pipeline_status` 把 diagnostics 合并回完整视图，前端无感
>   - 新增 3 个 P0-3 单元测试：strip / merge-back / prune-sync
>   - 108 个相关测试通过（pipeline_orchestrator + pipeline_upload_unified + image_import_status + exercise_region_detector），无新增回归
> - [x] **P0 隐患修复（2026-06-05 审计后）**：完成
>   - **隐患 2 修复**：`get_pipeline_status` 改为返回 `dict(data)` 防御性拷贝。
>     之前实现里 `data["ocr_progress"] = ...` 会污染 `_pipeline_store[pid]`
>     引用，破坏白名单契约。新增 `test_status_query_does_not_pollute_main_store`
>     断言主 store 字段始终是 `_PIPELINE_STORE_FIELDS` 子集。
>   - **隐患 1 修复**：见上方 P0-2 fallback 保护 + 命名修正。
> - [x] **P1-A stage 间清理 data 大字段**：完成
>   - `ImportPipeline.run` 主循环按数据生命周期 pop：
>     - `extract` 后：`file_content` / `file_path`（已有，P0-1）
>     - `normalize_text` 后：`raw_blocks`
>     - `match` 后：`normalized_blocks`（保留 `normalized_block_count` 给 stats 兜底）
>     - `normalize_schema` 后：`raw_questions` / `matched` / `unmatched`
>   - 终极效果：进入 `repair` / `ai_validation` / `similarity_match` / `review`
>     的 `data` 只剩 `questions` 一份大对象，其它阶段间产物全部释放。
>     400 页扫描 PDF 场景下，OCR 后的 `normalized_blocks`（含 boxes）
>     单独可达 50~200 MB，是仅次于 PDF 字节的内存大头。
>   - 新增 `test_p1a_large_fields_released_between_stages`：用 review 阶段
>     做哨兵，断言 review 收到的 kwargs 里不再含 raw_blocks / normalized_blocks /
>     raw_questions / matched / unmatched，且 stats.normalized 计数仍正确。
>   - 110 个相关测试通过（pipeline_orchestrator + pipeline_upload_unified +
>     image_import_status + exercise_region_detector），无新增回归。
> - [x] **P1-B review 阶段分批 commit**：完成
>   - `submit_to_review` 每 `_REVIEW_COMMIT_BATCH_SIZE=50` 道题做一次
>     `commit() + expunge_all()`，把 QuestionImport ORM 对象从 session
>     identity map 中放出来，让 GC 能回收 `raw_data` / `parsed_content` 等
>     dict（一道题约 5~30 KB，400 道累积可达 12 MB）。
>   - 收尾逻辑：尾部不满 batch 时再 commit 一次 + expunge；恰好整数倍时
>     再调一次 commit 关闭事务（无新对象，对 SQLAlchemy 是 no-op）。
>   - `seen_hashes` 只存 `hash → int`，跨 batch 不持有 ORM 引用。
>   - **未做 raw_data 瘦身**：raw_data 被 question_publish_service /
>     ai_import_helpers / import_service 多处读取，瘦身需要全链路兼容
>     评估，留到后续单独处理。
>   - 新增 2 个 P1-B 测试：105 道题断言 3 次 commit + 3 次 expunge_all；
>     恰好 50 道断言 2 次 commit（一次满 batch + 一次空收尾）+ 1 次
>     expunge_all。
>   - 144 个相关测试通过（review_service + pipeline_orchestrator +
>     pipeline_upload_unified + image_import_status + exercise_region_detector），
>     无新增回归。
> - [x] **P1 阶段审计后隐患修复（2026-06-05）**：完成
>   - **隐患①修复**：`pipeline_orchestrator.py` `stats["normalized"]` 在
>     `match` 之前的 stage（如 `analyze_structure`）失败时静默归零。
>     根因：原 fallback 链 `normalized_count → normalized_block_count →
>     len(normalized_blocks)`，前两者由 `normalize_schema` / `match` 后才
>     写入，中段失败时全部缺失，第三层在 `normalized_blocks` 已被 pop
>     的情况下永远是 0。
>     修复：每次 stage 写入 `normalized_blocks` 都同步缓存
>     `normalized_block_count`；fallback 兜底改为 `0` 而非
>     `len(已 pop 字段)`。
>     新增 `test_p1a_stats_normalized_survives_mid_pipeline_failure`：
>     断言 `analyze_structure` 失败后 `stats["normalized"]` 仍为 3。
>   - **隐患③修复**：`review_service.submit_to_review` 用
>     `db.expunge_all()` 会把整个 session 中所有 ORM 实例（包括上层调
>     用方 attach 的 watermark 规则、user 等）一并踢掉。
>     修复：维护本批 `pending_qis: list[QuestionImport]`，commit 后
>     逐条 `db.expunge(qi)`；commit 完成即 clear，避免持有引用。
>     更新两个 P1-B 测试：`expunge` 调用次数 = 写入题数；
>     `expunge_all` 不再被调用；按写入顺序断言 expunged_ids。
>   - **隐患②修复**：分批 commit 中途崩溃会留下孤儿 `batch_id` 记录
>     （前面已 commit 50 道，第二批失败后剩半截数据）。
>     修复：把整段写入循环包到 try/except，捕获异常后先 `db.rollback()`，
>     再 `DELETE FROM question_imports WHERE batch_id = ?` 做 best-effort
>     清理，最后 `raise` 把原始异常抛给调用方。任意一步清理失败只记
>     `logger.exception`，不掩盖原始异常。
>     新增 `test_p1b_mid_batch_failure_cleans_orphan_batch`：mock 第二
>     次 commit 抛错，断言 rollback 调用一次 + 触发一次 Delete 语句 +
>     RuntimeError 向上传播。
>   - 146 个相关测试通过（1 个 deselected 是 P0 阶段已存在失败，与本
>     次修复无关）。
> - [x] **P2-1 import_pipelines schema + checkpoint 模块**：完成
>   - 新增 `app/models/import_pipeline.py`：`ImportPipeline`（父表）+
>     `ImportPipelineChunk`（子表，FK→ImportPipeline.pipeline_id，无 CASCADE）
>     - chunk PK 用 `Integer`（不是 `BigInteger`），保证 SQLite 下 rowid alias
>       autoincrement 行为，与项目其它表（question_imports.id 等）一致。
>     - `UniqueConstraint(pipeline_id, chunk_index)` 防止同一 pipeline 重复 chunk。
>   - 新增 `alembic/versions/n5d6e7f8a9b0_add_import_pipeline_tables.py`：
>     幂等迁移（`_has_table` / `_has_index` 复用 j1f2a3b4c5d6 的模式），
>     完整 downgrade。
>   - 新增 `app/features/pipeline_checkpoint.py`：DB 为权威源 + Redis 仅做
>     进度快照缓存。7 个 public 函数：
>     - `create_pipeline_record / update_pipeline_status`
>     - `create_chunk_records / mark_chunk_running / update_chunk_status`
>     - `get_pipeline_progress`：返回 total/completed/failed/running/pending
>       计数 + question_count（仅 completed 累加）+ failed_chunk_details，
>       供 status API 直接复用。
>     - `get_pending_chunks`：返回 failed + pending（不含 running），按
>       chunk_index 排序，供 manual resume 使用。
>     - `invalidate_progress_cache`：写后清缓存。
>   - 全部 datetime 写入用 `_utcnow()` = `datetime.now(timezone.utc)`，避开
>     `datetime.utcnow()` deprecation。
>   - 新增 `tests/test_features/test_pipeline_checkpoint.py`：8 个用真实
>     sqlite+aiosqlite 跑的单测，覆盖创建/状态迁移/进度统计/resume 候选/
>     UNIQUE 约束。
>   - 92 个相关测试通过（pipeline_orchestrator 43 + review_service 41 +
>     pipeline_checkpoint 8），alembic upgrade head + downgrade -1 在干净
>     sqlite 上验证通过。
>   - **P2-1 严格不引入 orchestrator 逻辑**——只有 schema + checkpoint
>     模块 + 单测，run() 改造放到 P2-2。
> - [x] **P2-2 chunk runner + 失败隔离**：完成
>   - `pipeline_orchestrator.py`：
>     - 新增模块级 helpers：`_DEFAULT_CHUNK_SIZE=40` /
>       `_resolve_chunk_size`（读 env `IMPORT_PIPELINE_CHUNK_SIZE`）/
>       `_split_into_chunks`（1-based 闭区间）/ `_read_pdf_page_count`
>       （`fitz.open` 读 `len(doc)` 立即 close）/ `_build_stats` / `_build_diagnostics`
>       （把原 `run()` 内联的 stats/diagnostics 构造抽出来供 single-pass +
>       chunked 共用）。
>     - `ImportPipeline.run()` 拆成三段：watermark/strategy/import_mode 共
>       享一次（chunk 间复用，不重复加载）→ `_plan_chunks` 决策走分块还是
>       single-pass → `_run_single_pass` 或 `_run_chunked`。
>     - `_run_single_pass`：原 `run()` 主循环搬过来，0 行为变化；新增
>       `page_start/page_end` 入参可注入 chunk 范围（不破坏现有调用方）。
>     - `_run_chunked`：按 `_plan_chunks` 输出循环跑 chunk，每个 chunk
>       `mark_chunk_running` → `_run_single_pass(...page_start, page_end)` →
>       `update_chunk_status` + `invalidate_progress_cache`。任何 chunk 异
>       常**不 raise**，封装到 `chunk.error_message` + `pipeline_errors`，
>       继续下一 chunk。
>     - 整体状态：0 failed_chunks → `completed`，否则 `paused`（供 P2-5
>       手动 resume）。
>   - **chunked 触发条件**（任一不满足即走 single-pass，向后兼容）：
>     - `source_type == "pdf"` 且 `db is not None`
>     - 用户未通过 options 指定 `page_start/page_end`
>     - `_read_pdf_page_count` 成功返回且 `total_pages > chunk_size`
>     - `IMPORT_PIPELINE_CHUNK_SIZE > 0`
>   - **chunked 路径不污染主 store**：`_run_chunked` 直接返回聚合结果
>     `{status, batch_id (首个成功 chunk), stats: {total_chunks, completed_chunks,
>     failed_chunks, to_review, ...}, diagnostics: {chunked: True, chunks: [...]},
>     stages: {}, errors: [...]}`，前端可继续用 P0-3 的瘦身 store + diagnostics
>     KV，无需结构变更。
>   - 新增 `tests/test_features/test_pipeline_chunk_runner.py`：15 个测试
>     - `_split_into_chunks` / `_resolve_chunk_size` 边界 case
>     - chunked happy path（120 页 / chunk_size=40 → 3 chunks 全 completed，
>       DB checkpoint 记录齐全，question_count 正确累加，每 chunk 独立 batch_id）
>     - **chunk 1 抛错隔离**：chunk 0/2 仍 completed，pipeline.status=paused，
>       DB 中 chunk 1 status=failed + error_message 含原始异常文本
>     - chunk_size env override：100 页 / chunk_size=20 → 5 chunks，range 正确
>     - 0 题 chunk 标 completed（不是 failed）
>     - 单 chunk fallback：txt / 用户 page_range / 短 PDF / 无 db 全部走
>       legacy 单 pass，**不**创建 import_pipelines 行
>   - 169 个相关测试通过（pipeline_orchestrator 49 + pipeline_chunk_runner
>     15 + pipeline_checkpoint 8 + review_service + image_import_status +
>     exercise_region_detector + pipeline_upload_unified -1）。1 个 fail
>     是 P0 阶段已存在的 `test_pdf_dispatch_returns_pl_prefix`（git stash
>     验证与 P2-2 无关）。
> - [x] **P2-3 边界对齐 ±3 页**：完成
>   - `pipeline_orchestrator.py`：
>     - 新增 `_DEFAULT_CHUNK_OVERLAP=3` + `_resolve_chunk_overlap()`
>       （读 env `IMPORT_PIPELINE_CHUNK_OVERLAP`，负数 clamp 到 0，invalid
>       fallback 到 3）。
>     - `_run_chunked` 为非末 chunk 把 `effective_end =
>       min(logical_end + overlap, total_pages)` 后传给 `_run_single_pass`，
>       OCR 多读 3 页让题尾不被切碎；末 chunk 不扩。
>     - 引入跨 chunk 共享的 `seen_numbers: set[int]`（`_run_chunked` 持有），
>       通过 `_run_single_pass(... chunk_seen_numbers=, chunk_logical_end=)`
>       透传到 stage data 字典。
>     - `_run_split` 末尾追加 P2-3 逻辑：仅当 `_chunk_seen_numbers` 与
>       `_chunk_logical_end` 都注入时启用——
>       (a) **overlap 去重**：题号已在 seen_numbers 且 `page_start >
>           logical_end` 时丢弃，否则保留并把题号写入 seen_numbers；
>       (b) **boundary unclosed warning**：末题 page_end ≥ logical_end-1 且
>           `option_lines` 缺 D/E 时 emit `chunk_boundary_unclosed: q{n}` +
>           写 `split_diagnostics.boundary_unclosed_question`，供前端
>           review 提示用户该题可能跨 chunk。
>     - chunked diagnostics 多记 `chunk_overlap` 与每 chunk 的
>       `effective_page_end`（logical page_end 不变）。
>   - **关键约束**：
>     - 单 pass / 用户指定 page range / txt / 图片 OCR / 短 PDF 都**不**走
>       这套逻辑，行为零变化。
>     - dedup 只在 overlap 区（page_start > logical_end）触发，不会误删
>       chunk 内合法重号。
>     - seen_numbers 是函数级 set，跨进程不共享，重启即丢——P2-5 resume
>       时会从 DB chunks 重新累加。
>   - 新增 13 个测试（共 28 个 chunk runner 测试）：
>     - `_resolve_chunk_overlap` 5 case：default / env override / zero
>       disable / invalid fallback / negative clamp。
>     - `_run_split` 6 case：overlap 区去重 / overlap 区首次出现保留 /
>       overlap 内部误删保护 / boundary 警告触发 / 选项完整不警告 /
>       legacy 单 pass 旁路。
>     - `_run_chunked` 集成 2 case：120 页 effective_ends=
>       [(1,43),(41,83),(81,120)] 末 chunk 不扩；overlap=0 时退化。
>   - 回归：182 个相关测试通过（+13），1 个 P0 阶段已存在 fail 不变。
> - [ ] **P2-4 similarity → GlobalHashIndex**
> - [ ] **P2-5 manual resume API**
> - [ ] **P2-6 status API + 前端适配**
> - [ ] **P2-7 端到端测试**

------

## P2 总体架构（取舍已定，下面只记落地方案）

**核心取舍（已确认，不再重新讨论）：**

1. **Page Chunk 切分**（默认 40 页/chunk），不按 Region 切分；Region 仅作
   辅助元数据写入 chunk.metadata 供调试。
2. **AI repair / validation 在 chunk 内执行**；similarity 改为基于 hash
   的全局去重，不再持有全量 question 对象。
3. **Checkpoint：DB 为权威源，Redis 为进度快照缓存**（已在 P2-1 落地）。
4. **A2 chunk 失败隔离**：单 chunk OCR/AI 异常不杀全局，写
   `failed_chunks` 后继续；resume 由用户手动触发。
5. **B1 边界对齐 ±3 页**：chunk 末尾如检测到未闭合题号只记 warning，不做
   跨 chunk 缓冲（v1 简化方案）。
6. **C2 手动 Resume**：进程重启不自动恢复；POST /api/import/resume/
   {pipeline_id} 由用户主动调用。
7. **GlobalHashIndex 只加载当前批次 + 最近 N 天**（默认 30，env 可调），
   超过 50 万阈值降级为直接 SQL 查询，避免启动时间随历史题库膨胀。

------

## P2-2 chunk runner + 失败隔离

**目标**：把 `ImportPipeline.run` 改造为「按 chunk 循环执行」，单 chunk 失
败不影响整体；每个 chunk 的成功/失败状态写 DB，整体进度可在 status API
查询。

**改动范围（仅 `pipeline_orchestrator.py`）：**

1. 新增 `_split_into_chunks(total_pages, chunk_size=40) -> list[tuple[int, int]]`
   - 1-based 闭区间 page_start/page_end
   - chunk_size 可由 env `IMPORT_PIPELINE_CHUNK_SIZE` 覆盖（默认 40）

2. 新增 `ImportPipeline._run_chunk(page_start, page_end, **shared_data) -> dict`
   - 内部仍走原有 stage list（extract→…→review），但 extract 阶段把 page
     range 透传给 `_extract_pdf_blocks` / `_ocr_scanned_pdf`。
   - 返回 `{status, batch_id, question_count, error_message?, warnings, stage_summary}`。
   - 任何 stage 抛错 → catch 后封装为 status="failed"，**不再 raise**。

3. 改造 `ImportPipeline.run`：
   - 入口先用 `fitz.open` 读 total_pages（不读内容，立即 close），切 chunk。
   - 调 `create_pipeline_record` + `create_chunk_records` 落 DB。
   - for chunk in chunks:
     - `mark_chunk_running` → `_run_chunk(...)` → `update_chunk_status`
       + `invalidate_progress_cache`
     - 失败时把 error_message 写库，**不 break，继续下一 chunk**
   - 全部跑完后聚合 chunk 结果：
     - `pipeline.status = "completed"` 当且仅当 0 failed_chunks
     - 否则 `paused`（用户可 resume）
   - `update_pipeline_status(finished=True)`

4. **共享对象在 chunk 之间复用**（仅一次构造，不每 chunk 重新加载）：
   - watermark_patterns（DB 加载）
   - import_mode / strategy
   - GlobalHashIndex（P2-4 引入后由 run() 在循环外初始化并通过 shared_data
     注入到 chunk）
   - **不复用**：normalized_blocks / raw_questions / questions —— 这些是
     chunk 级中间态，每个 chunk 独立产生独立释放。

5. 失败隔离断言：
   - chunk 级异常通过 try/except 捕获并记录到 `chunk.error_message`
   - `_pipeline_store` 的 `errors` 字段聚合 `[chunk_index → error_message]`
     而非单条失败短路
   - `get_pipeline_status` 返回 `chunk_progress` 字段（来自
     `get_pipeline_progress`），前端可显示「失败 chunk 列表」

**关键 invariant（必须由测试覆盖）：**

- 单 chunk 抛错时：`pipeline.status` 最终是 `paused`，其它 chunk 仍正常完成。
- chunk 失败的 batch_id 不会出现在 review 队列（`update_chunk_status`
  只在 `submit_to_review` 成功后写）。
- `failed_chunks` 子表记录与 `_pipeline_store["errors"]` 一致。

**新增/修改测试：**

- `test_p2_2_chunk_runner_happy_path`：120 页 PDF / chunk_size=40 → 3 chunks
  全部 completed，pipeline.status=completed，DB 中 chunk 记录齐全。
- `test_p2_2_single_chunk_failure_isolated`：mock 第 2 个 chunk 的
  `_ocr_scanned_pdf` 抛错 → chunk 0/2 完成，chunk 1 failed，
  pipeline.status=paused，且 chunk 0/2 的题目都进了 review。
- `test_p2_2_chunk_size_from_env`：设 `IMPORT_PIPELINE_CHUNK_SIZE=20`
  断言 100 页文件切成 5 个 chunk。
- `test_p2_2_no_question_chunk_marked_completed`：某 chunk OCR 后 0 题，
  status 仍是 completed（不是 failed），question_count=0。
- 回归 `test_pipeline_orchestrator.py` 全部用例：单文件场景下行为与
  P1 完成态一致（chunk_size 大于总页数时退化成单 chunk）。

------

## P2-3 边界对齐 ±3 页

**目标**：避免 chunk 切分把一道题正好切成两半。**v1 不做跨 chunk 缓冲**，
只检测并 warning，让用户在 review 阶段手动合并。

**实现：**

1. `_run_chunk` 在 `split` 阶段后增加边界检查：
   - 取本 chunk 最后一题的 `page_end`，若 ≥ chunk.page_end - 1 且
     该题 `option_lines` 不完整（缺 D/E）→ 记 `warnings += ["chunk_boundary_unclosed: q{n} maybe spans next chunk"]`
   - 检查下一 chunk 的 page_start，看 P2-1 已写入的 `exercise_regions`
     是否标记此处为 "questions" 类型，作为强信号。

2. 默认 `chunk_overlap_pages=3`：
   - chunk[i] 的 OCR/extract 范围扩为 `[page_start, page_end + 3]`
   - chunk[i+1] 的 OCR 仍从 `page_start` 开始
   - 把重复识别出的题号通过 `_pipeline_store` 的全局 `seen_question_numbers`
     去重（**只 dedupe 题号 + page_range，绝不跨 chunk 合并 raw_question_text**，
     避免拼出残缺题干）。
   - env：`IMPORT_PIPELINE_CHUNK_OVERLAP=3`，0 时禁用。

3. 重叠区域命中时：
   - 后到的 chunk skip 已被前 chunk 写库的题号
   - 在 chunk.warnings 留 `boundary_overlap_skipped: [n1, n2]`

**测试：**

- `test_p2_3_boundary_unclosed_warning`：构造一道题选项分布在 chunk[0]
  最后一页（A/B/C）和 chunk[1] 第一页（D），断言 chunk[0].warnings 含
  `chunk_boundary_unclosed`。
- `test_p2_3_overlap_dedup_by_question_number`：chunk[0] 末尾 +3 页
  OCR 出题 #20，chunk[1] 也 OCR 到 #20 → 仅一条入库，chunk[1].warnings
  含 `boundary_overlap_skipped: [20]`。
- `test_p2_3_overlap_disabled_via_env`：`IMPORT_PIPELINE_CHUNK_OVERLAP=0`
  时不扩范围，dedup 逻辑跳过。

------

## P2-4 similarity → GlobalHashIndex

**目标**：similarity_match 阶段不再每个 chunk 跑全量 SQL 查重，改用
进程内 hash 索引，且索引规模可控。

**实现：**

1. 新增 `app/features/global_hash_index.py`：
   - `class GlobalHashIndex`：
     - `async def load(db, *, recent_days: int = 30, batch_id: str | None)`：
       - 从 `questions` 表加载 `recent_days` 内的 `id, question_hash`
       - 从当前 `question_imports.batch_id` 也加载（为了 chunk 间互查）
       - 大小阈值 `HASH_INDEX_MAX_SIZE=500_000`（env 可调），超过则
         set `self._fallback_to_sql = True`，不在内存建索引。
     - `def contains(question_hash: str) -> bool`：内存查或回落 SQL
     - `def add(question_hash: str)`：每写入一题 chunk 内自加，跨 chunk 复用
   - env：`HASH_INDEX_RECENT_DAYS=30`，`HASH_INDEX_MAX_SIZE=500000`

2. `_run_similarity_match`：
   - 收 shared_data 里的 GlobalHashIndex 实例（由 run() 在 chunk 循环外
     `await index.load(db, recent_days=...)` 一次注入）
   - 命中即给 question 标记 `is_duplicate_of=existing_id` + `confidence`
     设较低值（前端展示「疑似重复」），**不直接丢弃**
   - chunk 完成后将本 chunk 已写库题目的 hash `index.add(...)`

3. 复用现有 question_hash 计算逻辑（`question_normalizer.compute_hash`
   或同等函数，沿用，不重写）。

**测试：**

- `test_p2_4_index_loads_recent_only`：mock DB 里有 100 条历史题，60 条
  在最近 30 天，断言 index 仅包含 60 条 hash。
- `test_p2_4_chunk_dedup_via_index`：chunk[0] 写入题 hash=ABC，
  chunk[1] 出现相同 hash → similarity_match 标记为 duplicate（不再走
  SQL 查重 mock）。
- `test_p2_4_falls_back_to_sql_when_threshold_exceeded`：mock load 时
  超过 50 万阈值，断言 `index._fallback_to_sql=True`，contains 走 SQL
  路径。
- 回归 `test_similarity_matcher`：单 chunk 行为不变。

------

## P2-5 manual resume API

**目标**：导入失败后用户可主动触发 resume，仅重跑 failed/pending 的
chunk，不影响已完成 chunk 写入的 review 数据。

**实现：**

1. 新增 endpoint `POST /api/import/resume/{pipeline_id}`：
   - 鉴权：仅 pipeline 创建者本人 / admin（沿用现有依赖注入）
   - 流程：
     - `get_pipeline_progress(pipeline_id)` → 若不存在 404
     - `pipeline.status` 必须 ∈ {paused, failed} → 否则 409 Conflict
     - `get_pending_chunks(pipeline_id)` 取 failed + pending
     - 用 `BackgroundTasks` 启动 `resume_pipeline_background(pipeline_id, pending_chunks)`
     - 立即返回 `{pipeline_id, resumed_chunks: [chunk_index, ...], status: "running"}`

2. 新增 `resume_pipeline_background`（pipeline_orchestrator.py）：
   - 复用 `_run_chunk`，**不重新切 chunk、不创建新 pipeline_id**
   - 每个待恢复 chunk：先 `mark_chunk_running`（清掉旧 error_message），
     再跑，再 update_chunk_status
   - resume 完成后聚合：所有 chunk 都 completed → pipeline.status=completed；
     仍有 failed → 保持 paused，等下一次 resume

3. **PDF 文件来源问题**（v1 简化）：
   - 进入 resume 时原始 file_path 已被清理（API 层 finally unlink）
   - **要求 resume 必须带 `file_path` 或 `file_content`** 重新上传 → endpoint
     接受 multipart 上传或路径参数；前端 import.js 在「失败 chunk 重试」
     时弹出提示让用户重选文件。
   - 这避免「服务器永久持有 400 MB PDF」的存储压力。
   - 进阶方案（v2，不在本次范围）：把 PDF 落到对象存储 + 持久化路径到
     ImportPipeline.source_path。

**测试：**

- `test_p2_5_resume_only_failed_chunks`：mock 一次 import 走完 3 chunks
  (1 failed)，调 resume → 仅 chunk_index=1 被重新 mark_chunk_running，
  其它 chunk 状态不变。
- `test_p2_5_resume_409_when_pipeline_completed`：状态 completed → 拒绝。
- `test_p2_5_resume_404_when_pipeline_missing`。
- `test_p2_5_resume_clears_old_error`：失败 chunk 在 resume 后 error_message
  被清空且重新写入新结果或新错误。

------

## P2-6 status API + 前端适配

**目标**：`GET /api/import/status/{pipeline_id}` 返回的视图除了原有 stage
信息，**追加 `chunk_progress` 字段**，前端可显示进度条 + 失败 chunk 列表
+ resume 按钮。

**改动：**

1. `pipeline_orchestrator.get_pipeline_status`：
   - 沿用 P0-3 的 `_pipeline_store`（瘦身）+ diagnostics 合并视图
   - 新增：调 `get_pipeline_progress(db, pipeline_id, use_cache=True)`
     合并到返回值的 `chunk_progress` 字段。注意：现有 `get_pipeline_status`
     不接受 db，需要扩展签名为 `get_pipeline_status(pipeline_id, db=None)`，
     api 层注入 db。
   - 兼容：db=None 时不带 chunk_progress（图片导入等无 chunk 场景）。

2. API endpoint `GET /api/import/status/{pipeline_id}`（已存在，仅增字段）：
   - response 新增：
     ```json
     {
       "chunk_progress": {
         "total_chunks": 10,
         "completed_chunks": 8,
         "failed_chunks": 1,
         "running_chunks": 1,
         "pending_chunks": 0,
         "question_count": 240,
         "failed_chunk_details": [
           {"chunk_index": 5, "page_start": 201, "page_end": 240,
            "error_message": "OCR timeout"}
         ]
       }
     }
     ```

3. 前端 `miniprogram/pages/import/import.js`：
   - 进度条改成 `completed_chunks / total_chunks`
   - 失败 chunk 列表展示 + 「恢复导入」按钮 → 调 resume 接口
   - 兼容：response 缺 `chunk_progress` 时退化为旧逻辑

**测试：**

- `test_p2_6_status_includes_chunk_progress`：完整跑一遍 mock chunk pipeline
  后调 status，断言 `chunk_progress.completed_chunks==N`。
- `test_p2_6_status_without_db_omits_chunk_progress`：db=None 时
  response 不含 `chunk_progress` 键（向后兼容图片/Excel 导入）。
- 前端：手测 + 一个 e2e（小程序模拟器跑）。

------

## P2-7 端到端测试

**目标**：用一个 mock 400 页扫描 PDF（实际是构造的 fixture）跑完整链路，
验证内存上限 + 失败隔离 + resume 可恢复。

**测试矩阵：**

1. **happy path（400 页 → 10 chunks）**
   - 全部 completed，pipeline.status=completed
   - 断言峰值内存 < 1.5 GB（用 `tracemalloc.get_traced_memory()` 或
     `resource.getrusage().ru_maxrss`，给 chunk 之间留足释放窗口）
   - 题目计数与 chunk 累加一致

2. **chunk 5 失败隔离**
   - mock chunk_index=5 的 OCR 抛 RuntimeError
   - 其余 9 chunk 正常 completed，pipeline.status=paused
   - DB 中 chunk[5].status=failed，error_message 含 RuntimeError 字样
   - review 队列里 9 chunks 的题目都已写入

3. **resume 仅重跑 chunk 5**
   - 调 resume API，mock OCR 这次成功
   - chunk[5].status=completed，pipeline.status=completed
   - 不影响 chunk 0-4 / 6-9 的 batch_id（通过 batch_id 比对）

4. **GlobalHashIndex 跨 chunk 去重**
   - chunk[0] 出题 hash=H，chunk[3] 也 OCR 出 hash=H
   - chunk[3] 那条被 similarity_match 标记 `is_duplicate_of=...`

5. **内存边界**
   - chunk 完成后 `data` 中不再持有该 chunk 的 normalized_blocks /
     raw_questions / questions（用 weakref 哨兵或内存采样验证）

**fixture：**
- `tests/fixtures/scanned_400p_mock.py`：生成 400 页 mock，每页 1~2 题
  的 OCR 结果（避开真实 PaddleOCR）。

------

## 项目背景

这是一个考研408题库导入系统。

主要导入来源：

- 扫描版PDF（核心场景）
- 批量图片导入
- Excel导入

典型文件：

- 王道408教材
- 王道习题册
- 历年真题扫描版

文件规模：

- 100~400页
- 绝大部分为扫描图片页
- 非文本PDF

当前问题：

- OCR耗时较长
- 长文档导入容易超时
- WSL环境导入大文件时出现崩溃
- 怀疑存在内存持续增长问题
- 怀疑Pipeline中存在大量中间结果长期驻留内存

未来目标：

- 稳定支持400页扫描版PDF
- 未来可扩展到1000页
- 内存占用尽量与页数无关
- 支持低配置服务器运行

------

# 核心审计目标

不要优先关注OCR识别率。

优先分析：

**当前Pipeline的数据生命周期(Data Lifecycle)是否合理。**

重点回答：

> 一页PDF数据从生成到最终入库，经历了哪些阶段？
>
> 哪些数据被长期保存在内存中？
>
> 哪些中间结果实际上已经可以提前释放？
>
> 哪些模块会导致内存随页数线性增长？

------

# 请绘制当前Pipeline

分析当前真实执行链路：

```text
PDF
↓
PDF解析
↓
OCR
↓
Normalize
↓
Structure Analysis
↓
Question Split
↓
AI Correction
↓
Question Object
↓
Database Save
```

明确说明：

每个阶段输入什么

输出什么

数据量大概多大

生命周期持续多久

------

# 数据生命周期审计

重点检查：

## 1. PDF页面生命周期

检查：

当前是否：

```python
pages = load_all_pages()
```

或者：

```python
images = convert_all_pages()
```

分析：

- PDF是否一次性全部加载
- 是否一次性生成全部图片
- 图片对象何时释放

评估：

400页扫描PDF场景下的风险。

------

## 2. OCR结果生命周期

检查：

是否存在：

```python
all_ocr_results.append(...)
```

或者：

```python
ocr_blocks = [...]
```

长期累积。

分析：

- OCR结果大小
- bbox数据大小
- layout数据大小
- 是否会随着页数持续增长

输出内存风险评估。

------

## 3. Normalize阶段

检查：

是否存在：

```python
normalized_blocks
```

作为新的完整数据副本。

分析：

- 是否复制全部OCR结果
- 是否形成第二份大对象

------

## 4. Structure Analysis阶段

检查：

是否生成：

```python
analyzed_blocks
```

并长期保留。

分析：

是否形成第三份大对象。

------

## 5. AI Correction阶段

重点审计。

检查当前是否：

```python
全部OCR完成
↓
全部AI纠错
```

还是：

```python
OCR一页
↓
AI纠错一页
```

分析：

- Token消耗
- 内存占用
- 响应时间
- 异常恢复能力

------

## 6. Question Split阶段

检查：

是否：

```python
questions = []
```

持续累积所有题目。

分析：

400页文档情况下：

- Question对象数量
- 内存占用
- 生命周期

------

## 7. 数据库存储策略

检查：

当前是否：

```python
全部处理完成
↓
统一写库
```

还是：

```python
处理一批
↓
写库一批
```

分析：

SQLite与PostgreSQL下的表现差异。

------

# 查找生命周期过长的数据

请列出：

| 对象 | 来源 | 大小 | 当前释放时机 | 是否可提前释放 |
| ---- | ---- | ---- | ------------ | -------------- |
|      |      |      |              |                |

例如：

- PDF图片
- OCR结果
- Normalize结果
- Structure结果
- AI纠错结果
- Question对象

找出：

生命周期最长的Top10对象。

------

# 查找内存增长风险

重点搜索：

```python
append(
extend(
all_results
all_pages
all_questions
cache
buffer
```

分析：

哪些容器会随着页数无限增长。

------

# Generator/Yield机会分析

检查：

哪些代码：

```python
return full_results
```

适合改成：

```python
yield page_result
```

列出：

- 高收益改造点
- 中收益改造点
- 不建议改造点

------

# 流式Pipeline设计

如果发现问题，请设计新的架构：

```text
PDF

↓ 逐页读取

Page

↓ OCR

OCR Result

↓ AI Correction

Corrected Result

↓ Question Parse

Question

↓ Database Save

Commit

↓ Memory Release

Next Page
```

或者：

```text
20页批处理

↓ OCR

↓ AI Correction

↓ Parse

↓ Save

↓ Release
```

说明：

为什么选择该方案。

------

# 断点恢复能力

分析：

当前导入过程中：

如果第287页失败：

是否需要重新处理1~286页？

设计：

```text
导入任务
↓
记录已完成页码
↓
失败
↓
从失败页恢复
```

方案。

------

# 输出要求

请输出：

## 1. 当前架构图

## 2. 数据生命周期分析

## 3. 内存风险分析

## 4. 生命周期最长对象分析

## 5. 流式改造方案

## 6. Generator/Yield改造建议

## 7. 数据库存储优化建议

## 8. 断点恢复方案

## 9. 实施优先级

请先完成审计报告，不要修改代码。

------

