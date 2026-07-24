你是一名资深 Python/FastAPI、SQLAlchemy Async、PostgreSQL、Redis、分布式任务队列和 OCR 架构工程师。请在当前后端仓库中直接完成审计、修复、迁移、自动化测试和部署说明。不要只输出建议、TODO、伪代码或示例补丁。

# 一、任务目标

当前仓库是一个 FastAPI + SQLAlchemy Async + PostgreSQL + Redis 的刷题和题库导入系统。生产资源约为 2 核 CPU、1.8GB 内存，FastAPI、PostgreSQL、Redis、Nginx 和管理端可能运行在同一台服务器。

本次静态审计已经确认：当前代码只完成了部分结构性改造，尚未满足 `next_task.md` 的生产验收标准，不可直接上线。

你必须重新验证并修复每一个问题。不得因为类名、注释或文件名包含 durable、bounded、cloud safe、resource guard 等字样就认为实现已经正确。

必须优先保证：

1. 不阻塞 FastAPI 事件循环。
2. 不发生重复导入、重复发布、重复 OCR 或重复 AI 调用。
3. 进程重启、Worker 崩溃后任务可恢复。
4. processing、retry、dead、Redis key、临时文件和日志不会无限增长。
5. 资源不足时在入队前快速拒绝，不允许无限排队。
6. cloud_api/production 永远不导入、初始化、检查或回退本地 PaddleOCR。

# 二、先输出审计矩阵

开始修改前，输出一份审计矩阵，至少包含：

- 文档要求。
- 当前状态：已实现、部分实现、未实现、实现错误。
- 代码路径和行号。
- 可复现方式。
- 生产风险。
- 修复方案。
- 对应测试。

然后直接修改代码，不要停留在审计报告阶段。

# 三、必须首先修复的 P0

## P0-1：修复 DurableTaskQueue 状态机

重点检查：

- `app/services/task_queue_service.py`
- `app/services/task_queue_worker.py`
- `app/services/ai_prewarm_worker.py`

已确认缺陷：

1. `DurableTaskQueue.heartbeat()` 在接收 `Task` 时没有自动使用 `task.task_type`，而是更新 `_p_key(task_type or "")`。
2. 这会写入错误的 `taskq:processing:` ZSET，正确 processing lease 没有延长，错误 ZSET 会持续增长。
3. retry claim 在确认 task hash 和 payload 存在前就进入 processing，payload 缺失可能留下脏 processing/heartbeat。
4. reaper 没有可靠更新 generation、attempt、status 和 owner fencing。
5. owner 丢失后，旧 Worker 仍可能继续执行写数据库、发布或上传等副作用。
6. ready queue 没有原子容量控制。
7. 内存队列满时部分路径仍返回 task_id，调用方会误判成功。
8. SIGTERM 时仅设置 draining 后立即 cancel，没有等待当前任务和安全释放 lease。
9. 未知 task type 可能被当成成功完成。
10. AI prewarm 使用相同的错误 heartbeat，延迟和幂等语义也不完整。

修复要求：

- 使用 Redis Hash 保存 task payload/state。
- ready queue 只保存 task_id。
- processing 和 retry 使用 ZSET。
- 所有 enqueue、claim、heartbeat、complete、fail、retry、dead、reaper 操作必须通过原子 Lua 或 Redis Streams Consumer Group 完成。
- task state 至少包含：

```text
task_id
task_type
payload
status
retry_count
max_retries
owner_token
generation
lease_until
created_at
updated_at
last_error
```

- enqueue、幂等 key 和容量检查必须在同一个原子操作中完成。
- 队列达到上限时不能修改任何 Redis 状态，返回稳定的 429/503 错误和 Retry-After。
- claim 必须先确认 task hash 和 payload 存在，再进入 processing。
- 每次 claim 生成新的 owner_token 和 generation。
- heartbeat 必须原子校验 task_id、task_type、owner_token 和 generation，并更新正确 processing ZSET 的 score。
- complete、fail 和 reaper 必须使用同样的 fencing 条件。
- 所有终态必须清理 processing、heartbeat 和 owner 状态。
- reaper 只能恢复真实过期且未续租的任务，并且只能恢复一次。
- 旧 owner 在 lease 丢失后不得继续执行副作用步骤。
- 增加显式的 `release_or_requeue_on_shutdown()`。
- Worker 收到 SIGTERM 后执行：

