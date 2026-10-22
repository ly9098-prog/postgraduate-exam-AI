# Redis 使用情况与稳定性设计

> 状态：与当前代码同步（更新于 2026-09-29）
> 适用范围：`backend/`、`deploy/`、`miniprogram/pages/pomodoro/`
> 事实依据：源码、生产 Compose、生产只读探测。未执行过写操作/压测的内容会明确标注。

## 1. 结论摘要

Redis 在本项目中不是可选缓存，而是生产环境的核心基础设施，同时承担：

- 持久任务队列（`taskq:v2:*`）与 outbox 投递/对账
- 分布式锁（调度任务、答题投影对账）
- 安全态（用户/Admin JWT 失效与黑名单）
- AI 每用户限流与日/月 Token 预算
- OCR 全局并发控制与资源预留
- 导出/SSE 跨实例 Pub/Sub
- 暂存文件引用计数与生命周期锁
- 通用业务缓存与健康检查

设计已具备 Lua 原子操作、owner fencing、租约心跳、死信队列、outbox 对账与生产 fail-closed 等长期稳定性要素。主要风险集中在运维侧：单实例、持久化/内存策略此前未显式声明、健康检查曾被本地缓存掩盖、OCR 信号量降级语义不一致。

## 2. 接入方式

| 项目 | 现状 |
|------|------|
| 客户端库 | `redis[hiredis]==5.0.1`（`backend/requirements.txt`） |
| 配置项 | 单一 `REDIS_URL`（`backend/app/core/config.py`） |
| 默认（本地） | 空，未配置即禁用 Redis |
| 生产默认 | `redis://redis:6379/0`（`deploy/docker-compose.prod.yml`） |
| 生产校验 | 受限环境强制 `REDIS_URL` 且 PING 成功（`production_config_validator.py`） |
| 服务镜像 | `redis:7-alpine`（生产实测 7.4.10） |

客户端在多个模块各自懒初始化（`cache.py`、`task_queue_service.py`、`resource_guard.py`、`ai_runtime_guard.py`、`token_budget.py`、`ocr_distributed_concurrency.py`、`staging_storage.py` 同步客户端）。尚未统一到单一封装，属于后续可优化项。

## 3. 键空间与用途

### 3.1 持久任务队列（`taskq:v2:*`）

`backend/app/services/task_queue_service.py`

| Key | 类型 | 用途 |
|-----|------|------|
| `taskq:v2:ready:{type}` | List | 待执行队列 |
| `taskq:v2:processing:{type}` | ZSet | 执行中，score=租约到期 |
| `taskq:v2:retry:{type}` | ZSet | 重试，score=重试时间 |
| `taskq:v2:dead:{type}` | List | 死信（LRIM） |
| `taskq:v2:corrupt:{type}` | ZSet | 损坏任务 |
| `taskq:v2:task:{id}` | Hash | 负载/元数据 |
| `taskq:v2:heartbeat:{id}` | String | owner token，TTL=租约 |
| `taskq:v2:idempotent:{id}` | String | 幂等守卫，TTL=8d |
| `taskq:v2:fencing:{id}` | Hash | 单调代数；任务终态后 TTL=7d，执行中无 TTL |

- 入队/认领/心跳/完成/重试/死信/回收均通过 Lua 原子执行。
- `owner_token` + generation 拒绝过期 worker 写入。
- 租约时间以 Redis 服务器时间为准，避免多机时钟偏差。
- 独立 worker 进程消费：`python -m app.worker_main`；生产为 `worker` 容器。
- Redis 不可用时入队返回 `redis_unavailable`；dispatcher 指数退避，连续失败 10 次后打开熔断并周期探测，恢复后自动重入。

### 3.2 Outbox → Redis

`backend/app/services/outbox_service.py`、`outbox_reconciliation_service.py`、`outbox_runtime.py`

- PostgreSQL Outbox 为权威，Redis 只是投递/执行层。
- dispatcher 用 `FOR UPDATE SKIP LOCKED` 取待发布记录 → `enqueue_v2` → 标记 published。
- Redis 不可用按基础设施暂停处理，不消耗业务重试次数，采用有界指数退避（默认 5s→60s）。
- reconciler 修复 DB/Redis 漂移，并有“仅因 Redis 不可用被错误永久失败”的历史恢复路径。

### 3.3 分布式锁

