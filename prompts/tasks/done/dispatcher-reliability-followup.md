> **状态：已完成。** 下文是当时的任务书，只作记录。不要再按其中的步骤执行。

你是一名资深 Python/FastAPI、SQLAlchemy Async、PostgreSQL、Redis、分布式任务系统和生产可靠性工程师。

当前项目已完成 P0.5 修复，已报告：

- 新增 `FencingRejectedError`
- 新增 `conditional_update_with_fencing()`
- Redis 空队列与 Redis 不可用语义已分离
- Dispatcher 已增加 Redis 故障退避和熔断
- staging refcount 已改为复用共享 async Redis pool
- 123/123 核心 P0 测试通过
- ruff 通过
- compileall 通过
- 当前测试未发生 OOM

本阶段不要重复已经完成的基础重构。

本阶段目标是：

> Phase 6：证明修复真正接入业务主路径，在真实 Redis/PostgreSQL 和真实进程故障条件下完成验收，并直接投入测试用户使用。

当前用户量少，项目仍处于测试阶段，因此：

- 不做灰度发布；
- 不做复杂 canary；
- 不做双版本长期并行；
- 修复验证通过后直接启用；
- 使用过程中发现非阻断问题再继续修复。

但以下事项仍是测试使用前的阻断条件：

- stale Worker 可以写入业务数据；
- Redis 故障被识别为空队列；
- durable task 丢失或重复执行；
- kill -9 后任务无法恢复；
- staging 文件提前删除；
- cloud profile 加载本地 OCR；
- 任务完成后 processing/retry 持续增长；
- Worker SIGTERM 导致任务永久卡死；
- 数据库 migration 状态不一致。

直接修改实际代码、测试、部署配置和运维工具。不要只输出建议或伪代码。

------

# 一、首先验证 DB fencing 是否真正接入业务写入

当前新增了：

```python
conditional_update_with_fencing()
```

但“新增函数”不代表已经解决 TOCTOU。

必须搜索并列出该函数的所有调用位置：

```bash
rg "conditional_update_with_fencing" app
```

输出表格：

```text
handler
business model
business table
write operation
uses conditional fencing?
transaction boundary
```

至少覆盖：

- 单文件导入；
- PDF 导入；
- 图片导入；
- Excel 导入；
- batch image；
- resume；
- admin resume；
- formula batch；
- AI prewarm 或其他异步 AI 写入；
- pipeline 最终状态；
- 导入审核状态；
- 任务失败、取消和人工审核状态。

如果函数只存在于 `db_fencing.py`，或者只在 Worker complete 前调用：

判定为未完成。

------

# 二、修复“只拦 complete，不拦业务写入”的风险

以下流程仍然不安全：

```text
Worker A 生成结果
→ 普通 UPDATE 写入业务表
→ fencing check 失败
→ 不调用 complete_v2
```

因为业务数据已经被旧 Worker 覆盖。

必须改成：

```text
Worker 生成结果
→ 开启短事务
→ fenced parent UPDATE
→ rowcount == 1
→ 写入相关 child records
→ commit
→ complete_v2
```

如果 fenced parent UPDATE 的 rowcount 为 0：

```text
rollback
raise FencingRejectedError
禁止写 child records
禁止 complete
禁止 fail 当前新 generation
```

所有关键最终写入必须使用类似条件：

```sql
WHERE id = :business_id
  AND current_task_id = :task_id
  AND current_owner_token = :owner_token
  AND execution_generation = :generation
```

禁止仅依赖：

```python
SELECT current generation
Python 比较
普通 ORM assignment
commit
```

------

# 三、多表写入必须处于同一短事务

如果导入任务会同时写：

- pipeline；
- import job；
- questions；
- knowledge points；
- review queue；
- formula records；
- audit records；

必须设计清晰事务顺序。

推荐：

```text
1. 开启新的 AsyncSession
2. 执行 fenced parent UPDATE
3. rowcount != 1 → rollback
4. 写入或 upsert child records
5. 更新 pipeline terminal state
6. commit
7. queue complete
```

