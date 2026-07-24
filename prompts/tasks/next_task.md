你是一名资深 Python/FastAPI、PostgreSQL、Redis 和分布式任务系统工程师。请直接审计并修复当前项目后端代码，不要只输出建议或伪代码。

## 一、项目运行约束

项目是 FastAPI + SQLAlchemy Async + PostgreSQL + Redis 的刷题与题库管理系统，生产服务器约为：

- CPU：2 核
- 内存：约 1.8GB
- Gunicorn + Uvicorn Worker
- PostgreSQL、Redis、FastAPI、Nginx、管理端运行在同一台或同等级资源服务器上

必须优先保证：

1. 长期连续运行稳定。
2. 不阻塞 FastAPI 事件循环。
3. 不发生重复导入、重复发布、重复 OCR、重复 AI 调用。
4. 服务发布和进程重启后任务状态可恢复。
5. 队列、临时文件、Redis key、数据库日志不会无限增长。
6. 资源不足时快速拒绝新任务，不允许通过无限排队导致 OOM。

## 二、OCR 强制部署规则

这是不可违反的硬约束：

### 本地环境 `local_import`

本地开发机可以使用：

- PaddleOCR / PP-OCRv4
- 本地 CPU 或 GPU
- 本地 OCR 进程池
- 外部轻量 OCR API
- AI 纠错

### 云端环境 `cloud_api` / `production`

云端服务器只能使用轻量外部 OCR API。

云端严禁：

- 导入或初始化 `paddleocr`
- 导入或初始化 `paddle`
- 加载任何本地 OCR 模型
- 下载本地 OCR 模型
- 创建本地 OCR 子进程或进程池
- 使用本地 GPU OCR
- 外部 OCR 失败后回退到本地 OCR
- 为了通过依赖检查而要求安装 `requirements-ocr.txt`

云端外部 OCR 失败后只能：

1. 按有限次数和指数退避重试外部 OCR；
2. 使用轻量文本规则、已有 PDF 文本层或 AI 文本纠错；
3. 标记为需要人工审核；
4. 返回明确可重试错误。

绝不允许静默回退到本地 PaddleOCR。

请为此编写自动化测试，保证在 `APP_ENV=production` 或 `DEPLOYMENT_PROFILE=cloud_api` 时：

- `sys.modules` 中不存在 `paddleocr`、`paddle`；
- 不创建 OCR 子进程；
- 不实例化本地 OCR adapter；
- 图片导入和 PDF OCR 不检查本地 PaddleOCR 是否安装；
- 外部 OCR 失败时也不会进入 legacy local OCR；
- 启动配置不符合规则时应用直接启动失败。

## 三、必须优先修复的 P0 问题

### P0-1：重写 DurableTaskQueue 的状态模型

当前任务队列的 processing list、lease、heartbeat、ack 和 reaper 使用不同版本的 JSON，可能造成任务重复执行和 processing 列表无限增长。

不要在 Redis list 中保存会被修改的完整 Task JSON，并依赖 `LREM` 精确匹配。

优先采用以下任一可靠方案：

方案 A：Redis Streams + Consumer Group。

方案 B：使用原子 Lua 脚本实现：

- ready queue 只存 task_id；
- task payload/state 存 Hash；
- processing lease 存 Sorted Set，score 为 lease 到期时间；
- claim 原子完成 ready → processing；
- heartbeat 原子更新 lease；
- complete 原子删除 processing 和任务状态；
- fail 原子增加 retry_count，并进入 retry ZSET 或 dead-letter；
- reaper 只回收 lease 确实过期的 task_id；
- 所有终态必须清理 processing；
- 幂等 key 与入队必须在同一个原子操作中完成。

必须保证：

- 同一个 task_id 在任意时刻最多只有一个有效 owner；
- heartbeat 可以真正延长 lease；
- complete 后 reaper 永远不能重新入队；
- Worker 崩溃后任务可恢复；
- task 超过 lease 时间但 heartbeat 正常时不得被回收；
- dead-letter 有上限、保留时间和管理接口；
- processing、retry、dead 队列都有长度指标；
- Redis 不可用时生产环境直接拒绝长任务，不得降级为进程内队列；
- 本地开发模式才允许显式启用内存队列。

