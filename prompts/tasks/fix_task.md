你是一名资深 Python/FastAPI、SQLAlchemy Async、PostgreSQL、Redis、分布式任务队列和生产可靠性工程师。

请直接在当前项目根目录审计、修改并测试后端代码。不要只输出建议、设计说明、伪代码或 TODO。现有代码已经进行过一次架构更新，但静态审计确认仍存在严重的 P0 断链和伪完成问题。你必须先修复以下已确认问题，再继续审计其余需求。

# 一、执行原则

1. 以实际调用链为准，不以类名、注释、`v2` 命名或“已实现”声明作为完成证据。
2. 每项修复必须证明：
   - 生产者确实调用新实现；
   - 消费者确实消费同一套 Redis key；
   - 异常、重启、SIGTERM 和 Redis 断连路径仍成立；
   - 有自动化测试覆盖。
3. 先完成全部 P0，再处理 P1。
4. 不得通过扩大内存、线程池、Worker 数量或超时时间掩盖架构问题。
5. 修改实际代码、Alembic migration、部署配置和测试。
6. 对无法通过静态代码验证的数据库性能项，使用真实 PostgreSQL、Redis 和接近生产资源限制的容器验证。

# 二、必须立即修复的 P0

## P0-1：统一 DurableTaskQueue，修复 v1/v2 生产消费断链

当前已确认：

- `app/services/task_queue_worker.py` 中主要 enqueue helper 仍调用 `task_queue.enqueue()`。
- `app/services/ai_prewarm_worker.py` 也调用旧版 `enqueue()`。
- `app/main.py` 启动的是 `run_dispatcher_v2()` 和 `run_reaper_loop_v2()`。
- v2 Dispatcher 只调用 `dequeue_v2()`。
- 项目中没有业务生产者调用 `enqueue_v2()`。

这意味着主要任务被写入旧 key，而生产 Worker 轮询新 key。

必须：

1. 选定一套唯一的正式队列实现。
2. 建议将当前 v2 Lua/ZSET 实现提升为正式 API：
   - `enqueue`
   - `claim`
   - `heartbeat`
   - `complete`
   - `fail`
   - `reap`
3. 删除或明确禁用旧实现，不得长期保留两套可被误用的公开 API。
4. 如需要兼容已部署的旧队列，编写一次性迁移或双队列 drain 工具：
   - 只能迁移 task_id 和权威 payload；
   - 必须幂等；
   - 迁移完成后关闭旧队列写入；
   - 给出删除旧 Redis key 的安全步骤。
5. 所有导入、恢复、图片、Excel、公式、批量图片和 AI prewarm 必须使用同一正式队列。
6. `enqueue`、幂等 key、队列容量检查和任务 Hash 创建必须由同一 Lua 脚本原子完成。
7. 重复 task_id 或幂等键不得产生多个 ready/retry/processing 成员。
8. 生产 Redis 不可用时返回明确的 unavailable 状态，由 API 返回 503 和 `Retry-After`，不得降级成进程内队列。
9. 不要用 `None` 同时表示“队列为空”和“Redis 故障”。定义明确结果类型或异常：
   - EMPTY
   - CLAIMED
   - REDIS_UNAVAILABLE
   - FENCING_REJECTED
   - CORRUPT_TASK
10. Redis 连续异常达到阈值时：
    - Worker readiness 变为 not-ready；
    - 停止领取任务；
    - 记录结构化指标；
    - 可由进程管理器重启，不得把故障伪装成空队列。

## P0-2：修复 v2 Worker 无法运行和优雅关闭失效

在 `app/services/task_queue_worker.py` 中：

1. 正确导入 `settings`。
2. 删除生产环境 `/tmp/worker-scratch` 隐式默认值。
3. 生产 Worker 必须要求显式、持久或有配额的 `WORKER_SCRATCH_DIR`。
4. `graceful_shutdown_v2()` 中必须：
   - `await set_draining_v2()`；
   - `await stop_worker_v2()`。