```text
停止 claim 新任务
继续为当前任务 heartbeat
等待当前任务在 grace timeout 内完成
超时则原子释放或重新入队
关闭 Redis、DB、httpx 和 executor
```

- dead-letter 必须有容量、TTL、查询、重试、删除接口和指标。
- production/cloud_api Redis 不可用时拒绝长任务。
- 只有 local_import 且显式配置时才允许使用有界内存队列。

必须新增测试：

1. claim 后 processing 正确。
2. heartbeat 延长对应 task_type 的 lease。
3. 禁止生成空 task_type processing ZSET。
4. complete 后 processing 为空。
5. heartbeat 正常时，运行超过初始 lease 不会重复执行。
6. Worker 崩溃后只恢复一次。
7. 两个 Worker 并发 claim 只有一个成功。
8. 重复 enqueue 同一个 task_id 只产生一个任务。
9. retry/dead 状态正确。
10. Redis 重连后状态保留。
11. complete 后 reaper 永不重新入队。
12. processing/retry/dead 不随已完成任务无限增长。
13. owner_lost 后旧 Worker 不再执行写库或发布操作。
14. 队列满时 Redis 状态完全不变。

## P0-2：彻底隔离云端 OCR

重点检查：

- `app/services/ocr_service.py`
- `app/services/ocr_executor_service.py`
- `app/features/ocr_gateway.py`
- `app/features/ocr_adapter.py`
- `app/services/ocr_worker_client.py`
- `app/services/ocr_paddlex_http_client.py`
- `app/services/import_pipeline_service.py`
- `app/features/exercise_region_detector.py`
- `app/core/ocr_process_pool.py`
- `app/main.py`

已确认缺陷：

1. `ocr_service._is_cloud_api()` 将 `DeploymentProfile` 枚举与字符串 `"cloud_api"` 比较，结果恒为 False。
2. `import_pipeline_service.py` 也使用相同的错误比较。
3. Gateway 失败后，`ocr_pages`、`ocr_pages_with_boxes` 和 `ocr_raw_text` 会进入 legacy executor。
4. legacy executor 会导入 `app.core.ocr_process_pool`。
5. `ocr_executor_service.py` 使用 `run_in_executor(None, ...)`。
6. `OCRGateway` 构造函数允许不显式传 profile。
7. Gateway 注册 backend 时过早导入本地 adapter。
8. worker client factory 没有独立的 cloud fail-closed 防线。
9. shutdown 可能为了关闭 executor 而导入本地 OCR pool。
10. `main.py` 使用 `sys.modules` 却没有导入 `sys`。
11. 外部 OCR client 没有完整重试、退避、熔断、跨进程并发和大小限制。
12. `OCR_REMOTE_TOKEN` 没有明确安全地放入请求头。
13. OCR 请求构造存在同步文件读取。

修复要求：

- 所有模块只从 `app.core.deployment_profile` 导入统一的：

```python
detect_deployment_profile()
DeploymentProfile
```

- 所有判断使用枚举，不允许与字符串直接比较。
- `OCRGateway` 必须强制：

```python
OCRGateway(profile: DeploymentProfile, ...)
```

不得自动默认为 local_import。

- cloud_api/production 的实际 import graph 中不得触碰：

```text
paddle
paddleocr
PaddleOCRLocalAdapter
ocr_process_pool
ocr_local_worker_client
ocr_worker/executor.py
```

- 删除云端的所有 legacy local fallback。
- 删除云端 `reset_ocr_engine()` 路径。
- 云端不得调用 `find_spec("paddle")` 或 `find_spec("paddleocr")`。
- Gateway、client factory 和 executor 三层都要检查 profile 并 fail closed。
- 检测到 local backend 时记录结构化安全错误并停止该 OCR 路由。
- 外部 OCR 失败后只能：

```text
有限次数重试远端
使用已有 PDF 文本层
使用轻量文本规则
使用 AI 文本纠错
进入人工审核
返回明确可重试错误
```

不得进入本地 OCR。

外部 OCR client 必须：