| 实现 | 文件 | 语义 |
|------|------|------|
| `DistributedLock` | `backend/app/core/distributed_lock.py` | 严格 fail-closed，Lua acquire/renew/release + owner token |
| `cache.acquire_lock` | `backend/app/core/cache.py` | 宽松，Redis 失败时退化为进程内锁 |
| `cache.acquire_lock_strict` | `backend/app/core/cache.py` | 严格，用于安全路径 |

使用点：`system_task_service.py` 全部调度任务、`practice/projection_reconciliation_service.py`、Admin refresh token 等。

### 3.4 安全态

| 用途 | Key | 失败行为 |
|------|-----|----------|
| 用户 JWT 全局失效 | `user:jwt:nbf:{user_id}` | 503 fail-closed |
| Admin JWT 黑名单 | `admin:jwt:blacklist:{jti}` | 503 fail-closed |
| Admin 用户级失效 | `admin:user:nbf:{user_id}` | 503 fail-closed |
| Admin refresh token 单次消费 | `admin:refresh:used:{jti}` | 503 fail-closed |
| Admin 登录失败/锁定 | `admin:login:fail:{sha256(ip|username)}`、`admin:login:account_fail:{username}`、`admin:login:account_lock:{username}` | 503 fail-closed |

使用 `*_strict` 变体，确保多 web 实例共享且不会因 Redis 故障放宽吊销语义。

Admin 已实现的完整键空间（与代码同步）：

| 用途 | Key | TTL / 语义 | Redis 不可用时 |
|------|-----|------------|----------------|
| JWT 黑名单 | `admin:jwt:blacklist:{jti}` | 剩余 token 有效期 | 503 |
| 用户级 nbf | `admin:user:nbf:{user_id}` | 30d，覆盖式 | 503 |
| Refresh token 单次消费 | `admin:refresh:used:{jti}` | 剩余 refresh 有效期（最长 7d，消费标记不得早于 token 过期），值为 owner token | 503 |
| 登录失败（IP + 用户名哈希） | `admin:login:fail:{sha256}` | 15min，计数 | 503 |
| 账号级失败计数 | `admin:login:account_fail:{username}` | 15min，计数 | 503 |
| 账号临时锁 | `admin:login:account_lock:{username}` | 15min，值为 1 | 503 |
| Admin readiness 探针 | `admin:health:ping` | 10s，写后读校验 | 返回 `redis=degraded` |
| Dashboard overview | `admin:dashboard:overview` | 300s ± 10% 抖动 | 直接查 DB，不缓存 |
| Dashboard 防穿透锁 | `admin:dashboard:overview:lock` | 10s，严格获取；释放为 Lua compare-and-delete | 退化为本地锁/直接查 DB |
| AI enrich 任务状态 | `admin:ai:task:{task_id}` | 86400s，任务 JSON | 可能读不到；不替代 DB 权威记录 |
| AI enrich 批次最新任务指针 | `admin:ai:batch:{batch_id}:task` | 86400s，task_id | 可能读不到；不替代 DB 权威记录 |
| 调度任务心跳 | `admin:system-task:scheduler-heartbeat` | 75s，Hash；每 20s 更新 | 仅影响调度器状态观测 |
| 调度任务执行 telemetry | `admin:system-task:{task_id}` | 30d，Hash | 仅影响后台任务状态显示 |
| 角色权限版本 | `admin:role:version:{role_id}` | 永久（覆盖式 uuid），角色权限变更时刷新 | 权限缓存停用，退化为每次查 DB |
| 角色权限集缓存 | `admin:perm:role:{role_id}` | 900s ± 10% 抖动，`{version, permissions}` | 每次查 DB（与历史行为一致） |
| 在线状态 | `admin:online:{user_id}` | 300s，每次鉴权请求续期；仅观测用 | 在线快照为空，鉴权不受影响 |
| 接口限流 | `admin:ratelimit:{user_id}:{class}` | 60s 固定窗口；batch=10/min、stats=30/min、默认 60/min，super_admin ×2 | 放行（不限流） |
| 幂等请求 | `admin:idempotency:{user_id}:{key}` | 执行中预约 3600s，完成响应 600s；路径/方法/请求体指纹绑定，同键并发返回 409 | 关键批量写返回 503（fail-closed） |
| 限流豁免 | `admin:bypass:{sha256(token)}` | 30d（可自定义），经 `X-Admin-Bypass-Token` 提交；仅 `/dashboard/overview`、`/dashboard/daily`、`/redis/online` 可豁免限流，不豁免 JWT/RBAC | 视为无豁免（fail-closed）；增删需 system:write + critical 审计 |
| OCR 任务进度快照 | `admin:ocr:task:{task_id}` | 3600s，轮询用 JSON；DB 仍为权威 | 快照读不到，接口回退 DB 记录 |
| Dashboard daily 统计 | `admin:stats:daily:{from}:{to}` | 300s ± 10% 抖动（跨度 ≤31 天才缓存） | 直接查 DB |