不得：

- 在外部 OCR 或 AI 请求期间持有事务；
- 在渲染 PDF 期间持有事务；
- parent fencing 失败后仍写 child table；
- 业务 commit 成功后因为 queue complete 短暂失败而重复写业务结果。

对于“业务 commit 成功但 Redis complete 失败”的情况：

必须保证再次执行任务时能够识别业务已经以当前 generation 完成，避免重复插入。

可采用：

- 唯一约束；
- generation terminal marker；
- idempotent upsert；
- outbox/finalization record；
- 等价的可恢复设计。

------

# 四、增加真实 PostgreSQL stale Worker 测试

必须使用真实 PostgreSQL，不接受纯 mock。

测试流程：

## Worker A

```text
claim task
generation = 1
建立业务 fence
开始执行
暂停在最终写入前
```

## Lease 过期

```text
停止 A heartbeat
等待 lease expire
reaper 恢复任务
```

## Worker B

```text
claim same task
generation = 2
建立新 fence
写入结果 B
commit
complete
```

## Worker A 恢复

A 尝试：

- 写 pipeline 状态；
- 写 question；
- 写 import result；
- 写 formula 或 batch 状态；
- 调用 complete。

验收：

- A 的 fenced UPDATE rowcount = 0；
- A 的事务 rollback；
- A 不得写入任何 child record；
- A 不得覆盖 B；
- A 不得 fail 或 complete generation 2；
- 最终数据库只包含 B 的结果；
- Redis task 为正确终态。

测试必须验证实际数据库内容，不能只断言抛出了异常。

------

# 五、真实 Redis 队列集成测试

使用真实 Redis，不能全部 skip。

至少覆盖：

## 1. Empty 与 unavailable

空队列：

```text
dequeue_v2() → None 或明确 EMPTY result
```

Redis 停止：

```text
dequeue_v2() → TaskQueueUnavailableError
```

两者不可混淆。

## 2. 双 Worker claim

两个 Worker 同时 claim 同一任务：

```text
只有一个成功
```

验证：

- owner；
- generation；
- processing ZSET；
- Hash status。

## 3. 并发幂等 enqueue

100 个并发请求使用相同 idempotency key：

```text
只创建一个 task
只出现一个 ready member
```

## 4. heartbeat

任务执行时间超过初始 lease，但正常 heartbeat：

```text
reaper 不得回收
generation 不得变化
```

## 5. kill -9

真实启动 Worker 子进程：

```text
claim 后 kill -9
```

等待 lease 到期并运行 reaper。

验证：

- 任务只恢复一次；
- 不同时存在于 ready 和 processing；
- 新 Worker 可以 claim；
- generation 增加；
- 最终只产生一个有效业务结果。

## 6. complete 后 reaper

完成任务后多次执行 reaper：

```text
任务永远不重新进入 ready/retry
```

## 7. concurrent reaper

两个 reaper 同时扫描同一个过期任务：

```text
只有一次恢复
```

## 8. retry/dead

验证：

- retry_count；
- retry backoff；
- retry ZSET score；
- 最大次数；
- dead-letter；
- dead TTL；
- dead 最大长度。

## 9. Redis outage/recovery

运行中关闭 Redis，再恢复。

验证：

- Dispatcher 增加 failure metric；
- 执行指数退避；
- 达阈值后停止 claim；
- readiness 反映 queue unavailable；
- 不使用 memory queue；
- Redis 恢复后继续消费；
- 原任务状态不丢失。

------

# 六、验证 Redis 熔断逻辑不会丢任务

当前 Dispatcher 报告：

```text
10-failure circuit breaker
```

审计其具体行为。

必须明确：

熔断后：

- 是否只是暂停 claim；
- 是否退出进程；
- 是否设置 not-ready；
- 如何恢复；
- 是否自动 half-open；
- 是否需要重启；
- 已 claim 任务的 heartbeat 是否继续。

正确行为应为：

```text
停止领取新任务
保留已运行任务 heartbeat
Redis 恢复后有限探测
探测成功恢复 claim
```