- 复用共享 `httpx.AsyncClient`。
- 设置 connect、read、write、pool timeout。
- 设置连接数上限。
- 使用有界的进程内并发控制。
- 使用 Redis 实现跨进程并发控制。
- 获取并发许可时有超时或立即拒绝，不能无限等待。
- 仅重试连接错误、429、502、503、504。
- 使用有限次数指数退避和随机抖动。
- 业务 4xx 不重试。
- 实现 circuit breaker。
- 限制原始请求大小、base64 后大小和响应流大小。
- token 只能放入安全请求头。
- token 不得出现在 URL、日志、异常、response preview 或监控标签中。
- shutdown 只关闭真实创建过的远端 client。

必须新增 cloud isolation 测试：

- 设置 `APP_ENV=production` 或 `DEPLOYMENT_PROFILE=cloud_api`。
- monkeypatch `builtins.__import__`，导入任何 `paddle`、`paddleocr` 或本地 OCR 模块立即失败。
- monkeypatch `importlib.util.find_spec`，查询 paddle/paddleocr 立即失败。
- 断言 `sys.modules` 中不存在 paddle 和 paddleocr。
- 断言不创建 OCR 子进程或进程池。
- 断言不实例化 local adapter。
- 外部 OCR 失败时进入 review 或明确失败。
- 不安装 OCR requirements 时，云端仍能启动并调用外部 OCR。
- shutdown 不导入任何 local OCR 模块。

## P0-3：修复生产配置 fail-fast

重点检查：

- `app/services/production_config_validator.py`
- `app/main.py`
- `app/core/config.py`
- `app/core/ocr_runtime_config.py`

已确认缺陷：

1. `_check_ocr_no_local_deps()` 在 cloud 中主动执行 `find_spec`，违反硬约束。
2. 使用 `except Exception: pass` 隐藏配置检查错误。
3. profile 解析失败时 `_is_restricted_environment()` 可能返回 False，从而跳过生产校验。
4. `main.py` 将部分生产校验异常记录为非致命 warning。
5. paddlex_http URL 为空时，URL/token 组合可能漏检。
6. queue capacity 校验读取了错误位置的 `_DEAD_MAX`。
7. DB 连接预算没有覆盖真实实例数和 PostgreSQL 保留连接。
8. `main.py` 存在缺少 `sys`、早期使用未导入 `log_event` 等运行时问题。

修复要求：

- APP_ENV、profile 或配置解析失败时必须 fail closed。
- production/cloud_api 的任何同步或异步校验异常都必须抛 `SystemError`。
- 不允许在生产启动路径使用 `except Exception` 后继续启动。
- 云端不检查 Paddle 是否安装，只验证当前配置和 import graph 不会使用本地 OCR。
- 完整校验：

```text
APP_SECRET
PostgreSQL + asyncpg
Redis 连接
Alembic head
CORS
PROCESS_ROLE
OCR profile
OCR backend
OCR_USE_GPU=false
unsafe thread fallback=false
remote-to-local fallback=false
OCR URL
OCR token
经显式允许的内网 HTTP 例外
staging/static/persistent storage 可写
磁盘剩余空间
DB 连接预算
队列容量
角色配置一致性
```

- 为所有非法配置组合增加参数化启动测试。
- 非法组合必须导致 lifespan 启动失败。
- 修复所有 NameError、未定义符号和被异常吞掉的启动检查。

安全默认值至少调整为：

```text
cloud 单文件：5MB
cloud PDF 页数：30
同时处理文档：1
同时渲染页面：1
PDF page window：1
worker 并发：1
OCR GPU：false
```

## P0-4：真正拆分 web、worker 和 scheduler

重点检查 `app/main.py` 及部署命令。

当前 web role 仍启动 token cleanup 和 staging cleanup，违反角色隔离。

修复要求：

- `PROCESS_ROLE=web`：

```text
HTTP
鉴权
轻量数据库查询
上传到 staging
资源准入
可靠入队
```

不得执行 pipeline、OCR、AI、公式、定时清理或 reaper。

- `PROCESS_ROLE=worker`：

```text
导题
PDF
外部 OCR
AI 修复
公式任务
task heartbeat/retry/dead
```

默认并发 1。

- `PROCESS_ROLE=scheduler`：

```text
番茄钟
refresh token cleanup
audit cleanup
staging orphan cleanup
其他定时任务
```