原规划中 `admin:perm:user:{userId}` 实现为按角色聚合的 `admin:perm:role:{roleId}`（同一角色权限集相同，命中率和失效成本更优；用户到角色的映射本就每次实时读取）。幂等当前仅接入 batch-delete 与 imports 批量 approve/reject；其余批量写端点可按需复用 `require_idempotency` 依赖。

### 3.5 AI 限流与 Token 预算

- `core/ai_runtime_guard.py`：每用户固定窗口限流，受限环境 Redis 不可用即 fail-closed；AI 并发信号量仍为进程内。
- `features/token_budget.py`：`memograd:{env}:ai:tokens:day:{date}`（TTL 3d）、`...:month:{month}`（TTL 40d）；受限环境 Redis 不可用时暂停 AI 调用。

### 3.6 OCR 并发与资源预留

- `services/ocr_distributed_concurrency.py`：ZSet 全局槽位，Redis 错误在 cloud_api 直接抛错。
- `core/resource_guard.py`：ZSet + meta 预留活跃 pipeline；受限环境 Redis 不可用则拒绝新任务。
- `features/ocr_vl/paddleocr_vl_client.py`：PaddleOCR-VL ZSet 信号量 `semaphore:ocr_vl:v2`，上限 2。**2026-09-28 起受限环境 fail-closed**，只有本地开发才降级为无全局限制。

### 3.7 通用缓存与订阅

| 场景 | Key 前缀 | TTL |
|------|----------|-----|
| 导入流水线状态/检查点 | `import:pipeline*` | 24h |
| Admin AI enrich 状态 | `admin:ai:task:*`、`admin:ai:batch:*:task` | 86400s |
| 番茄钟/刷题科目树 | `practice:subject_tree:*` | 24h |
| 推荐策略/实验/知识路径失效 | `recommendation:*`、`knowledge:path:*`、`practice:smart:*` | 按调用 |
| 向量推荐/相似题 | `vector:*` | `vector_cache_ttl_sec`（默认 300s） |
| 统计/复习/知识点 | `stats:*`、`review:*`、`kp:*` | 30–3600s |
| SSE 批图进度 | `sse:job:{job_id}` | ephemeral |
| 导出状态推送 | `export:task:events:*` | ephemeral |

`cache.delete` 使用 `SCAN`；`cache.clear()` 只清本地缓存，禁止 `FLUSHDB`，避免清掉队列/锁/黑名单。

### 3.8 暂存引用计数

`services/staging_storage.py`：`staging:v2:refcount:{object_id}` 原子增减；对象生命周期锁 + `.lease` 文件双重保护。清理前 `get_refcounts()` 批量校验，生产 Redis 不可用直接抛错、不删文件。

## 4. 失败降级矩阵

| 组件 | Redis 不可用时 |
|------|----------------|
| 任务队列（生产） | 拒绝入队；worker 退避+熔断，恢复后重入 |
| Outbox dispatcher | 暂停 + 有界退避，不计业务重试 |
| 通用 cache | 降级进程内，多实例可能不一致 |
| JWT / Admin 鉴权 | 503 fail-closed |
| AI 限流 / Token 预算 | 受限环境 fail-closed |
| ResourceGuard 预留 | 受限环境拒绝新导入 |
| OCR 分布式并发 | cloud_api 抛错拒绝 |
| PaddleOCR-VL 信号量 | 受限环境拒绝（2026-09-28 修复） |
| SSE / 导出推送 | 降级 DB 轮询 |
| Staging 引用计数 | 生产抛错，不删文件 |
| 严格分布式锁 | 获取失败，任务跳过 |
| `/health/ready` | 生产 503（2026-09-28 修复） |

## 5. 本次稳定性修复（2026-09-28）