5. 简化不必要的 async setter；如果函数不执行异步工作，也可以改成同步函数，但调用方式必须一致。
6. SIGTERM 顺序必须为：
   - 原子设置 draining；
   - Dispatcher 不再 claim；
   - heartbeat 在任务完成前继续运行；
   - 等待当前任务到 grace deadline；
   - 未完成任务执行明确的 abandon/release 操作；
   - owner+generation 校验通过后，从 processing 移除并放回 retry/ready；
   - 最后取消 Dispatcher、reaper 和相关守护任务。
7. 不得仅依赖 lease 自然过期来处理正常 SIGTERM。
8. 被取消的处理任务不得继续写业务数据库。
9. 所有 `asyncio.create_task()`：
   - 保存强引用；
   - 设置名称；
   - 捕获并记录异常；
   - shutdown 时 cancel 并 await；
   - 不得出现无人读取的后台 Task exception。
10. AI prewarm 不得拥有独立于重型任务之外的无限制并发。
    - 最好将 prewarm 纳入同一个 Dispatcher；
    - 或使用同一个全局重型任务并发控制器；
    - 2 核、1.8GB 环境默认总重型任务并发必须为 1。

## P0-3：补全任务状态和 reaper 原子语义

检查并修复 `app/services/task_queue_service.py` 的全部 Lua 脚本和 Python 封装。

必须保证：

1. claim 原子完成 ready/retry → processing。
2. claim 成功后任务 Hash 中同步写入：
   - status=processing
   - owner_token
   - generation
   - lease_expires_at
   - claimed_at
3. heartbeat 同时校验：
   - task_id 存在；
   - processing ZSET 中存在；
   - owner_token 一致；
   - generation 一致。
4. complete 原子：
   - 校验 owner+generation；
   - ZREM processing/retry；
   - 删除 heartbeat；
   - 写入有 TTL 的 terminal tombstone 或受控终态；
   - 清理幂等生命周期；
   - 保证 reaper 永远不能重新入队。
5. fail 原子更新 retry_count，并根据次数进入 retry 或 dead。
6. reaper 只能回收 lease 确实过期且仍为 processing 的 task_id。
7. reaper 回收时必须更新 Hash 为 pending/retrying，并清理旧 owner、旧 lease 等字段。
8. reaper 回收到 ready 前必须执行队列容量检查。
9. 同一过期任务被多个 reaper 并发扫描时只能恢复一次。
10. corrupt task 必须进入有界隔离区，不能无限重新扫描。
11. dead-letter 必须具备：
    - 最大长度；
    - TTL；
    - 分页查询接口；
    - retry/requeue 接口；
    - 删除接口；
    - 权限和审计日志。
12. ready、processing、retry、dead、corrupt 的长度都要有指标。

## P0-4：修复 fencing key 永久增长和业务数据库 fencing 未接入

当前 `taskq:v2:fencing:{task_id}` 每个任务一个 Hash，并明确不删除，会永久增长。

必须重新设计：

1. 不允许每个历史 task_id 永久保留一个 Redis key。
2. fencing generation 必须在任务有效生命周期中单调递增。
3. 终态后使用有界 tombstone TTL，TTL 必须覆盖：
   - 最大任务时间；
   - 最大 lease；
   - 最大 retry 窗口；
   - 最大允许迟到写入窗口。
4. 不得简单在任务仍可 retry 时提前删除 generation。
5. 增加定期清理和 key 数量指标。
6. 测试十万次短任务完成后 Redis key 数稳定在有界范围内。

项目已有：

- `app/services/db_fencing.py`
- `execution_generation`
- `current_task_id`
- `current_owner_token`
- `execution_status`
- `alembic/versions/v14_execution_generation_fencing.py`

但当前业务代码没有接入。

必须：

1. Worker claim 后，在开始业务执行前，用单条条件 UPDATE 初始化业务记录的 fence。
2. 不能只执行“SELECT 验证，再执行普通 UPDATE”，因为存在 TOCTOU。
3. 所有关键业务状态更新必须使用条件 UPDATE，例如条件包含：
   - `current_task_id = expected_task_id`
   - `current_owner_token = expected_owner_token`
   - `execution_generation = expected_generation`
4. 条件 UPDATE 影响行数为 0 时，立即抛出 fencing error，停止后续写入。
5. 对以下任务至少接入数据库 fencing：
   - import pipeline
   - resume/admin resume
   - batch image job
   - formula batch job
