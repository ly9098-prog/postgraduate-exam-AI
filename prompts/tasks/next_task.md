你是一名资深 Python/FastAPI/SQLAlchemy 异步后端工程师。请基于当前 backend/app 代码，对 OCR 批量导入链路二次补丁后的残留问题继续做小范围修复。

重要背景：

上一轮数据库循环操作优化和二次兼容补丁已经完成，大部分问题已修复，包括：

- batch image trace 不再高频锁 job 行；
- poll_job_summary 已改为 SQL GROUP BY；
- API OCR 模式已改成 job 级预取模型配置；
- submit_to_review 已改为批量 flush；
- 同一 flush 批次内重复题检测已补；
- 重复 request_id 返回已有 job 时已清理临时文件；
- SSE 已兼容 lastEventId、since_seq、Last-Event-ID；
- completed_with_warnings 已加入 SSE 终态；
- trace event API 已同时返回 id 和 seq，seq 兼容为 id；
- ORM model 已补 batch_job_trace_events(job_id, id) 和 import_batch_job_items(job_id, status) 组合索引。

本轮不要大改，不要回滚已有优化，只修复下面 3 个残留点。

# ============================================================ 任务一【必须修】：修复 _merge_image_texts 缺少 running 状态跳过逻辑

位置大概率在：

app/features/batch_image_import_service.py

函数大概率是：

_merge_image_texts(...)

当前问题：

函数开头已经会通过 FOR UPDATE 读取 ImportBatchJob，并且会判断：

if job.merge_status == "completed" and job.merged_batch_id:
return ...

然后设置：

job.merge_status = "running"
job.merge_started_at = now
await db.commit()

但是当前缺少对：

job.merge_status == "running"

的判断。

这会导致如果两个 merge 入口几乎同时进入，第二个请求在第一个请求已经把 merge_status 持久化为 running 后，仍然继续执行 merge，而不是跳过。

请修复：

在设置 merge_status="running" 之前增加判断：

if job.merge_status == "running":
return {
"merged": False,
"reason": "merge already running",
"review_batch_id": job.merged_batch_id,
}

请结合项目实际返回结构调整字段，但必须满足：

- 不再重复执行 merge；
- 不会抛异常；
- 不会把 running 状态覆盖掉；
- 不会破坏 completed 后复用 merged_batch_id 的逻辑；
- 不会破坏 merge 成功 / 失败后的状态收口。

如果项目已有 logger，请记录一条 info 或 warning：

logger.info("Batch image merge already running", extra={...})

注意：

- 不要删除 FOR UPDATE。
- 不要删除 commit。
- 不要重构整个 merge 流程。
- 不要改变外部 API 响应格式，除非测试需要兼容字段。

请新增或更新测试：

1. 第一次进入 _merge_image_texts 时，会设置 merge_status="running" 并继续执行。
2. 当 job.merge_status 已经是 "running" 时，再次调用 _merge_image_texts 应直接跳过，不执行后续 merge pipeline。
3. 当 job.merge_status 是 "completed" 且有 merged_batch_id 时，仍返回已有 merged_batch_id。
4. merge 失败时状态仍能收口为 failed，不会永久 running。
5. 没有可合并内容时不会永久 running。

# ============================================================ 任务二【增强项】：request_id 并发幂等风险评估与保守修复

位置大概率在：

app/features/batch_image_import_service.py
app/models/import_batch_job.py
app/api/v1/admin_imports.py

当前现状：

request_id 当前存放在 ImportBatchJobItem 上。
_create_batch_job / create_batch_job 里会先查：

_find_job_by_request_id(db, request_id)

如果查到已有 job，则返回 duplicate stub。

这个逻辑能解决“第一次请求完成创建后，第二次重复请求”的幂等问题。

残留风险：

如果两个相同 request_id 的请求并发到达，可能两个请求都先查不到 existing，然后都创建 job。因为 request_id 在 item 表上，且同一个 job 下多张图片会共享同一个 request_id，所以不能简单给 ImportBatchJobItem.request_id 加唯一索引。