1. **readiness 真实探测**：`/health/ready` 的 `_check_redis()` 改用新增的 `cache.ping()`，不再被进程内缓存兜底；修复前 Redis 宕机仍可能返回 `redis: ok`。
2. **持久化与内存策略**：生产 Redis 显式 `--appendonly yes --appendfsync everysec`，`--maxmemory 192mb --maxmemory-policy noeviction`，容器 `mem_limit` 由 128m 提升到 256m，给 AOF 重写/碎片留出余量。
3. **备份与还原入口**：新增 `deploy/scripts/redis_backup.sh`（BGSAVE + 原生 RDB 归档 + 文件头校验 + 保留期清理）和 `deploy/scripts/redis_restore.sh`（AOF-safe 恢复）；`deploy.sh backup` 现在同时备份 PostgreSQL 与 Redis，另有 `backup-redis`、`redis-restore` 子命令。
4. **OCR 信号量语义对齐**：PaddleOCR-VL 在 production/cloud_api 下 Redis 失败改为抛错拒绝，只有本地开发降级。
5. **番茄钟科目树缓存**：新增 `practice:subject_tree:*` 24h 共享缓存；Admin 科目创建/修改/删除后立即失效。小程序侧新增 `pomodoro_subject_cache_v1` 本地 24h 缓存，减少进入页面时的网络请求。
6. **admin:refresh:used 堆积修复**：管理端前端将 access token 持久化到 sessionStorage，页面刷新复用未过期 token、减少 rotate；消费标记仍须保留至 refresh token 过期（最长 7 天），否则旧 token 可在标记过期后重放（修复前生产 329 条、约 35 万~53 万秒 TTL）。
7. **REDIS_PLAN 规划键落地**：`admin:role:version:*`/`admin:perm:role:*`（角色权限缓存 + bump 失效）、`admin:online:*`（鉴权请求续期 + `/api/admin/v1/redis/online` 快照）、`admin:stats:daily:*`（daily 统计缓存）、`admin:ratelimit:*`（依赖注入式限流）、`admin:idempotency:*`（batch-delete、imports 批量 approve/reject，Redis 不可用 503）、`admin:bypass:*`（sha256 存储豁免 token，critical 审计）、`admin:ocr:task:*`（OCR job 轮询快照，DB 仍权威）。回归测试见 `backend/tests/test_api/test_admin_redis_plan.py`。

## 6. 生产配置与实测

按 `docs/project/DEPLOY_PLAN.md` 的连接方式（`ssh -i Linux_connect.pem root@101.33.231.186`）核验。下表为 **2026-09-28 修复并恢复完成后的状态**：

| 指标 | 值 |
|------|-----|
| Redis 版本 | 7.4.10 |
| `used_memory` | ~1.69 MB |
| `maxmemory` | 192 MB |
| `maxmemory_policy` | noeviction |
| `appendonly` | yes（everysec） |
| `aof_last_bgrewrite_status` | ok |
| `rdb_last_bgsave_status` | ok |
| `DBSIZE` | 597 |
| `evicted_keys` | 0 |
| `expired_keys` | 9154 |
| 宿主机可用内存 | 约 1.6 GB |
| 磁盘可用 | 约 21 GB |

生产数据量远低于 192MB 上限；单实例与无 Sentinel 仍是主要可用性风险（见第 7 节）。

**未执行**：故障注入与高负载 AOF 重写压测。恢复过程曾因旧 AOF 被加载导致 `DBSIZE=0`，已从 RDB 恢复并重建 AOF；因此生产恢复必须使用 `redis_restore.sh`，不能手工只替换 `dump.rdb`。

## 7. 遗留风险与后续建议

| 优先级 | 事项 | 说明 |
|--------|------|------|
| P1 | Redis 单实例无 Sentinel | 容器/主机故障即全站鉴权与任务队列不可用；长期应评估 Sentinel 或独立队列实例 |
| P2 | 缓存与不可淘汰数据共用实例/DB | 建议按用途拆分实例或逻辑 DB，避免缓存挤占队列 |
| P3 | 多套客户端与连接池分散 | 建议统一客户端封装（超时、重试、关闭策略） |
| P4 | AI 并发信号量为进程内 | 多实例下 AI 总并发上限不可控，可评估迁移到 Redis |
| P5 | Admin 规划键与实现偏差 | 已在 `docs/admin/REDIS_PLAN.md` 顶部和第 2 节标注设计稿/未实现项；当前实现清单见本文 3.4 节 |
| P6 | 监控告警 | 已接入任务健康监控的 `used_memory/maxmemory`、`evicted_keys` 与答题投影键巡检；`rejected_connections`、慢日志、AOF 重写状态告警仍待接入 |

### 答题投影 Redis 容量监控