- 为三个角色提供独立启动命令、Docker Compose/systemd/supervisor 示例和健康检查。
- 所有 `asyncio.create_task()` 保存引用并添加 done callback。
- 关键任务异常退出时，production 进程必须退出或进入 not-ready，不能静默停止。
- 每个组件有明确 `start()`、`stop()`、`drain()`。
- shutdown 顺序正确关闭共享 httpx、Redis、SQLAlchemy engine 和 executor。
- web role 不初始化重型 OCR client。
- worker role 初始化自己需要的 OCR Gateway 和共享远端 client。

## P0-5：重写 ResourceGuard 原子准入

重点检查：

- `app/core/resource_guard.py`
- `app/services/import_pipeline_service.py`
- 所有上传、resume、后台管理和内部导入入口

已确认缺陷：

1. Redis acquire Lua 超过容量后仍然 `INCR`。
2. `can_accept_work()` 和 `increment_pipeline_count()` 分离，存在竞态。
3. increment 忽略 acquire 返回值。
4. async 路径调用同步 Redis client。
5. Redis 失败时 production 也可能降级为进程内计数。
6. 校验期间抛异常可能泄漏 pipeline count。
7. module singleton 未按 deployment profile 配置。
8. event-loop lag、临时磁盘和 DB pool 等指标没有真实接入。

修复要求：

- 使用异步 Redis Lua 实现原子的：

```python
async with resource_guard.acquire_pipeline(...):
    ...
```

- 超限时不能修改计数。
- 使用 owner token + lease/ZSET 或等价结构支持续租和 crash cleanup。
- 不要使用单个整数加固定 TTL 表达活动任务。
- production Redis 失败时 fail closed。
- local_import 只有显式配置时允许本地有界 fallback。
- 任何异常或取消都必须在 context manager 中释放。
- admission 至少检查：

```text
RSS
系统可用内存
临时磁盘
当前 pipeline 数
OCR 并发
页面像素预算
远端 API 调用预算
队列长度
DB pool 使用率
event-loop lag
```

- 所有导入入口必须在入队前调用同一 guard。
- 资源不足返回稳定错误码、503/429 和 Retry-After。
- 登录、刷题和答题提交等轻量接口不能被长任务 admission 阻塞。

## P0-6：将 staging 生命周期绑定到 durable task

重点检查：

- `app/services/staging_storage.py`
- `app/services/task_queue_worker.py`
- `app/services/import_pipeline_service.py`
- `app/services/import_service.py`
- 所有上传入口

修复要求：

- 上传时直接分块流式写入 staging volume。
- 写入过程中计算 SHA-256、size 和 MIME/magic。
- 使用原子 rename 提交对象和 metadata。
- task payload 只保存 object_id。
- 不保存服务器路径、`UploadFile`、请求 Session、ORM 实例或内存闭包。
- enqueue、claim、heartbeat 应创建或续租 object lease。
- completed、failed、cancelled 和 dead 状态按 retention policy 释放 lease。
- cleanup 只能删除：

```text
无有效 lease
无 ready/processing/retry task 引用
超过保留期
```

- 正确使用 `ttl_sec`。
- 删除 object 时同时清理 metadata 和 lease。
- quota 必须并发安全，不能每次依靠 O(n) 目录扫描。
- production 使用持久 Docker volume，不允许 durable task 依赖 `/tmp`。
- 删除 resume payload 中的 `file_path`。
- 将旧的 `/tmp` + FastAPI BackgroundTasks 导入路径迁移到 durable queue。

## P0-7：PDF 和图片改为严格单页流式处理

重点检查：

- `app/services/pdf_renderer_service.py`
- `app/features/pipeline_orchestrator.py`
- `app/core/config.py`
- 图片压缩和上传路径

已确认缺陷：

1. `PdfRenderResult` 保存全部页面 bytes。
2. 可能同时保存全部内存和磁盘副本。
3. `PDF_RENDER_PAGE_WINDOW` 默认 0。
4. cloud 默认仍为 200MB、600 页和并发 5。
5. semaphore 没有限制 executor 等待队列。
6. chunk 路径仍会积累多页。
7. `ckpt` 存在先使用后导入的运行时错误。

修复要求：

- 生产主路径不得返回全量 `dict[int, bytes]`。
- 提供 `AsyncIterator[RenderedPage]`。
- cloud 同时最多持有一页：

```text
render
校验
文本层/OCR
解析
持久化
释放 bytes/Pixmap/PIL/BytesIO
删除临时页
下一页
```