请先做代码级评估：

1. 全局搜索：
   - request_id
   - _find_job_by_request_id
   - ImportBatchJobItem.request_id
   - ImportBatchJob
   - create_batch_job
   - batch image upload
2. 判断当前 ImportBatchJob 是否已有 request_id 字段。
   - 如果已有，请使用该字段并确认有唯一索引。
   - 如果没有，不要贸然破坏性迁移。

优先修复方案 A：如果 ImportBatchJob 已经有 request_id 字段

- 创建 job 时把 request_id 写到 ImportBatchJob.request_id；
- 对 ImportBatchJob.request_id 使用唯一约束或唯一索引；
- _find_job_by_request_id 优先查询 ImportBatchJob.request_id；
- 捕获 IntegrityError，如果并发创建冲突，则 rollback 后查询已有 job 并返回 duplicate stub；
- 保持 ImportBatchJobItem.request_id 兼容字段不变，不删除。

修复方案 B：如果 ImportBatchJob 没有 request_id 字段，且项目有 Alembic/migration 体系

- 可以新增 nullable request_id 字段到 ImportBatchJob；
- 增加唯一索引，注意 nullable 兼容；
- 创建 job 时写入 request_id；
- _find_job_by_request_id 优先查 ImportBatchJob.request_id，回退查 ImportBatchJobItem.request_id；
- 捕获唯一冲突；
- 生成对应 migration；
- 保持旧数据兼容。

修复方案 C：如果项目当前没有迁移体系，或新增字段风险较高

不要强行改表结构。
请在代码中至少做保守增强：

- 在同一个事务内尽量缩小“查 existing → 创建 job/items”的窗口；
- 创建完成后再次检查同 request_id 是否已有更早 job；
- 如果发现已有更早 job，当前新建 job 标记为 cancelled/duplicate 或直接清理本次资源并返回已有 job；
- 但不要做危险删除，不要破坏已有业务。

如果你判断此问题暂不适合代码层修复，请在报告中明确说明：

- 当前已支持非并发重复 request_id；
- 并发重复 request_id 需要 DB 唯一约束才能彻底解决；
- 推荐后续在 ImportBatchJob 增加 request_id + unique index；
- 本轮是否做了保守增强。

请新增或更新测试，按实际修复方案选择：

- 非并发重复 request_id 仍返回已有 job。
- 如果实现了唯一约束，模拟 IntegrityError 后能返回已有 job。
- 如果没有实现唯一约束，至少测试现有幂等行为未被破坏。
- 不要误删正在使用的 temp file。
- 不要给 ImportBatchJobItem.request_id 加全局唯一约束，因为多图片同 job 会共享 request_id。

# ============================================================ 任务三【低风险增强】：submit_to_review 同批重复 key 改为 (subject, question_hash)

位置大概率在：

app/features/review_service.py

当前问题：

submit_to_review 的同批重复 tracking 目前大概率使用：

seen_hashes: dict[str, int]
pending_first_qi_by_hash: dict[str, QuestionImport]

也就是只按 question_hash 判断同批重复。

如果一次 submit_to_review 中混入多个 subject，理论上可能出现不同 subject 但 question_hash 相同，从而被误判为同批重复。

请修复：

将同批重复 tracking key 从 question_hash 改成：

(subject, question_hash)

推荐写法：

DuplicateKey = tuple[str | None, str]

def _make_duplicate_key(subject: str | None, question_hash: str | None) -> DuplicateKey | None:
if not question_hash:
return None
return (subject, question_hash)

然后把：

seen_hashes[question_hash]
pending_first_qi_by_hash[question_hash]
pending_duplicate_links

相关逻辑改为基于 duplicate_key。

注意：