6. 在任务 complete/fail/dead/cancel 时同步更新业务 execution_status，但仍需使用 owner+generation 条件。
7. 外部 API 或 CPU 重任务前可检查 owner；外部调用完成后、写库前必须再次验证。
8. 增加“旧 Worker 在 lease 丢失后尝试提交结果，数据库拒绝”的集成测试。

## P0-5：修复 staging storage 的伪持久 refcount 和对象生命周期

当前已确认：

- `staging_storage.py` 导入不存在的 `app.core.redis_client`；
- ImportError 被吞掉后使用进程内 `_REFCOUNT_STORE`；
- refcount API 没有接入 enqueue/terminal 生命周期；
- Worker 获取对象时用空 owner/generation 建 lease；
- terminal 后没有可靠 release/retention；
- 批量图片路径可能删除 staging 原始 `.data` 对象。

必须：

1. 使用项目实际的异步 Redis 连接工厂，不得导入不存在的模块。
2. 生产环境 Redis refcount/lease 操作失败时必须 fail closed。
3. 进程内 refcount 仅允许显式本地开发模式。
4. 上传完成创建不可变对象：
   - object_id
   - SHA-256
   - size
   - MIME
   - created_at
5. enqueue 成功后增加任务引用；enqueue 失败时回滚引用。
6. 最好通过数据库对象引用表或 Redis Lua，把任务创建与引用登记设计成可恢复的事务式流程。
7. claim 时使用任务 owner_token 和 generation 创建或续租 staging lease。
8. heartbeat 同时续租任务 lease 和关联对象 lease。
9. complete/fail/dead/cancel 后：
   - 释放活跃 lease；
   - 根据终态设置明确保留期；
   - refcount 为 0 且超过保留期后才能删除。
10. Worker 只能把 work copy 传给会修改或删除文件的 pipeline。
11. 严禁把 staging 原始路径作为 `BatchImageSource.temp_path`。
12. 批量图片处理完成只能删除 work copy，不能删除 staging object。
13. 将同步 `retrieve_file`、`open`、`read`、`exists`、`unlink` 从 async 主路径移出事件循环。
14. 同时清理：
    - staging orphan；
    - `.tmp`；
    - worker scratch；
    - 过期 lease；
    - 无引用对象。
15. 增加磁盘用量、对象数、orphan 清理数和清理失败指标。

## P0-6：严格实现云端 OCR 隔离

修复以下路径：

- `app/features/ocr_gateway.py`
- `app/services/ocr_service.py`
- `app/services/ocr_executor_service.py`
- `app/core/ocr_process_pool.py`
- `app/main.py`
- 图片/PDF 导入入口

必须：

1. `OCRGateway._register_profile_backends()` 必须先判断 profile。
2. cloud profile 的分支中不得执行：
   - `from ... import PaddleOCRLocalAdapter`
   - 本地 adapter 模块导入；
   - `find_spec("paddleocr")`
   - `ocr_process_pool` 导入；
   - ProcessPool/子进程创建。
3. `main.py` cloud shutdown 不得导入并调用会导入 `ocr_process_pool` 的 `ocr_executor.shutdown()`。
4. `ocr_executor_service.shutdown()` 在 cloud profile 必须直接安全 no-op，且 no-op 之前不能导入本地 OCR 模块。
5. cloud Gateway 外部 OCR 失败后：
   - 有限重试；
   - 明确返回 retryable error；
   - 或写入 manual review；
   - 不得调用 legacy local OCR。
6. 删除 cloud 路径中“先调用 legacy，再由 `_reject_cloud_legacy` 抛错”的结构。cloud 分支必须根本不进入 legacy 函数。
7. `review` 必须成为明确的业务结果或 adapter，不能只是一个未注册 backend 名称，最终变成笼统的 `OCR_ALL_BACKENDS_FAILED`。
8. 清理 Gateway 的双重远程调用架构：
   - 要么统一使用注册的 remote adapter；
   - 要么统一使用 worker_client；
   - 不得一个路径使用空 token adapter，另一个路径绕过 registry。