如果 Redis 无法 heartbeat：

必须明确当前任务如何处理。

不能假装 heartbeat 成功。

必须避免：

```text
Redis 故障
→ heartbeat 丢失
→ Worker 继续执行很久
→ Redis 恢复后任务已被其他 Worker claim
→ 两个 Worker 同时写结果
```

最终仍需依靠数据库 fencing 阻止旧 Worker 写入。

------

# 七、Staging 生命周期真实集成测试

验证共享 async Redis pool 已真正复用。

## 连接复用

执行大量：

```text
async_incr_refcount
async_decr_refcount
lease acquire
lease renew
lease release
```

确认：

- 使用同一个 Redis pool；
- 不为每次操作建立新 client；
- connection 数有上限；
- shutdown 能关闭 pool。

## 并发 refcount

多个任务同时引用相同 object：

```text
refcount 不丢失
refcount 不为负数
```

## Work copy

处理器可以删除 work copy。

但：

```text
immutable staging object 必须仍存在
```

## 终态清理

验证：

- complete；
- failed；
- dead；
- cancelled；
- review required；

各状态对应的 lease/refcount/retention 行为。

## Worker crash

Worker 获取对象后 kill -9。

验证：

- staging object 不会立即被删除；
- lease 过期后可清理；
- 新 Worker 仍可读取原 object。

------

# 八、完整 SIGTERM 验证

真实启动 Worker。

构造一个可控长任务。

发送：

```bash
kill -TERM <worker_pid>
```

验证顺序：

```text
draining=true
停止 claim
当前任务 heartbeat 继续
等待当前任务
完成则 complete
超时则安全 release/requeue
关闭 Dispatcher
关闭 reaper
关闭 Redis
关闭 DB engine
进程退出
```

必须验证：

- SIGTERM 后未领取新任务；
- 没有 un-awaited coroutine；
- 没有 Task was destroyed；
- 没有永久 processing zombie；
- release 操作校验 owner+generation；
- 新 Worker 可以继续处理被释放任务。

------

# 九、把 integration tests 从 skip 变成真实执行

建立或修复：

```text
docker-compose.test.yml
```

至少包括：

```text
postgres
redis
```

可以选择：

- Docker Compose；
- Testcontainers。

提供统一命令：

```bash
docker compose -f docker-compose.test.yml up -d
pytest -q -m integration
docker compose -f docker-compose.test.yml down -v
```

测试启动前自动：

- 等待 PostgreSQL ready；
- 等待 Redis ready；
- 执行 Alembic upgrade head；
- 创建独立测试 database/namespace。

测试结束清理：

- Redis test keys；
- PostgreSQL rows/schema；
- staging test objects；
- 子进程。

不得以开发机没有服务为理由让全部 integration skip。

------

# 十、修复完整测试套件中的 PaddleOCR import 问题

虽然本轮内存正常，但仍需验证完整非本地 OCR 测试不会隐式加载 Paddle。

全局搜索 import chain。

目标：

```text
普通 tests
cloud tests
queue tests
database tests
API tests
```

都不得加载 PaddleOCR。

本地 OCR adapter 必须 lazy import。

仅以下条件允许导入：

```text
DEPLOYMENT_PROFILE=local_import
OCR_EXECUTION_BACKEND=local_process
明确运行 local_ocr marker
```

设置 pytest marker：

```ini
local_ocr
integration
cloud_ocr_isolation
load
```

运行：

```bash
pytest -q -m "not local_ocr and not load"
```

应在未安装 PaddleOCR 的环境中通过。

Cloud CI 不安装 PaddleOCR。

------

# 十一、继续执行 Phase 5 运维能力，但避免过度工程化

当前属于小用户量测试阶段。

只实现最实用的运维能力。

至少提供：

## 1. Doctor

```bash
python -m app.cli.doctor
```

检查：

- APP_ENV；
- PROCESS_ROLE；
- deployment profile；
- PostgreSQL；
- Alembic current=head；
- Redis；
- queue namespace；
- staging；
- OCR 配置；
- cloud OCR isolation 配置；
- storage/scratch 可写；
- DB connection budget。