- 正式题库重复检测如果本来是按 subject + question_hash 查询，要保持不变。
- duplicate_of_import_id 仍指向同 subject 同 hash 的第一条。
- 不要破坏跨 flush 批次重复检测。
- 不要破坏同一 flush 批次重复检测。
- 不要破坏批量 flush 优化。
- 不要破坏 _log_multi_blank_review_item。
- 如果 submit_to_review 的入参天然保证同一 subject，也可以做兼容性增强，不影响原行为。

请新增或更新测试：

1. 同 subject + 同 question_hash：第二题标记 possible_duplicate。
2. 不同 subject + 同 question_hash：不应互相标记 duplicate_of_import_id。
3. 跨 flush 批次、同 subject + 同 hash：仍能标记 duplicate_of_import_id。
4. 100+ 题批量 flush 次数仍保持优化，不回退逐题 flush。

# ============================================================ 任务四【清理项】：修正文档/注释中过时的 trace seq/lock 描述

位置可能在：

app/features/batch_image_import_service.py
app/schemas/admin_imports.py
app/models/import_batch_job.py

当前问题：

上一轮之后，item trace 已经不再每条都锁 job 行，也不再依赖 DB 里的 BatchJobTraceEvent.seq 做增量读取。API 输出兼容 seq，但 seq 当前等同于 id。

请全局搜索并修正过时注释：

- “caller must hold FOR UPDATE lock”
- “seq is per-job monotonic”
- “next_event_seq 每个事件递增”
- “poll by seq”

修正为：

- trace 增量读取基于 BatchJobTraceEvent.id；
- API 返回 seq 是兼容字段，当前等同于 id；
- BatchJobTraceEvent.seq / ImportBatchJob.next_event_seq 为兼容保留字段，不建议新逻辑依赖；
- item-level trace 不要求持有 job row lock。

注意：

- 只改注释、schema 描述或 docstring。
- 不要删除字段。
- 不要做破坏性迁移。

# ============================================================ 测试要求

请运行：

pytest

如果测试较多，至少运行：

pytest tests/test_features/test_batch_import_optimizations.py
pytest tests/test_features/test_review_service.py
pytest tests/test_api/test_admin_imports.py

如果某些测试文件不存在，请说明。

如果项目有 ruff/mypy/flake8，按项目现有命令运行，不要新增依赖。

# ============================================================ 重要约束

- 本轮是小补丁，不要大规模重构。
- 不要回滚上一轮 DB 优化。
- 不要重新引入每条 trace 都 FOR UPDATE 锁 job 行。
- 不要把 submit_to_review 改回逐题 flush。
- 不要删除 BatchJobTraceEvent.seq。
- 不要删除 ImportBatchJob.next_event_seq。
- 不要删除 ImportBatchJobItem.request_id。
- 不要给 ImportBatchJobItem.request_id 加全局唯一约束。
- 不要破坏旧前端依赖 seq 字段。
- 不要破坏 SSE lastEventId / since_seq / Last-Event-ID 兼容。
- 不要把 api_key、api_key_encrypted、完整 model_config 写入 options、trace event、日志或数据库。
- 不要引入 Redis、Celery、Kafka 等新基础设施。
- 如果新增 DB 字段或索引，请确认项目迁移体系；没有迁移体系时不要强行做生产不可控改动。
- 修改前请先全局搜索：
  - _merge_image_texts
  - merge_status
  - merged_batch_id
  - request_id
  - _find_job_by_request_id
  - ImportBatchJobItem.request_id
  - ImportBatchJob
  - submit_to_review
  - seen_hashes
  - pending_first_qi_by_hash
  - duplicate_of_import_id
  - BatchJobTraceEvent.seq
  - next_event_seq
  - poll_trace_events
  - since_seq
  - lastEventId

修复完成后请输出报告，包括：

1. 修改了哪些文件；
2. 每个残留问题如何修复；
3. request_id 并发幂等是否已彻底解决，如果没有，为什么；
4. 是否做了 DB schema / migration 修改；
5. 执行了哪些测试；
6. 是否还存在残留风险；
7. 是否可以进入真实上传验收。