增加以下测试：

1. claim 后 processing 状态正确；
2. heartbeat 延长 lease；
3. complete 后 processing 为空；
4. 运行时间超过初始 lease 但 heartbeat 正常时不重复执行；
5. Worker 崩溃后 reaper 只恢复一次；
6. 两个 Worker 并发 claim 同一任务时只有一个成功；
7. 重复 enqueue 同一 task_id 只产生一个任务；
8. retry 和 dead-letter 状态正确；
9. Redis 重连后状态不丢失；
10. processing 列表或 ZSET 不会随已完成任务增长。

### P0-2：把导题 Worker 从 Web Worker 中拆出

不要在每个 Gunicorn Web Worker 的 lifespan 中直接启动导题、PDF、OCR、公式批处理等长任务 Worker。

请建立明确的进程角色，例如：

- `PROCESS_ROLE=web`
- `PROCESS_ROLE=worker`
- `PROCESS_ROLE=scheduler`

要求：

- web 进程只处理 HTTP、鉴权、轻量 DB 查询和任务入队；
- worker 进程处理导题、外部 OCR、AI 修复、公式生成；
- scheduler 进程处理定时任务，或者使用严格 leader election；
- 在资源有限时 worker 并发默认只能为 1；
- Web Worker 不得执行重型 pipeline；
- worker 必须支持 SIGTERM：停止领取新任务，等待当前任务在规定时间内结束，不能结束则安全释放 lease；
- 所有 `asyncio.create_task()` 必须保存引用、捕获异常、关闭时 cancel 并 await；
- task reaper、pipeline worker、AI prewarm worker 都必须有明确的 start/stop；
- 应用关闭时关闭 Redis、httpx、数据库 engine 和所有 executor。

### P0-3：修复生产配置 fail-fast

修复 `services/production_config_validator.py`。

同步检查必须在存在错误时抛出 `SystemError`，不能只记录日志。

生产环境至少验证：

- `APP_SECRET` 长度和默认值；
- PostgreSQL + asyncpg；
- Redis 可连接；
- Alembic 在 head；
- CORS 无通配符、localhost；
- OCR deployment profile 合法；
- `OCR_USE_GPU=false`；
- `OCR_EXECUTION_BACKEND` 必须为允许的外部 API backend 或 disabled；
- 云端禁止 `local_process`；
- 云端禁止 unsafe thread fallback；
- 云端禁止 remote failure 回退到 local；
- 外部 OCR URL 必须为配置的 HTTPS 地址，除非明确允许内网 HTTP；
- 外部 OCR token 必须存在；
- 云端启动时不得检测本地 PaddleOCR 包；
- 生产临时目录、静态目录和持久存储可写；
- worker 和 web 角色配置一致。

增加启动配置参数化测试，非法组合必须启动失败。

### P0-4：修复请求作用域 Session 被后台任务复用

检查所有 FastAPI BackgroundTasks 和 `asyncio.create_task()`。

禁止把请求依赖提供的 `AsyncSession` 传入响应之后执行的后台任务。

例如数学图片处理任务必须：

```python
async with async_session() as db:
    ...
```

自行创建、提交、回滚和关闭 Session。

所有后台任务必须只接收可序列化 ID、文件对象引用和配置，不接收：

- request 对象；
- UploadFile；
- 请求作用域 Session；
- ORM 实例；
- 内存闭包中的 pipeline store。

## 四、OCR 架构修复

### 1. 统一 profile 检测

所有模块必须调用同一个：

```python
detect_deployment_profile()
```

禁止各自使用不同的：

- `APP_ENV`
- `DEPLOY_PROFILE`
- `DEPLOYMENT_PROFILE`
- 默认 `"local_import"`

`OCRGateway` 构造时必须显式传入已解析的 profile，不能自行默认成 `local_import`。

### 2. 云端移除本地依赖检查

修复图片导入中无条件执行的：

```python
importlib.util.find_spec("paddleocr")
```

只有 `local_process` backend 才检查本地 OCR 依赖。

外部 API backend 只检查：

- URL；
- token；
- timeout；
- 健康状态；
- 配额和并发。

### 3. 删除云端 legacy local fallback

审计并修改：