失败返回非 0。

## 2. Queue status

```bash
python -m app.cli.task_queue status
```

输出：

- ready；
- processing；
- retry；
- dead；
- corrupt；
- oldest ready age；
- oldest processing age。

## 3. Task inspect

```bash
python -m app.cli.task_queue inspect TASK_ID
```

输出安全摘要。

不得输出 token 和完整 payload 敏感信息。

## 4. Staging status

```bash
python -m app.cli.staging status
```

输出：

- object count；
- active lease；
- orphan candidate；
- disk usage。

## 5. Consistency check

```bash
python -m app.cli.consistency check
```

只读检查：

- processing Hash/ZSET 不一致；
- terminal 仍在 processing；
- retry 状态不一致；
- task object_id 不存在；
- pipeline/task generation 不一致；
- negative refcount。

## 6. Smoke test

```bash
python -m app.cli.smoke_test
```

测试：

- live；
- ready；
- PostgreSQL；
- Redis；
- staging；
- enqueue；
- claim；
- complete。

使用测试 namespace，完成后清理。

------

# 十二、管理端最小任务操作

测试阶段至少需要：

## 查询任务

支持：

- task_id；
- pipeline_id；
- status；
- task type；
- created time。

## Retry

只允许：

- failed；
- dead；
- review required；
- 明确可恢复状态。

必须走正式 queue service。

不得直接修改 Redis Hash。

## Cancel

pending/retry：

原子取消。

processing：

设置 cancellation requested。

Worker 在安全 checkpoint 处理。

## 查看错误

返回：

```text
error_code
error_stage
retryable
attempt
last_error_at
```

所有操作写 audit log。

不需要建设复杂任务平台。

------

# 十三、统一错误码

至少保证以下错误可区分：

```text
QUEUE_EMPTY
QUEUE_UNAVAILABLE
QUEUE_FULL
TASK_NOT_FOUND
TASK_FENCING_REJECTED
TASK_LEASE_LOST
TASK_CANCELLED
TASK_RETRY_EXHAUSTED
STAGING_OBJECT_MISSING
STAGING_UNAVAILABLE
RESOURCE_MEMORY_LOW
RESOURCE_DISK_LOW
RESOURCE_QUEUE_FULL
RESOURCE_DB_POOL_BUSY
OCR_TIMEOUT
OCR_RATE_LIMIT
OCR_PROVIDER_ERROR
AI_TIMEOUT
AI_RATE_LIMIT
DB_UNAVAILABLE
DB_CONFLICT
PIPELINE_TIMEOUT
REVIEW_REQUIRED
```

内部 queue empty 一般不作为 HTTP error。

API 返回统一格式：

```json
{
  "error": {
    "code": "QUEUE_UNAVAILABLE",
    "message": "任务队列暂时不可用",
    "retryable": true,
    "request_id": "..."
  }
}
```

提交长任务成功时返回：

```json
{
  "task_id": "...",
  "pipeline_id": "...",
  "status": "queued"
}
```

------

# 十四、可观测性必须验证实际增加，而非只声明变量

验证以下指标在真实测试中发生变化：

```text
task_queue_redis_failure_total
task_fencing_rejected_total
task_claim_total
task_complete_total
task_retry_total
task_dead_total
task_reaper_recovered_total
task_heartbeat_failure_total
staging_refcount_error_total
staging_orphan_cleaned_total
worker_draining
worker_active_tasks
```

不要使用高基数 label：

- task_id；
- pipeline_id；
- user_id；
- owner_token；
- object_id。

通过日志字段关联具体任务，而不是 Prometheus label。

------

# 十五、检查当前新增实现中的常见问题

重点审计：

## `conditional_update_with_fencing()`

检查：

- 是否接受任意字段名导致 SQL 注入风险；
- 是否通过 SQLAlchemy column expression 构建；
- 是否正确处理 rowcount；
- PostgreSQL driver 是否可靠返回 rowcount；
- 是否 flush/commit 边界清晰；
- 是否错误捕获后继续；
- 是否允许更新 ownership 字段本身；
- 是否可以无意覆盖 generation。