9. 禁止 token 出现在 URL、日志、异常和 trace 数据中。
10. 增加启动测试：
    - monkeypatch `builtins.__import__`；
    - 任何包含 `paddle`、`paddleocr`、`ocr_process_pool` 的导入立即失败；
    - monkeypatch multiprocessing 和 ProcessPoolExecutor；
    - cloud 启动、图片导入、PDF OCR、外部 OCR 失败、shutdown 全流程均不得触发本地 OCR。

## P0-7：把跨进程 OCR 并发真正接入请求路径

项目已有 `ocr_distributed_concurrency.py`，但没有业务调用。

必须：

1. 每个外部 OCR 请求发送前获取 Redis semaphore。
2. semaphore 必须包含：
   - 原子 acquire；
   - token；
   - TTL；
   - owner；
   - 自动续租；
   - owner 校验 release；
   - orphan recovery。
3. 获取不到令牌时快速拒绝或有限等待，不得无限排队。
4. Redis 不可用时生产 cloud OCR 必须 fail closed。
5. 进程内 Semaphore 只能作为第二层保护，不能替代跨进程限制。
6. HTTP 429 的 `Retry-After` 当前已解析但没有传给 backoff，修复 `_RetryableError` 保存 `retry_after` 并实际采用。
7. 只重试连接错误、429、502、503、504。
8. 为整个 OCR 操作设置总 deadline，不能每次 retry 重新获得完整超时。
9. 增加并发、等待时间、拒绝、续租失败、429、circuit state 指标。

## P0-8：修复生产进程角色边界

当前 `PROCESS_ROLE` 控制 lifespan 中启动什么任务，但所有角色仍构造并挂载完整 FastAPI HTTP 应用。

必须：

1. 提供清晰的进程入口，例如：
   - `app.web_main`
   - `app.worker_main`
   - `app.scheduler_main`
     或独立 CLI 命令。
2. web：
   - 只提供 HTTP；
   - 只执行轻量查询、鉴权、上传流式落盘和 enqueue；
   - 不启动 pipeline、OCR Worker、AI prewarm、scheduler。
3. worker：
   - 不监听公网 HTTP；
   - 只运行 Dispatcher、reaper 和任务处理生命周期。
4. scheduler：
   - 不监听公网 HTTP；
   - 只运行有 leader lock 的周期任务。
5. 若继续共用 FastAPI app，必须通过部署命令证明 worker/scheduler 不被 Gunicorn 当作 HTTP Worker 启动。
6. Scheduler role 的关键启动失败不能全部作为 non-fatal 忽略。
7. resource orphan reconciler 只能由明确角色运行，或必须有严格 leader election。
8. token cleanup 在 Redis lock 创建或获取失败时不得无锁继续执行。
9. 所有 scheduler 未获得锁必须立即退出。
10. 锁必须续租，并覆盖任务实际时长。
11. 增加 scheduler acquired/skipped/failed/duration/processed 指标。

# 三、必须继续处理的 P1

## P1-1：PDF 和图片内存、线程池治理

修复 `pdf_renderer_service.py`：

1. 所有入口统一使用 settings 中的限制，不得保留 200MB、600 页硬编码作为生产有效上限。
2. cloud 默认：
   - 5MB；
   - 30 页；
   - page window=1；
   - render concurrency=1；
   - document concurrency=1。
3. `iter_pages()` 在打开 PDF 前必须执行 magic、大小和类型校验。
4. 所有上传、resume、后台管理和内部接口共用同一 validator。
5. 页面处理完成立即关闭 Pixmap、Document、Image、BytesIO 并删除 work copy。
6. 禁止将全部页面保存为 `dict[int, bytes]`。
7. 总页像素预算和总 OCR 调用预算必须贯穿整个 pipeline。
8. 使用有界 executor 和快速 admission control。
9. 队列已满时返回 429/503，不得在 asyncio 层无限等待 Semaphore。
10. 防止 decompression bomb、超大尺寸、异常压缩比和伪造 MIME。

## P1-2：删除旧 BackgroundTasks 和临时路径导入路径

重点处理 `app/services/import_service.py`：

1. 删除或下线 `BackgroundTasks.add_task()` 运行 PDF/数学流水线的路径。
2. 不得响应后继续依赖 `NamedTemporaryFile` 路径。
3. 不得在 async 函数中直接执行 fitz、PIL、文件大块读取和 CPU 密集处理。
4. 所有长任务必须：
   - 上传到 staging；
   - payload 只保存 object_id；
   - enqueue 到正式队列；
   - Worker 创建独立 AsyncSession。
