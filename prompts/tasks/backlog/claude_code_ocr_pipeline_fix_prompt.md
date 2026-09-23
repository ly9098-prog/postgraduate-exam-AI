> **不要按本文施工（2026-09-23）。** 这是收进 `backlog/` 的历史任务书，不代表当前工作。现行范围见 `docs/project/ROADMAP.md`。

# 修复任务：OCR Pipeline、批量图片导入与数据库一致性

你现在在本地代码仓库中工作。请直接检查并修改代码，不要只给建议或伪代码。

默认项目路径：

```bash
cd /home/lmh/projects/postgraduate-ai/backend
```

如果当前目录已经是仓库根目录，以实际目录为准。

## 一、工作原则

1. 先执行 `git status --short`，识别用户已有的未提交改动。不得覆盖、回滚或格式化无关文件。
2. 不要盲信本文给出的文件行号；先通过符号名、调用关系和测试确认问题是否仍存在。
3. 只修改与本任务有关的代码、ORM、迁移、测试和文档，不做无关重构。
4. 每个修复必须包含回归测试。不能通过删除有效断言、降低测试标准或重新引入已废弃接口来让测试变绿。
5. 当前 OCR 纠错的正式架构是 `OCRFixRouter -> PaddleOCR-VL -> DeepSeek -> Rule`。不要为了兼容旧测试重新实现或恢复 `_call_ocr_api`、旧版 `ocr_fallback` 网络调用路径。
6. 数据库修改必须通过项目现有迁移体系完成。先检查是否使用 Alembic；如使用，生成可升级且可回滚的迁移。
7. 对外 API 尽量保持向后兼容。确需改变请求结构时，保留旧字段兼容逻辑并返回明确的弃用信息。
8. 所有状态转换必须集中定义，不要在不同模块中散落裸字符串。
9. 不要在未验证的情况下宣称“DAG、SSOT、断点恢复或幂等已完成”。最终报告必须列出实际实现和仍未解决的内容。
10. 不要停在计划阶段。完成代码、迁移、测试和验证；只有遇到无法从仓库推断的外部配置时才记录阻塞原因。

## 二、总体目标

修复 OCR Pipeline 外层编排中影响生产一致性的 P0 问题：

1. artifact 级断点恢复跳过未执行阶段。
2. 缓存重解析违反 `ImportBatchJobItem` 状态机。
3. `ocr_mode=api` 被本地 PaddleOCR 依赖检查错误拦截。
4. 多文件上传共用 `image_id`，与数据库唯一约束冲突。
5. Job 在跨图片 merge 完成前被标记为 `completed`，SSE 过早结束。
6. Trace Event 的 `step/status` 与业务 Job 状态混用。
7. 旧 OCR 测试仍验证已废弃接口，测试集与新架构漂移。

在 P0 全部通过后，再完成本文列出的 P1 数据一致性改进。不要先做大规模架构重写。

---

# 三、实施顺序

## Phase 0：建立基线

先执行并记录：

```bash
git status --short
python -m compileall .
pytest --collect-only -q
```

检查测试依赖配置。如果仓库没有统一的测试依赖文件，补充到现有的 `pyproject.toml`、`requirements-test.txt` 或项目当前采用的等价文件中，不要另造重复体系。

已知测试环境可能缺少：

- `aiosqlite`
- `passlib`
- 项目内部 `rag` 包
- `scripts/backfill_question_hash.py`

先区分“测试依赖未声明”和“测试引用不存在模块”，不要把内部模块缺失简单当作第三方依赖安装。

运行与本任务相关的基线测试，记录失败：

```bash
pytest -q \
  tests/test_services/test_ocr_service.py \
  tests -k "pipeline or checkpoint or resume or batch_image or ocr_fix or option or noise or dag"
```

如测试路径与实际仓库不同，搜索对应测试类和符号。

---

# 四、P0 修复任务

## P0-1：修复 artifact 级断点恢复语义

重点检查：

- `features/pipeline_orchestrator.py`
- `_build_pipeline()`
- artifact 保存逻辑
- `_restore_from_artifacts()` 或同等恢复函数
- `features/pipeline_artifacts.py`

当前风险：

```text
normalize_schema
-> code_language_noise_clean
-> code_structure_reconstruct
-> classify_questions
-> batch_validation
-> batch_dedup
-> repair
-> ai_validation
-> similarity_match
```

已观察到的错误语义：