## `FencingRejectedError`

检查：

- 是否被过宽 `except Exception` 捕获并转成普通 retry；
- stale Worker 是否会调用 fail_v2；
- stale Worker 是否会修改 pipeline failed；
- 是否会造成错误告警风暴。

## `TaskQueueUnavailableError`

检查：

- 所有消费者都已适配；
- 所有生产者 enqueue 都已适配；
- API 层返回 503；
- readiness 已反映；
- scheduler 是否仍把异常当空队列；
- management CLI 是否正确显示 unavailable。

## staging shared client

检查：

- `_client` 是否一定存在；
- client 未初始化时行为；
- close 顺序；
- fork/Gunicorn 后连接池是否在子进程重新建立；
- 不得在 master 进程创建后跨 fork 复用 socket。

------

# 十六、进程角色直接启用

测试阶段直接使用正式进程角色。

## Web

```bash
PROCESS_ROLE=web \
gunicorn app.web_main:app \
  -k uvicorn.workers.UvicornWorker \
  --workers 2
```

实际 workers 以资源预算为准。

## Worker

```bash
PROCESS_ROLE=worker \
python -m app.worker_main
```

默认重型并发：

```text
1
```

## Scheduler

```bash
PROCESS_ROLE=scheduler \
python -m app.scheduler_main
```

Worker 和 scheduler 不通过 Gunicorn 暴露公网 HTTP。

如果项目实际入口不同，以现有代码为准，并在最终报告给出准确命令。

------

# 十七、直接发布，不做灰度

本阶段发布流程保持简单：

```bash
git pull
alembic upgrade head
python -m app.cli.doctor
docker compose up -d --build
```

或项目当前部署命令。

然后：

```bash
python -m app.cli.smoke_test
python -m app.cli.task_queue status
python -m app.cli.staging status
python -m app.cli.consistency check
```

全部通过后：

直接允许测试用户使用。

不需要流量比例和 canary。

------

# 十八、直接使用前的最小回滚准备

虽然不做灰度，仍需：

- 记录当前 git commit；
- 创建可识别 tag；
- 备份生产测试数据库；
- 记录 Alembic revision；
- 记录 Redis queue namespace；
- 确认 staging format 没有破坏性变化。

如果 migration 不支持安全 downgrade：

明确说明：

```text
代码可以回滚
数据库 migration 不建议 downgrade
需要使用备份恢复
```

不需要建立双环境长期运行。

------

# 十九、必须执行的命令

至少执行：

```bash
python -m compileall app tests
ruff check app tests
pytest -q -m "not integration and not local_ocr and not load"
pytest -q -m integration
pytest -q -m cloud_ocr_isolation
pytest -q -m "not local_ocr and not load"
alembic heads
alembic current
alembic upgrade head
```

如果 mypy baseline 已存在：

```bash
mypy app
```

必须实际运行：

```bash
python -m app.cli.doctor
python -m app.cli.smoke_test
python -m app.cli.task_queue status
python -m app.cli.staging status
python -m app.cli.consistency check
```

------

# 二十、故障注入测试

至少执行以下真实故障场景：

## Redis

- Redis 停止；
- Redis 恢复；
- claim 期间断开；
- heartbeat 期间断开；
- complete 期间断开。

## PostgreSQL

- 在最终 fenced UPDATE 前让 stale Worker 暂停；
- 由新 Worker 完成；
- 恢复旧 Worker；
- 验证旧 Worker 被拒绝。

## Worker

- kill -9；
- SIGTERM；
- 当前任务超出 graceful timeout。

## OCR

- timeout；
- 429；
- 503；
- circuit open。

## Staging

- object 暂时不可读；
- work copy 被删除；
- Worker crash 后 lease 过期。

输出每个场景的真实结果。

------

# 二十一、Phase 6 验收标准

只有全部满足，才能标记：

```text
READY FOR TEST USAGE
```