- 跨阶段保存 object/artifact 引用，不保存全量 bytes。
- 专用 executor 有固定 worker 数和有界提交队列。
- 队列满立即返回 429/503。
- 全部 PyMuPDF、PIL、Excel、图片压缩、公式渲染、大文件哈希、同步 SDK 调用必须 offload。
- 不得在持有数据库事务时等待外部 API、上传或 CPU 操作。
- 增加以下校验：

```text
文件 magic
MIME
文件大小
页数
页面尺寸
单页像素
压缩比
decompression bomb
总 OCR 请求数
pipeline 总超时
临时磁盘预算
```

## P0-8：修复 scheduler 分布式锁

重点检查：

- `app/services/pomodoro_scheduler_service.py`
- `app/services/audit_cleanup_scheduler.py`
- `app/core/cache.py`
- token/staging cleanup

修复要求：

- 不得使用会在 Redis 故障时自动降级本地锁的 cache API。
- 建立 strict distributed lock。
- 锁包含唯一 owner token。
- 使用 Lua compare-and-expire 续租。
- 使用 Lua compare-and-delete 释放。
- owner 丢失后立即停止任务。
- 长任务必须在 TTL 到期前续租。
- audit cleanup 超过初始 TTL 时仍不能被第二实例重入。
- refresh-token 和 staging cleanup 只在 scheduler 角色运行。
- 每批有处理上限和数据库幂等条件。
- 增加 acquired、skipped、failed、duration、processed 指标。

# 四、继续完成 P1/P2

## 1. BackgroundTasks 和事件循环

- 删除重型 `/tmp` BackgroundTasks 主路径。
- 后台任务只接收序列化 ID/object_id。
- 每个后台任务自行建立、提交、回滚和关闭 AsyncSession。
- 不得传请求 Session、UploadFile、ORM 实例或 Request。
- 审计所有 `asyncio.create_task()`。
- 未跟踪的 SSE publish task 必须改为可靠管理、直接 await 或 outbox。
- async 路由中的 `compress_image()` 必须 offload。
- 审计 PIL、fitz、openpyxl、文件 I/O、同步 COS SDK、公式渲染和大型 JSON。

## 2. SSE

- 保留 Redis Pub/Sub/Streams 主路径。
- DB fallback 在无事件时指数退避，不能固定每两秒查询。
- 限制单用户并发连接和总连接数。
- 跨进程统计 active SSE，或至少提供可聚合 Prometheus 指标。
- heartbeat 不访问数据库。
- terminal 后立即关闭。
- Nginx/客户端断开后立即 cancel generator 和 subscription。
- 修复 subscription 异常重启抖动及 task 泄漏。

## 3. Readiness 和可观测性

- Redis readiness 使用 strict Redis PING，不能通过本地 cache fallback。
- `/health/live` 只表示进程存活。
- `/health/ready` 检查：

```text
PostgreSQL
strict Redis
Alembic head
当前角色依赖
worker queue
staging writable/free space
draining
OCR profile/backend/URL/token
cloud OCR 隔离
```

- 外部 OCR 短暂故障可以 degraded。
- 非法 OCR 配置必须 not-ready。
- 增加 Prometheus 指标：

```text
event-loop lag
HTTP p50/p95/p99
DB pool checked-out/wait
慢 SQL
task ready/processing/retry/dead
task duration
lease renewal failure
duplicate execution prevented
pipeline stage duration
OCR duration/429/timeout/circuit
AI duration/token/timeout
RSS/available memory/temp disk
active SSE
scheduler acquired/skipped
orphan files cleaned
```

## 4. 数据库性能

必须实际执行并保存修复前后的：

```sql
EXPLAIN (ANALYZE, BUFFERS)
```

覆盖：

- 今日复习。
- 错题列表和统计。
- practice 推荐。
- 知识状态。
- pipeline 状态。
- audit log cleanup。
- pomodoro 到期扫描。
- task 管理查询。
- question import review queue。

修复：

- 逐知识点 mastery 查询。
- practice 跨学科循环。
- AI prewarm 逐错题查询。
- review 逐题查询。
- 批量知识点 get-or-create。
- 导入逐题 flush/refresh。
- 公式逐条 get。
- 大表 `ORDER BY random()`。