5. 后台任务不得接收：
   - 请求作用域 Session；
   - UploadFile；
   - Request；
   - ORM 对象；
   - 进程内 pipeline store；
   - 任意服务器路径。
6. 对无法迁移的旧入口返回明确的 410 或受控禁用错误，不得留下可调用的不安全路径。

## P1-3：生产配置 fail-fast 和连接预算

修复 `production_config_validator.py` 和 `core/config.py`：

1. HTTPS 校验必须尊重明确的内网 HTTP 开关，但该开关默认关闭。
2. 校验 `EXPORT_DIR`、staging、scratch、static、persistent storage 的可写性和容量。
3. 按角色校验目录，不要要求纯 web 具备无关 Worker scratch 配置。
4. 校验 web/worker/scheduler 使用相同：
   - queue namespace/version；
   - deployment profile；
   - OCR backend；
   - staging root；
     -数据库和 Redis。
5. 重新计算 PostgreSQL 总连接预算：
   - Gunicorn Web Worker 数；
   - Worker 进程数；
   - Scheduler 数；
   - Alembic；
   - 运维保留；
   - PostgreSQL 自身保留。
6. 2 核、1.8GB 环境从更小配置开始：
   - web 每进程 pool_size 2、max_overflow 1；
   - worker pool_size 1～2、max_overflow 1；
   - scheduler pool_size 1、max_overflow 0～1。
7. 实际值通过压测确认，启动日志打印完整预算。
8. 非法组合必须抛出 `SystemError`，不能只打印日志。
9. 生产不得运行 `Base.metadata.create_all()`、ALTER TABLE 或 CREATE INDEX 修复函数。
10. 将 `core/database.py` 中生产所需 schema 修改迁入 Alembic。
11. 执行并证明：
    - `alembic heads` 只有一个 head；
    - `alembic upgrade head` 成功；
    - 当前 revision 等于 head。

## P1-4：ResourceGuard 接入所有入口

当前 guard 仅在部分 import pipeline 中使用。

必须覆盖：

- 单文件导入；
- 图片导入；
- PDF 导入；
- Excel 导入；
- batch image；
- resume；
- 管理端恢复；
- 公式批处理；
- AI prewarm；
- 内部接口。

admission 前至少检查：

- RSS；
- 系统可用内存；
- staging/scratch 临时磁盘；
- 活跃重型任务数；
- OCR 跨进程并发；
- 页面像素预算；
- 外部 API 调用预算；
- ready+retry 队列长度；
- DB pool checked-out/wait；
- event-loop lag。

资源不足时必须在 enqueue 前拒绝，并返回稳定错误码和 `Retry-After`。

## P1-5：SSE、数据库和查询性能

1. 审计 batch image SSE 的 Redis 推送与 DB fallback。
2. Redis subscriber 失败后不得恢复成高频每客户端 DB 查询。
3. 限制单用户 SSE 数量、最大连接时长和 idle 时间。
4. heartbeat 不访问数据库。
5. 客户端断开后立即取消 subscriber 和 generator。
6. 终态后立即关闭连接。
7. 审计所有 `ORDER BY random()` 和文档列出的 N+1。
8. 使用真实 PostgreSQL 对核心查询执行：
   - `EXPLAIN (ANALYZE, BUFFERS)`；
   - 记录执行计划；
   - 通过 Alembic 添加缺失索引。
9. 不得只修改 ORM 模型而不生成 migration。

# 四、必须新增的测试

创建完整 `tests/`，至少包含：

## 单元测试

- deployment profile 判定；
- cloud 禁止本地 OCR import；
- enqueue/claim key namespace 一致；
- claim 状态；
- heartbeat 延长 lease；
- complete 清理 processing；
- retry/dead；
- reaper；
- queue capacity；
- fencing generation；
- graceful shutdown；
- staging refcount；
- staging lease；
- work copy 不删除原对象；
- PDF page window；
- ResourceGuard；
- scheduler lock；
- Retry-After；
- production config 参数化失败组合。

## Redis/PostgreSQL 集成测试