必须满足：

1. `conditional_update_with_fencing()` 实际用于全部关键业务最终写入；
2. stale Worker 无法写 parent 或 child data；
3. stale Worker 不得 complete/fail 新 generation；
4. Redis empty 与 unavailable 已彻底分离；
5. enqueue Redis failure 返回 503；
6. Redis outage/recovery 集成测试通过；
7. 双 Worker claim 测试通过；
8. heartbeat 超过初始 lease 测试通过；
9. kill -9 recovery 通过；
10. concurrent reaper 只恢复一次；
11. complete 后永不重投；
12. staging refcount/lease 测试通过；
13. staging client 使用共享 pool；
14. SIGTERM 测试通过；
15. integration tests 不再全部 skip；
16. Cloud OCR isolation 继续通过；
17. 非 local OCR 测试不隐式加载 Paddle；
18. Alembic single head 且 current=head；
19. doctor 通过；
20. smoke test 通过；
21. consistency check 无严重错误；
22. 没有已知数据破坏、重复写入或 durable state blocker。

非阻断问题，例如：

- 管理页面样式；
- 少量低频慢查询；
- 日志展示不够友好；
- 非核心功能性能一般；

可以在测试使用期间继续修复。

------

# 二十二、最终报告格式

最终严格按照以下格式输出。

## 1. Phase 6 结论

```text
READY FOR TEST USAGE: YES / NO
```

如果 NO，列出 blocker。

## 2. Fencing 接入矩阵

```text
handler
model/table
fenced initialization
fenced final update
child write protected
test
status
```

状态只能：

```text
PASS
FAIL
NOT VERIFIED
```

## 3. Redis 语义验证

列出：

- empty；
- unavailable；
- recovery；
- circuit breaker；
- readiness。

## 4. 修改文件

```text
path
change
reason
```

## 5. 新增测试

列出测试文件和场景。

## 6. 真实测试结果

```text
command
passed
failed
skipped
duration
```

不得只写“全部通过”。

## 7. 故障注入结果

分别报告：

- Redis；
- PostgreSQL stale worker；
- kill -9；
- SIGTERM；
- staging；
- OCR。

## 8. CLI 实测

```text
doctor
smoke_test
queue status
staging status
consistency check
```

状态和关键输出。

## 9. 当前运行状态

```text
queue ready
queue processing
queue retry
queue dead
oldest task age
staging objects
staging disk usage
DB revision
deployment profile
OCR backend
worker concurrency
```

## 10. 直接部署命令

给出项目实际可执行命令。

## 11. 回滚信息

列出：

- commit/tag；
- Alembic revision；
- DB backup；
- Redis compatibility；
- staging compatibility。

## 12. 可边用边修的问题

只列非阻断问题。

## 13. 阻断问题

如果没有：

```text
No known test-usage blockers.
```

------

# 二十三、禁止事项

禁止：

- 只在 Worker complete 前检查 fencing；
- stale Worker 写完业务数据后才抛错；
- 用 SELECT+Python 判断代替最终条件 UPDATE；
- 新增 helper 但业务 handler 不调用；
- mock 测试代替全部 Redis/PostgreSQL 集成测试；
- integration tests 全 skip 后宣布通过；
- Redis exception 返回 None；
- Redis 故障 fallback 到 memory queue；
- staging fallback 到 process-local refcount；
- stale Worker 调用 fail_v2；
- kill -9 后人工改 Redis 才能恢复；
- 通过增加 lease 时间掩盖 heartbeat 问题；
- cloud profile 导入 PaddleOCR；
- 为了完整测试安装 PaddleOCR 到 cloud CI；
- 只修改测试期望值让测试变绿；
- 声称 READY，但没有 doctor 和 smoke test 实测；
- 在没有真实数据库内容断言的情况下声称 fencing 成功。

本阶段完成后，不再继续进行大规模架构重构。

满足验收条件后，直接投入小规模测试用户使用。

使用过程中通过：

```text
task_id
pipeline_id
request_id
error_code
```

定位问题，修复后直接重新部署。