1. `normalize_schema` artifact 在 `code_language_noise_clean` 之前保存，但恢复时把噪声清洗也当成已完成。
2. `repair` artifact 在 `ai_validation`、`similarity_match` 之前保存，但恢复时把它们也跳过。

### 实现要求

1. 找到每个 artifact 实际保存的时点，明确其含义是“哪个 stage 成功完成后的输出”。
2. 不允许继续手工维护容易漂移的 `preceding` 集合。
3. 从真实 stage 顺序动态推导 `completed_stages`，或让 artifact 显式保存：

```python
completed_stage: str
completed_stage_index: int
pipeline_version: str
stage_versions: dict[str, str]
```

4. 恢复时只能跳过 artifact 明确覆盖的阶段。
5. 如果 artifact 的 pipeline/version/config 不兼容，应拒绝恢复并记录原因，而不是静默加载。
6. 不修改已有 chunk 级 checkpoint/resume 的正确行为。

### 必须新增测试

新增 artifact 等价性测试，至少覆盖：

- 从 `normalize_schema` artifact 恢复。
- 从 `repair` artifact 恢复。
- artifact 版本不兼容时拒绝恢复。

核心不变式：

```python
canonicalize(full_run(input)) == canonicalize(resumed_run(input, artifact_stage))
```

比较至少包括：

- stem/content
- options
- answer
- warnings/quality flags
- AI validation 结果
- similarity match 结果
- 最终 review 写入数据

测试中不要只比较题目数量。

---

## P0-2：修复缓存重解析状态机

重点检查：

- `features/batch_image_import_service.py`
- `reparse_item_from_cache()`
- `_guard_item_transition()`
- `_update_item()` 或等价函数
- `models/import_batch_job.py`

当前状态机类似：

```text
pending -> processing -> succeeded/failed
succeeded -> 无
failed -> 无
```

但缓存重解析需要从 `succeeded` 或 `failed` 重新进入处理，当前会触发：

```text
failed -> failed
succeeded -> succeeded
failed -> succeeded
```

非法状态转换。

### 实现要求

1. 增加明确的 `reprocessing` 状态，推荐状态机：

```text
pending -> processing -> succeeded | failed
succeeded -> reprocessing
failed -> reprocessing
reprocessing -> succeeded | failed
```

2. `reparse_item_from_cache()` 必须在运行新 Pipeline 之前原子地将条目转为 `reprocessing`。
3. 如果无法进入 `reprocessing`，不得创建新 review batch。
4. 重解析失败时不要覆盖最后一次成功结果。至少保留：

```text
previous_review_batch_id
reparse_attempt
reparse_started_at
reparse_finished_at
reparse_config_hash
```

如果项目已有 attempt/history 表，优先复用，不要重复建模。
5. 如果本次重解析成功，再原子切换到新 review batch；旧批次先标记 superseded，不要先删除。
6. 防止重解析异常后遗留孤立 `question_imports` 或 review batch。

### 数据库迁移

按实际模型增加必要字段和状态支持。数据库字段是字符串时也要在 Python 层建立统一枚举和转换校验。

### 必须新增测试

- `failed -> reprocessing -> succeeded`
- `succeeded -> reprocessing -> succeeded`
- `reprocessing -> failed` 时保留上一次成功批次
- 同一 item 同时发起两次 reparse，只允许一个获得处理权
- Pipeline 在创建新 batch 后抛异常，不遗留活动孤立批次

使用真实 SQLite 测试唯一约束和事务，不要全部 mock。

---

## P0-3：修复 `ocr_mode=api` 路由前置检查

重点检查：

- 批量图片上传 API，例如 `api/v1/admin_imports.py`
- 单图上传 API，例如 `api/v1/imports.py`
- `features/batch_image_import_service.py`
- OCR 模型配置解析函数

当前问题：API 入口在读取 `ocr_mode` 路由之前，无条件检查：

```python
settings.OCR_ENABLED
importlib.util.find_spec("paddleocr")
```

导致纯远程 PaddleOCR-VL 部署无法使用 `ocr_mode=api`。

### 实现要求

1. 建立唯一的 OCR mode 解析/校验函数，例如：

```python
resolve_ocr_mode(mode: str) -> Literal["local", "api"]
validate_ocr_mode_dependencies(mode)
```

2. 仅在 `local` 模式检查：

- `settings.OCR_ENABLED`
- 本地 `paddleocr` 包
- 本地模型/GPU 配置

3. 在 `api` 模式检查：

- 远程 OCR 模型配置存在且启用
- API URL 和密钥可解析
- 不要求安装本地 PaddleOCR