使用真实 Redis 和 PostgreSQL，不得用纯 mock 替代：

1. 两个 Worker 并发 claim，同一 task_id 只有一个成功。
2. 同一幂等键并发 enqueue 只产生一个任务。
3. 任务超过初始 lease，但 heartbeat 正常，不被 reaper 回收。
4. kill -9 Worker 后任务只恢复一次。
5. complete 后 reaper 永远不能重新入队。
6. Redis 短暂断连和重连后状态不丢失。
7. stale Worker 的 DB 条件 UPDATE 被 generation fencing 拒绝。
8. SIGTERM 停止 claim，当前任务完成或被安全 requeue。
9. staging 对象在容器/进程重启后仍可读取。
10. 两个任务引用相同 SHA-256 对象时，一个任务完成不能删除另一个仍需要的对象。
11. dead-letter 长度和 TTL 有上限。
12. 大量完成任务后 processing、retry、fencing key 数不持续增长。

## Cloud OCR 隔离测试

在 `APP_ENV=production`、`DEPLOYMENT_PROFILE=cloud_api` 下：

- monkeypatch `__import__`；
- 禁止 `paddle`、`paddleocr`、`ocr_process_pool`；
- 禁止 ProcessPoolExecutor 和 multiprocessing OCR；
- 不安装 OCR requirements；
- 启动、图片导入、PDF OCR、外部失败、shutdown 全部通过；
- 外部失败只能 retry/review/明确失败；
- 不允许 legacy local fallback。

## 压力测试

在 2 CPU、约 1.8GB 内存限制下执行：

- 普通 API 并发；
- 一个 PDF 任务与普通 API 同时运行；
- 多个导入快速提交；
- OCR 延迟、429、500、超时；
- Redis 中断；
- SSE 长连接；
- 百万级练习记录核心查询；
- SIGTERM 与容器重启。

记录：

- RSS 峰值；
- OOM；
- event-loop lag；
- HTTP p50/p95/p99；
- DB pool wait；
- 队列长度；
- 重复执行次数；
- staging/scratch 增长；
- shutdown 后遗留任务数。

# 五、执行命令和证据

至少运行并给出真实输出摘要：

```bash
python -m compileall app
pytest -q
pytest -q -m integration
pytest -q -m cloud_ocr_isolation
ruff check app tests
mypy app
alembic heads
alembic current
alembic upgrade head
```

如果项目尚未配置 ruff、mypy 或集成测试容器，请补齐配置，不能简单写“未配置所以跳过”。

使用 Docker Compose 或 Testcontainers 提供测试 Redis/PostgreSQL。

# 六、输出顺序

最终回复必须严格按以下顺序：

1. 已确认问题、严重等级、代码路径和触发方式。
2. P0 修复清单。
3. 实际修改的文件及关键 diff 说明。
4. 新增或修改的环境变量。
5. Alembic migration 和 revision 链说明。
6. 新增测试列表。
7. 完整测试命令及真实结果。
8. 旧 v1 队列、旧 Redis key、旧临时文件和旧配置兼容方案。
9. 回滚方案。
10. web/worker/scheduler 生产部署命令。
11. 压测方法和结果。
12. 逐条需求验收矩阵：通过、失败或待验证。
13. 仍未解决的风险。

# 七、禁止事项

禁止：

- 只写 TODO；
- 只重命名方法而不统一 Redis key；
- 只增加日志而不修复状态；
- 只增加 timeout；
- 捕获异常后返回 None，把 Redis 故障当队列为空；
- `except Exception: pass`；
- 生产降级为内存队列或进程内 refcount；
- cloud 导入任何本地 OCR 模块；
- cloud 外部 OCR 失败后调用 legacy；
- 在 async 路径直接执行大文件 I/O、PIL、fitz 或同步 SDK；
- 把 staging 原始对象路径交给会 unlink 的处理器；
- 通过无限 Semaphore 等待代替队列容量控制；
- 声称 exactly-once，但不接入数据库条件 fencing；
- 声称 durable，但仍依赖 `/tmp`、进程内字典或请求对象；
- 声称测试通过但不提供执行命令和结果。

在全部 P0、自动化测试和云端 OCR 隔离测试完成前，不得宣布项目满足生产要求。