- `services/ocr_service.py`
- `services/ocr_executor_service.py`
- `features/pipeline_orchestrator.py`
- `features/ocr_gateway.py`
- `core/ocr_process_pool.py`
- 所有 `reset_ocr_engine()` 调用

在 cloud profile 中：

- Gateway 失败后不得调用 legacy executor；
- 不得调用 `reset_ocr_engine()`；
- 不得导入 `ocr_process_pool`；
- 不得尝试本地文字 fallback；
- fallback chain 必须在执行前和执行后都校验；
- 发现本地 backend 时记录安全错误并终止该 OCR 路由。

### 4. 外部 OCR 客户端

外部 OCR 客户端必须：

- 复用单例 `httpx.AsyncClient`；
- 设置 connect、read、write、pool timeout；
- 设置最大连接数；
- 使用全局并发信号量；
- 有有限重试、指数退避和随机抖动；
- 仅对连接失败、429、502、503、504 重试；
- 不对业务 4xx 无限重试；
- 有 circuit breaker；
- 有请求大小限制；
- 有响应大小限制；
- token 不出现在 URL、日志和异常中；
- shutdown 时关闭客户端。

云端总 OCR 并发必须是跨 Web/Worker 进程可控的，必要时使用 Redis semaphore，而不是只有进程内 Semaphore。

## 五、任务输入和文件持久化

当前 durable task 不得依赖本地 `/tmp` 路径或 24 小时缓存中的 `_file_path`。

改为：

1. 上传时流式写入受控 staging storage；
2. 生成不可变对象 ID、SHA-256、大小和 MIME；
3. task payload 只保存 object_id；
4. worker 根据 object_id 获取文件；
5. 完成、失败超过保留期或取消后统一清理；
6. 重启和容器重建后文件仍可读取；
7. 定期清理 orphan staging objects；
8. 临时文件目录设置磁盘配额和最大年龄；
9. 启动时清理超过安全年龄的遗留临时文件；
10. 不允许用户提供任意服务器路径。

如果生产暂时使用本地磁盘，则必须使用 Docker volume 中的持久目录，而不是容器 `/tmp`。

## 六、PDF 和图片内存治理

重构 `pdf_renderer_service`：

- 不允许一次把所有页面 PNG 保存在 `dict[int, bytes]`；
- 使用 page window 或 async iterator，每次最多保留 1 页，云端默认 1；
- 页面处理完成立即释放 bytes、Pixmap 和临时文件；
- 需要跨阶段使用时保存对象引用，不保存全量 bytes；
- `ThreadPoolExecutor` 必须真正传给 `run_in_executor`，或者删除无效 executor；
- PDF 渲染、PIL 解码、压缩、PyMuPDF 操作必须在受限 executor 中运行；
- executor 队列必须有上限，队列满返回 429/503；
- 避免同时在内存和磁盘保存完整副本；
- 处理后明确关闭 PIL Image、PyMuPDF Document 和 BytesIO；
- 防止 decompression bomb；
- 校验文件 magic、页数、像素、尺寸、文件大小和压缩比。

云端建议默认限制：

- 单文件 5MB，可配置但不得默认 200MB；
- PDF 最多 30 页；
- 同时处理文档数 1；
- 同时渲染页面数 1；
- 单页像素预算；
- 外部 OCR 调用总数预算；
- pipeline 总超时；
- 临时磁盘总预算。

不要只依赖 OCRProfile；所有上传入口、resume、后台管理入口和内部接口都必须走同一套校验。

## 七、消除事件循环阻塞

审计全部 `async def`，重点修复：

- PIL `Image.open/resize/save`
- PyMuPDF `fitz.open/get_pixmap`
- 本地 `open/read/write/remove`
- 哈希大文件
- 腾讯 COS 同步 SDK
- Excel 解析
- 图片压缩
- 公式渲染
- 大型 JSON 序列化
- CPU 密集文本拆题和规则分析

处理原则：

- 小型异步文件 I/O 可用 aiofiles；
- CPU 或阻塞 SDK 放入专用、受限 executor；
- 不得使用无限制默认线程池承接所有重任务；
- 不得在持有数据库事务时执行外部 API、文件上传或 CPU 重任务；
- 外部网络请求完成后再开启短事务写库；
- 对 executor 任务增加 timeout 和取消策略。