4. 非法模式返回 422，不要静默回退。
5. 单图、批量图、缓存重解析复用同一个 mode 解析逻辑。

### 必须新增测试

- monkeypatch `find_spec("paddleocr") -> None`，`ocr_mode=api` 仍可进入 `_run_vl_ocr()`。
- 同样环境下 `ocr_mode=local` 返回明确依赖错误。
- 非法 mode 返回 422。
- API 模式配置缺失时返回远程配置错误，而不是本地 PaddleOCR 错误。

---

## P0-4：修复多文件幂等键和唯一约束冲突

重点检查：

- 批量图片上传请求模型和 endpoint
- `create_batch_job()`
- `ImportBatchJobItem`
- 唯一约束 `uq_batch_import_id_image`

当前 API 接受多张文件，但只接受一组：

```text
batch_id
image_id
request_id
```

随后将相同 `image_id` 写入所有 item，与：

```text
UNIQUE(batch_import_id, image_import_id)
```

冲突。

### 目标语义

- `request_id`：一次批量请求的幂等键。
- `batch_import_id`：上游业务批次标识。
- `image_import_id`：单张图片唯一标识。
- `source_sha256`：图片内容级幂等和去重标识。

### 实现要求

1. 优先支持每张图片独立 metadata。根据现有 FastAPI 上传形式选择兼容方案，例如：

```text
files[]
image_ids[]
```

要求数组长度与 files 一致；或接受 JSON manifest 加文件上传。
2. 保留旧的单文件 `image_id` 用法。
3. 多文件请求如果只传一个旧版 `image_id`：
   - 不得把同一个值写给每一张图。
   - 可以生成稳定的派生 ID，如 `image_id:seq`，同时返回 deprecation warning；或直接返回清晰的 422。优先选择不破坏现有单文件客户端的方案。
4. 增加 `source_sha256` 字段和合适索引，用于内容级重复检测。不要仅依赖文件名。
5. `create_batch_job()` 遇到重复请求时必须返回已有 Job，而不是先写临时文件再失败。
6. 处理并发插入竞争：捕获唯一约束异常后重新读取已存在记录，保证幂等。

### 必须新增测试

使用真实 SQLite：

- 两张图片、两个 image ID，成功创建两个 item。
- 两张图片、同一个旧版 image ID，按兼容策略处理且不触发 IntegrityError。
- 同一 request ID 重试，返回同一个 Job。
- 两个并发请求使用同一幂等键，只产生一个 Job。
- 相同内容、不同文件名能通过 `source_sha256` 识别。

---

## P0-5：修复 merge 前 Job 提前完成和 SSE 过早关闭

重点检查：

- `run_batch_job()`
- `_merge_image_texts()` 或等价函数
- Job 状态更新
- SSE/事件流 endpoint
- `ImportBatchJob`

当前错误顺序类似：

```text
item 全部处理完成
-> job.status = completed
-> 执行 merge
```

SSE 看到 `completed` 后就发送 done 并关闭，但 merge 还没有完成。

### 实现要求

1. 增加 Job 状态：

```text
queued -> running -> merging -> completed
                         -> completed_with_warnings
                         -> failed
```

如项目不希望增加 `completed_with_warnings`，至少增加 `merging` 并在 merge 失败时将 Job 标为 failed 或显式保存 merge failure。
2. 只有以下条件全部完成后才能进入 `completed`：

- 所有 item 已到终态
- 需要 merge 时 merge 已成功
- item 的最终 `review_batch_id` 已完成切换
- 最终 trace event 已写入

3. SSE 只能在真正终态关闭。
4. 增加 Job 字段或等价结构：

```text
merge_status
merged_batch_id
merge_error
merge_started_at
merge_finished_at
```

5. merge 过程使用事务或 Saga：

```text
create merged batch as pending
validate merged batch
atomic switch item references
mark merged batch active
mark old batches superseded
later purge old batches
```

不得边更新 item 边物理删除旧 batch。

### 必须新增测试

- merge 运行时 Job 为 `merging`，SSE 不发送 done。
- merge 成功后才发送 completed/done。
- merge 失败时状态和错误可查询。
- merge 中途异常时，不出现一半 item 指向新批次、一半指向旧批次。
- 重复执行 merge 具有幂等性。

---

## P0-6：分离 Job 状态与 Trace Event 状态

重点检查：

- `BatchJobTraceEvent`
- `_set_job_status_with_trace()`
- trace step/status 枚举
- `DB_SCHEMA.md`