使用 JOIN、IN、selectinload、PostgreSQL upsert、bulk insert/update 和必要唯一索引。

所有索引修改必须提供 Alembic upgrade 和 downgrade。

按实际 web、worker、scheduler 实例数重新计算连接预算，并为 PostgreSQL 管理和运维连接保留余量。

# 五、强制测试

当前仓库没有测试目录。必须新增真实、可执行的测试。

## 单元测试

1. profile 解析和非法配置 fail-fast。
2. cloud OCR 禁止本地 import/find_spec/subprocess/adapter/fallback。
3. 外部 OCR retry、backoff、jitter、4xx、circuit、大小限制和 token 脱敏。
4. queue 全状态机和 fencing。
5. heartbeat 正确 ZSET。
6. queue capacity 原子性。
7. SIGTERM graceful drain。
8. scheduler strict lock。
9. staging lease 和 cleanup。
10. PDF 单页窗口。
11. ResourceGuard 原子准入和异常释放。
12. SSE 关闭、取消、heartbeat 和退避。
13. 批量 SQL 查询次数断言。

## 集成测试：真实 Redis + PostgreSQL

1. 两个 Worker 同时 claim，仅一个成功。
2. Worker 执行中被 kill。
3. lease 过期后只恢复一次。
4. heartbeat 正常时不恢复。
5. complete 后永不重新入队。
6. Redis 断连和重连。
7. production 不降级内存队列。
8. PostgreSQL pool 耗尽。
9. OCR timeout、429、500 和 circuit。
10. SIGTERM。
11. staging volume 和容器重启后恢复。
12. 多 scheduler 实例只有一个执行。

## 压力测试

在 2 核、1.8GB 容器限制下测试：

- 普通 API 并发。
- 一个 PDF pipeline 同时处理普通请求。
- 多个导入请求快速提交。
- OCR 高延迟、429 和失败。
- SSE 长连接。
- 百万级练习记录核心查询。

记录：

```text
RSS
available memory
event-loop lag
HTTP p95/p99
queue length
processing/retry/dead
DB pool
temp disk
OCR concurrency
duplicate execution count
```

# 六、仓库清理

- 移除交付包中的：

```text
app/dev.db
app/data/dev.db
app/postgraduate.db
```

- 加入 `.gitignore`。
- 补充根级依赖、测试、lint、类型检查和运行配置。
- 不得提交 token、密码或生产数据库文件。

# 七、工作顺序

严格执行：

1. 输出审计矩阵。
2. 修复所有 P0。
3. 每修复一个 P0 模块立即增加并运行测试。
4. 处理事件循环、SSE、观测和数据库性能。
5. 给出新增或修改的环境变量与 `.env.example`。
6. 提供 Alembic migration 和 downgrade。
7. 提供旧配置兼容、数据迁移和回滚方案。
8. 提供 web、worker、scheduler 独立部署步骤。
9. 运行并粘贴真实命令结果。
10. 最后列出仍未解决的风险。

至少运行：

```bash
python -m compileall app
pytest -q
ruff check .
mypy app
```

根据仓库实际工具调整命令，但不得伪造未运行的结果。

# 八、禁止事项

禁止：

- 只写 TODO、建议、设计说明或伪代码。
- 使用 `except Exception: pass` 隐藏关键错误。
- 仅增加 timeout 掩盖死锁。
- 增加内存、线程或 Worker 数掩盖架构问题。
- production 降级进程内队列或本地分布式锁。
- cloud_api 检查、导入或执行本地 PaddleOCR。
- 外部 OCR 失败后回退本地 OCR。
- 把同步重任务放进 FastAPI 事件循环。
- durable task 依赖 `/tmp`、请求 Session、UploadFile、ORM 实例或进程内闭包。
- 在 owner lease 已失效时继续写库、上传或发布。
- 声称测试通过但没有测试文件和命令输出。

# 九、最终输出格式

最终按以下顺序输出：

1. 已确认问题和代码路径。
2. 修复后的架构及关键不变量。
3. 实际修改文件清单和关键 diff 摘要。
4. 新增或修改的环境变量。
5. Alembic migration。
6. 完整测试和真实执行结果。
7. 旧配置兼容与回滚方案。
8. web、worker、scheduler 生产部署步骤。
9. 压测方法、数据和验收结论。
10. 仍未解决的风险、影响和后续动作。