修复 `storage_backend.py`：

- LocalFileStorage 的 async 方法不得直接同步写文件；
- COS SDK 调用必须 offload 或改用异步客户端；
- 图片压缩不得在路由事件循环中直接运行；
- 上传失败后的 local fallback 必须由配置控制，生产 COS 失败时不得静默写入容器本地磁盘。

## 八、Redis 和 AI 预热修复

AI prewarm 不能继续使用无确认语义的 `BLPOP`。

统一复用可靠任务队列，至少支持：

- processing 状态；
- ack；
- lease；
- heartbeat；
- crash recovery；
- retry；
- dead-letter；
- 幂等；
- 限流。

禁止 Redis 不可用时降级到裸 `asyncio.create_task()`。

AI 调用增加：

- 进程内并发上限；
- 跨进程并发上限；
- 用户级、功能级和全局限流；
- 每日/月度 Token 限额必须原子计数；
- circuit breaker；
- 超时；
- 请求取消；
- 429 重试；
- 缓存；
- 避免 stampede；
- shutdown 时关闭共享 httpx client。

## 九、Scheduler 修复

修复番茄钟锁逻辑：

```python
if not got_lock:
    return
```

不要在未获得锁时继续执行扫描。

所有 scheduler 应采用以下一种方式：

- 独立 scheduler 进程；
- PostgreSQL advisory lock；
- 可续租的 Redis leader lock。

要求：

- 锁 TTL 小于任务最长时间时必须续租；
- 未获得锁立即退出；
- 调度任务必须有批次上限；
- 调度器不能在每个 Web Worker 中无条件启动；
- refresh token cleanup 也必须有 leader 或数据库幂等批处理；
- 审计清理任务运行超过锁 TTL 时不能被第二实例重入；
- 增加 scheduler duration、skipped、failed、processed 指标。

## 十、数据库性能修复

根据 2 核、1.8GB 约束重新计算连接预算。

Gunicorn Worker 数、后台 Worker 数、scheduler 和运维连接的总和必须不超过 PostgreSQL 安全连接预算。

建议从较小值开始，例如每个 Web Worker：

- pool_size 2～3；
- max_overflow 1～2；
- 较短 pool_timeout；
- 总连接数写入启动日志。

具体值必须通过压测确定。

批量消除以下 N+1：

- 知识路径逐节点掌握度查询；
- mastery 更新逐知识点查询；
- practice 跨学科循环查询；
- AI prewarm 逐错题查询；
- review 逐题查询；
- 批量知识点 get-or-create；
- 导入逐题 flush/refresh；
- 公式批量逐条 get。

使用：

- 一次性 `IN` 查询；
- JOIN；
- selectinload；
- PostgreSQL upsert；
- bulk insert/update；
- 批量返回映射；
- 必要的唯一索引。

审计所有 `ORDER BY random()`，大表改用：

- 随机 ID 范围；
- 预计算随机桶；
- TABLESAMPLE；
- 候选集合随机；
- 缓存候选池。

对以下查询执行 PostgreSQL `EXPLAIN (ANALYZE, BUFFERS)`：

- 今日复习；
- 错题列表和统计；
- practice 推荐；
- 知识状态；
- pipeline 状态；
- audit log cleanup；
- pomodoro 到期扫描；
- task 管理查询；
- question import review queue。

缺失索引通过 Alembic migration 增加，不能只修改 ORM 模型。

## 十一、SSE 和轮询

当前批量图片 SSE 会按 0.5～1.5 秒为每个客户端建立新数据库 Session 并查询。

修复为：

- Redis Pub/Sub、Streams 或 PostgreSQL LISTEN/NOTIFY 推送；
- 无新事件时降低查询频率；
- 限制单用户并发 SSE 连接数；
- 设置连接最长时间；
- 反向代理断开后立即取消 generator；
- heartbeat 不触发数据库查询；
- 终态后及时关闭；
- 记录 active SSE connections。

## 十二、资源保护必须真正接入主路径

项目中存在多套 ResourceGuard，但当前生产 legacy pipeline 并未可靠使用。

请合并为一个实现并接入所有导入入口。

至少检查：