当前问题：Job 的 `completed` 被直接写入 Trace Event.status，但文档中的事件状态是：

```text
running / success / failed
```

同时实际代码使用了文档未列出的 `waiting` step。

### 实现要求

1. 定义集中枚举：

```python
class BatchJobStatus(...): ...
class BatchItemStatus(...): ...
class TraceEventStatus(...): RUNNING, SUCCESS, FAILED
class TraceStep(...): UPLOAD, OCR, PIPELINE, MERGE, DONE, ERROR, WAITING
```

2. Job 状态变化写 trace 时进行明确映射，例如：

```text
job.status=completed
trace.step=done
trace.status=success
```

3. 不允许将 `completed` 直接写入 `TraceEvent.status`。
4. 更新数据库文档和 API schema。
5. 如数据库支持 CHECK 约束且项目已有类似实践，可增加；否则至少在 ORM/API 层严格校验。

### 必须新增测试

- 所有 Job 状态到 Trace Event 的映射。
- 数据库中不会出现 `trace.status=completed`。
- `waiting` 等实际 step 已注册并可序列化。

---

## P0-7：迁移旧 OCR 测试到 OCRFixRouter

重点检查：

- `tests/test_services/test_ocr_service.py`
- OCRFixRouter 和 adapter 测试
- `_call_ocr_api`
- `ocr_fallback`

当前已有约 11 个测试仍要求已删除的旧接口工作。不要恢复这些接口。

### 实现要求

1. 删除或重写依赖 `_call_ocr_api` 的测试。
2. `ocr_fallback()` 如果已经明确 deprecated/NotImplemented，测试应验证其弃用行为，而不是要求它重新联网。
3. 把实际能力迁移到以下测试目标：

- `PaddleOCRVLAdapter`
- `OCRFixRouter`
- adapter 异常时进入下一 adapter
- adapter 返回空结果时进入下一 adapter
- adapter 返回非空但质量/安全门拒绝时进入下一 adapter
- 全部失败时 Rule fallback

4. 不能仅按“非空文本”判定 adapter 成功；将质量校验纳入 Router 或候选选择层，使被安全门拒绝的 VL 结果可以继续回退 DeepSeek/Rule。
5. 修复注释和实现不一致的 manual mode 默认 adapter 行为。

### 必须新增测试

- VL 返回非空危险文本，validator 拒绝，Router 继续 DeepSeek。
- VL 超时，继续 DeepSeek。
- VL 和 DeepSeek 都失败，Rule 返回。
- validator 接受 VL 时不调用后续 adapter。

---

# 五、P1 数据一致性改进

仅在全部 P0 测试通过后执行。

## P1-1：临时文件生命周期

修复批量上传中的临时文件泄漏：

- 重复请求提前返回时删除本次新建的临时文件。
- `create_batch_job()` 异常时清理。
- 只有后台 Worker 明确接管后，API 层才放弃文件所有权。
- 如果后续改用对象存储，保存对象键，不跨进程依赖本地临时路径。

新增测试：重复 Job、数据库异常、任务入队异常时均无遗留文件。

## P1-2：单图异步入口不阻塞事件循环

检查单图 async endpoint，禁止直接执行同步 `ocr_image()`。

使用：

```python
await asyncio.to_thread(ocr_image, image_content)
```

如果 PaddleOCR 不适合多线程，使用项目级专用 executor/worker，而不是阻塞事件循环。

## P1-3：阶段失败策略

为 Pipeline stage 增加统一失败策略：

```text
FATAL
DEGRADE
ITEM_LEVEL
```

推荐：

```text
extract                    FATAL
normalize_text             FATAL
split                      FATAL
normalize_schema           FATAL
code_structure_reconstruct ITEM_LEVEL 或 DEGRADE
similarity_match           DEGRADE
math_detect                DEGRADE
table_detect               DEGRADE
review                     FATAL
```

最终状态区分：

```text
completed
completed_with_warnings
failed
```

辅助阶段失败不应自动阻止可审核题目进入审核池。

## P1-4：数据库级正式题去重

当前应用层按 `subject + question_hash` 查询后插入，存在并发竞态。

在确认业务语义后增加数据库级唯一约束。PostgreSQL 推荐部分唯一索引：

```sql
CREATE UNIQUE INDEX uq_questions_active_subject_hash
ON questions(subject, question_hash)
WHERE question_hash IS NOT NULL
  AND is_active = true;
```

SQLite 测试环境使用等价可测试方案。