- 管理端「系统 / 任务」的 Redis 内存卡片及 `GET /api/admin/v1/tasks/diagnostics` 返回 `redis.memory`：已用字节、配置上限、占用率、累计淘汰键数及阈值。定期任务健康监控沿用状态变化才记录日志 / 发 Sentry 事件的机制；默认占用率 **50% 预警、75% 错误**，内存未设限、出现淘汰也预警。阈值可分别由 `TASK_HEALTH_REDIS_MEMORY_WARN_PCT`、`TASK_HEALTH_REDIS_MEMORY_ERROR_PCT` 配置。Redis 不可用时容量不伪报为零，仍由 `REDIS_UNAVAILABLE` 报警。
- scheduler 的任务健康监控默认**每 15 分钟**只读 `SCAN` 一次答题投影的 `idempotent`、`fencing`、`task` 键，记录按类型的近似数量与**缺 TTL 的幂等键**，同时从 `practice_records`（已有 `projection_state, answered_at` 索引）记录过去 24 小时答题量。幂等键缺 TTL 为错误；任务进行中的 fencing / task 键允许无 TTL，不触发该错误。扫描最多 4096 页 / 5 秒；超预算则明确提示巡检未完成，**部分数量不得视为总数**，内存占用告警仍然有效。可用 `TASK_HEALTH_REDIS_PROJECTION_SCAN_INTERVAL_SEC` 调整巡检间隔；不在每次管理端请求中扫描全库。
- 以上只提供当前读数和状态变化告警，**不存储历史曲线，也不自动删除 Redis 键**。需分析增长率时结合 Redis 外部时序监控或定期留存健康指标；幂等键保留 8 天，不能仅为压缩内存直接缩短 TTL（Outbox 对账依赖该保留期）。

## 8. 运维命令速查

```bash
# 生产连接（见 docs/project/DEPLOY_PLAN.md）
ssh -i Linux_connect.pem root@101.33.231.186
cd /opt/22408-ai

# 备份 PostgreSQL + Redis
bash deploy/scripts/deploy.sh backup

# 仅备份 Redis
bash deploy/scripts/redis_backup.sh backup      # 或 deploy.sh backup-redis
bash deploy/scripts/redis_backup.sh list

# 从 RDB 安全恢复（AOF-safe；会停止 Redis、快照旧数据、重建 AOF）
# 备份目录默认值以 deploy/scripts/redis_backup.sh（BACKUP_DIR 默认 PROJECT_DIR/redis_backups）为准；
# 如需改目录，可设置宿主机路径 REDIS_BACKUP_DIR。
bash deploy/scripts/deploy.sh redis-restore /opt/22408-ai/redis_backups/redis_YYYYmmdd_HHMMSS.rdb

# Redis 状态（只读）
docker exec deploy-redis-1 redis-cli INFO memory
docker exec deploy-redis-1 redis-cli INFO persistence
docker exec deploy-redis-1 redis-cli CONFIG GET appendonly maxmemory maxmemory-policy
docker exec deploy-redis-1 redis-cli DBSIZE

# 应用 Redis 配置（重建 Redis 容器，不会删除命名卷）
bash deploy/scripts/deploy.sh update      # 如仅 Redis 配置变更，可单独重建 redis 服务
```

## 9. 相关文件

| 主题 | 路径 |
|------|------|
| 通用缓存 | `backend/app/core/cache.py` |
| 配置 | `backend/app/core/config.py` |
| 严格分布式锁 | `backend/app/core/distributed_lock.py` |
| 资源预留 | `backend/app/core/resource_guard.py` |
| AI 限流 | `backend/app/core/ai_runtime_guard.py` |
| Token 预算 | `backend/app/features/token_budget.py` |
| 任务队列 | `backend/app/services/task_queue_service.py` |
| Worker | `backend/app/services/task_queue_worker.py` |
| Outbox | `backend/app/services/outbox_service.py` |
| 安全态 | `backend/app/core/security.py`、`backend/app/core/admin_security.py` |
| OCR 并发 | `backend/app/services/ocr_distributed_concurrency.py`、`backend/app/features/ocr_vl/paddleocr_vl_client.py` |
| Staging 引用计数 | `backend/app/services/staging_storage.py` |
| 科目树缓存 | `backend/app/services/subject_tree_cache.py`、`miniprogram/pages/pomodoro/utils/subject-cache.js` |
| 生产 Compose | `deploy/docker-compose.prod.yml` |
| Redis 备份脚本 | `deploy/scripts/redis_backup.sh` |