- RSS；
- 系统可用内存；
- 临时磁盘；
- 当前 pipeline 数；
- OCR 调用并发；
- 页面像素预算；
- 外部 API 调用预算；
- 队列长度；
- DB pool 使用率；
- event-loop lag。

资源不足时：

- 不再接收新导入任务；
- 返回稳定错误码和 Retry-After；
- 不允许先入无限队列再等待；
- 不影响登录、刷题、答题提交等核心轻量接口。

## 十三、可观测性和健康检查

增加指标和结构化日志：

- event-loop lag；
- HTTP p50/p95/p99；
- DB pool checked-out/wait；
- 慢 SQL；
- task ready/processing/retry/dead；
- task execution duration；
- lease renewal failure；
- duplicate execution prevented；
- pipeline stage duration；
- OCR external request duration、429、timeout、circuit state；
- AI duration、token、timeout；
- RSS、内存和临时磁盘；
- active SSE；
- scheduler lock acquired/skipped；
- orphan temp files cleaned。

`/health/live` 只表示进程存活。

`/health/ready` 必须检查：

- PostgreSQL；
- Redis；
- Alembic；
- 当前角色依赖；
- worker queue；
- 云端 OCR 外部 API 配置；
- 磁盘可写和剩余容量；
- 生产 OCR 隔离规则。

不要让外部 OCR 短暂抖动直接杀死 Web readiness，可区分 degraded 和 not-ready。

## 十四、测试和验收标准

必须新增测试目录和自动化测试。

### 单元测试

- 配置 profile 判定；
- 云端 OCR 禁止本地 fallback；
- TaskQueue claim/heartbeat/ack/reaper；
- scheduler lock；
- 文件清理；
- PDF 页窗口；
- ResourceGuard；
- 批量 SQL 行为。

### 集成测试

使用真实 Redis 和 PostgreSQL：

- 双 Worker 并发 claim；
- Worker 在执行中被 kill；
- lease 恢复；
- complete 后不重复；
- Redis 短暂断连；
- PostgreSQL 连接池耗尽；
- 外部 OCR timeout/429/500；
- 服务 SIGTERM；
- 容器重启后任务恢复。

### 云端 OCR 隔离测试

启动 cloud_api 配置后：

- monkeypatch `__import__`，任何 `paddle` 或 `paddleocr` 导入立即让测试失败；
- 检查没有 OCR 子进程；
- 检查没有 GPU 初始化；
- 外部 OCR 返回失败时任务进入 review 或明确失败；
- 不安装 OCR requirements 时服务仍能正常启动和调用外部 OCR。

### 压力测试

在接近 2 核、1.8GB 的容器限制下测试：

1. 普通 API 并发；
2. 一个 PDF 导题任务同时处理普通请求；
3. 多个导入请求快速提交；
4. 外部 OCR 延迟和失败；
5. SSE 长连接；
6. 数据库达到百万级练习记录后的核心查询。

验收要求：

- 不发生 OOM；
- Web API 不被导题任务长期阻塞；
- event-loop lag 在明确阈值以内；
- 同一 task_id 执行次数始终为 1，除非前一次明确失败并进入 retry；
- processing、retry、临时文件不会持续增长；
- graceful shutdown 后无未回收 task；
- cloud_api 环境未加载任何本地 OCR 模型；
- 所有新增测试通过；
- `compileall`、lint、类型检查通过。

## 十五、输出要求

请按以下顺序工作并输出结果：

1. 先列出确认的问题及代码路径；
2. 先修复所有 P0，再处理 P1；
3. 直接修改实际代码；
4. 给出新增或修改的环境变量；
5. 给出 Alembic migration；
6. 给出完整测试；
7. 给出旧配置兼容和回滚方案；
8. 给出生产部署步骤；
9. 给出压测方法和验收结果；
10. 最后列出仍未解决的风险。

禁止：

- 只写 TODO；
- 只提供设计说明而不改代码；
- 用 `except Exception: pass` 隐藏问题；
- 通过增加超时掩盖死锁或阻塞；
- 通过扩大内存和 Worker 数掩盖架构问题；
- 在生产环境降级为内存队列；
- 在云端静默回退到本地 OCR；
- 把同步重任务直接放进 FastAPI 事件循环；
- 声称“durable”但仍依赖临时文件或进程内状态。