发布服务捕获唯一冲突并返回 duplicate，而不是 500。

## P1-5：审核暂存幂等键和 review batch 主表

评估并实现：

1. 为 `question_imports` 增加稳定 `idempotency_key`，避免 Worker 重试或恢复重复写入。
2. 新建正式的 `import_review_batches` 主表，至少包含：

```text
batch_id PK
pipeline_id
job_id
status
source_type
created_at
superseded_by
```

3. `ImportBatchJobItem.review_batch_id`、chunk 和 question imports 引用该表。
4. 旧 batch 不立即删除，先标记 superseded。

如果该改动范围过大，先输出独立迁移设计和测试，但不得用临时字符串逻辑继续扩大技术债。

## P1-6：统一文档和状态定义

更新 `DB_SCHEMA.md` 和相关架构文档：

- `question_imports.status` 实际包含 `published` 时，文档和状态机必须体现。
- `ImportBatchJob.started_at` 不应在 queued 时写入；增加 `queued_at`，真实运行时再写 `started_at`。
- Trace step/status 与代码一致。
- 明确 DAG 是否接入主 Pipeline。未接入时不要称其为“主 DAG 编排已完成”。

---

# 六、禁止事项

1. 不要重新引入旧 `_call_ocr_api`。
2. 不要为了测试通过而把 `ocr_fallback()` 恢复成第二套远程 OCR 路径。
3. 不要删除唯一约束来掩盖多文件 `image_id` 设计错误。
4. 不要允许任意状态到任意状态转换。
5. 不要把 merge 异常仅写日志后仍返回 completed。
6. 不要通过 sleep、扩大超时或跳过测试解决并发问题。
7. 不要在 API 中记录 2,000 字原始 OCR 文本到 INFO 日志。
8. 不要在一个超大提交中顺便格式化整个仓库。
9. 不要把所有测试都 mock 掉；状态、事务和唯一约束必须有真实 SQLite 集成测试。
10. 不要修改无关业务表和用户功能。

---

# 七、测试要求

修复完成后至少执行：

```bash
python -m compileall .

pytest -q tests/test_services/test_ocr_service.py

pytest -q tests -k "artifact and resume"
pytest -q tests -k "reparse or batch_image"
pytest -q tests -k "ocr_mode or ocr_fix or router"
pytest -q tests -k "merge or trace or sse"
pytest -q tests -k "idempot or unique or question_hash"

pytest -q
```

如果完整测试因仓库本来就缺失的内部模块无法收集：

1. 修复属于本仓库的错误引用。
2. 将确属外部可选模块的测试使用现有项目机制显式 skip，并写清原因。
3. 不得用全局 `--ignore` 隐藏与本次修改有关的测试。
4. 最终列出：收集数、通过数、失败数、跳过数、xfailed/xpassed 数。

建议增加一个专门的回归测试文件，例如：

```text
tests/test_ocr_pipeline_production_invariants.py
```

集中验证以下生产不变式：

```text
恢复运行与完整运行等价
同一幂等请求最多产生一个 Job
一个 image ID 只属于一张图片
终态 Job 不再继续做 merge
SSE done 等于真实终态
重解析必须经过 reprocessing
Trace status 只允许 running/success/failed
API OCR 不依赖本地 PaddleOCR
```

---

# 八、提交和输出要求

按以下逻辑拆分原子提交；如果不能自动提交，至少按这些分组汇报修改：

1. `fix(pipeline): make artifact resume stage-accurate`
2. `fix(import): add reprocessing state and safe cached reparse`
3. `fix(ocr): separate local and api dependency validation`
4. `fix(import): make per-image idempotency keys unique`
5. `fix(import): complete merge before terminal job state`
6. `fix(trace): separate event status from job status`
7. `test(ocr): migrate legacy fallback tests to OCRFixRouter`
8. `fix(db): add concurrency-safe constraints and migrations`
9. `docs: align database and pipeline state documentation`

最终回复必须包含：

## 1. 实际修改文件

逐个列出文件和修改目的。

## 2. 数据库迁移

列出升级、回滚方式和数据兼容策略。

## 3. 修复结果

逐项说明 P0/P1 是否完成，不得只写“已优化”。

## 4. 测试结果

贴出实际命令和摘要。

## 5. 兼容性影响

说明 API 请求、状态枚举、SSE、数据库字段是否有变化。

## 6. 未完成项

如存在必须明确说明原因、风险和下一步，不得隐藏。

在完成之前，请持续直接修改和验证代码，不要只返回计划。
