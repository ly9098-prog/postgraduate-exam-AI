# 任务队列语义与兼容基线

核对日期：2026-10-27。对应重构计划阶段 0/3；覆盖 `DurableTaskQueue`、v2 worker/outbox、Redis 键空间及隔离 worker 入口验证，不代表生产 worker 全部业务流程、生产 Redis 故障恢复或备份演练已完成。

本次更新：修复 v2 心跳以及标记损坏、取消、过期回收在异常或取消后未释放已获取客户端的路径，并分离对应执行装配。Lua、键空间与 owner/generation fencing 协议未改；第 7、8 节的独立 Redis 恢复与真实 `worker_main` 证据继续保留。

## 1. 入口与消费者

| 用例 | 实现入口 | 当前消费者 | 兼容边界 |
| --- | --- | --- | --- |
| v2 任务入队 | `DurableTaskQueue.enqueue_v2` | outbox dispatcher、任务 worker、AI prewarm、Admin/smoke 工具 | 生产/cloud 只接受 v2 key；幂等重复仍返回 accepted=True，队列满返回 accepted=False。 |
| v2 任务认领 | `dequeue_v2` | `task_queue_worker.run_dispatcher_v2`、AI prewarm、smoke test | 先 ready 再 retry；owner token + generation fencing；损坏 payload 移入 corrupt 后本次返回空。 |
| 心跳续租 | `heartbeat_v2` | 任务执行心跳和取消检查 | `1` 成功、`0` owner 不匹配、`-1` generation 已过期；Redis 异常向调用方传播。 |
| 成功完成 | `complete_v2` | worker、AI prewarm | 保持 v2 哈希、移除 processing/retry、保留幂等 guard，写入 fencing tombstone。 |
| 失败重试/死信 | `fail_v2` | worker、AI prewarm | `1` 进入 retry、`2` 直接死信、`0`/`-1` 为 fencing 拒绝；指数退避和重试预算由队列拥有。 |
| 管理取消 | `cancel_v2` | Admin 任务页 | pending→cancelled(1)、processing→cancel_requested(2)、retrying→cancelled(3)、dead→cancelled(4)、终态 no-op(0)。 |
| 过期回收 | `_reclaim_expired_v2`、`run_reaper_loop_v2` | scheduler/HTTP worker 启动 | 只回收 lease 已过期且 heartbeat 缺失的任务；v2 Lua 使用 Redis 时间。 |
| 健康统计 | `queue_length_v2` 等、`get_metrics_v2` | Admin 任务页、readiness、指标采样 | v2 健康方法在 Redis 不可用时抛 `QueueHealthError`，不能伪装为空队列。 |
| 死信/损坏管理 | `list_*_v2`、`retry_from_dead_v2`、`delete_*_v2`、`purge_dead_v2` | Admin 任务页/运维接口 | 保留可见错误摘要、FIFO/LIFO 顺序和受限容量；管理重试开启新 retry cycle。 |
| v1 兼容健康/死信 | `queue_length`、`get_metrics`、`oldest_ready_age`、`list_dead`、`purge_dead` | 旧调用/迁移与诊断入口 | v1 深度、指标聚合、就绪年龄与死信投影规则已拆为纯契约；仍保留 v1 吞 Redis 异常、返回 0/本地计数的旧语义，不得与 v2 抛错语义合并。 |
| v1→v2 迁移 | `drain_v1_to_v2`、`drain_all_v1_to_v2`、`delete_v1_keys` | 一次性迁移/运维工具 | v1 仅兼容保留，不被 v2 dispatcher 消费；每个任务由原子 Lua 迁移，校验身份、写 v2 hash/admission guard/ready list 后才移除 v1 位置。v2 满时保留 v1 队头；payload 缺失或身份不符时转为 v2 corrupt 诊断；v2 写入中途失败时回滚本次 partial hash/guard/ready 位置，保留 v1 队头供重试。 |

## 2. Redis 键空间与版本边界

- v1：`taskq:queue:*`、`taskq:processing:*`、`taskq:retry:*`、`taskq:dead:*`、`taskq:corrupt:*`、`taskq:task:*`。
- v2：`taskq:v2:ready:*`、`taskq:v2:processing:*`、`taskq:v2:retry:*`、`taskq:v2:dead:*`、`taskq:v2:corrupt:*`、`taskq:v2:task:*`。
- 共享命名：`taskq:heartbeat:*` / `taskq:v2:heartbeat:*`、`taskq:idempotent:*` / `taskq:v2:idempotent:*`、`taskq:v2:fencing:*`。
- v2 `Task` 保留 `schema_version`、`minimum_worker_version`、`trace_id`、`request_id`、`owner_token`、`generation`。旧 payload 缺版本字段时按 worker 兼容默认值恢复；不支持的 answer projection schema 在入队前拒绝。
- 生产/cloud 画像禁止进程内队列兜底；local_import 只有在 `ALLOW_IN_MEMORY_TASK_QUEUE` 显式开启且 Redis enqueue 返回可降级原因时才可执行本地任务。

## 3. 状态机与异常语义

- enqueue 的幂等 guard 在任务完成后仍保留（8 天），避免短时间重放创建第二条业务任务；重复不会返回新的 task_id 之外的副作用。
- dequeue 认领后若 JSON/payload 身份校验失败，调用 `mark_corrupt_v2`，返回 None，不把损坏任务交给业务 handler。
- worker 版本不兼容属于不可重试的业务拒绝，应进入死信/人工处理，而不是无限重试。
- `TaskQueueUnavailableError` 只在 v2 dequeue/complete/fail 的 Redis 连接、超时或响应协议错误时抛出；调用方据此暂停/降级，不能用空任务代替。
- v1 health 方法为了兼容旧调用会吞 Redis 异常并返回 0/本地计数；v2 health 方法必须抛错。不能把两套错误语义合并。
- v1 `oldest_ready_age` 的历史口径保留：无任务/无 payload 或 `created_at=0` 返回 0；有效未来时间可返回负年龄；损坏 JSON、非数值时间戳等 payload 错误由外层异常兜底归零。v2 口径独立：无效载荷/时间归零，未来时间钳制为 0。
- v1 死信列表保留有效 JSON 原对象、缺失 hash 标记 `hash_expired`、损坏 JSON 标记 `corrupt_payload`；purge 对缺失/损坏 payload 只移除列表不删 hash，对过期有效 payload 同时删除列表与 hash，边界时间为严格大于且不删除。
- v1/v2 指标聚合均复制进程内计数器并按传入类型累加 `ready/processing/retry/dead`，不修改原计数器字典；v1 与 v2 的 Redis 错误边界仍由各自长度方法持有。
- reaper 只能回收“lease 过期且 heartbeat 不存在”的任务；仍有心跳的 processing 任务不得被回收。
- 管理重试死信任务必须重置 retry budget/error，但保留 generation/fencing 事实；普通 `retry_from_dead_v2` 与 LREM 删除是不同操作。

## 4. Lua 脚本缓存

- 21 个 Lua 源文本分别由 `task_queue_lua_v1.py`、`task_queue_lua_v1_recovery.py`、`task_queue_lua_v1_to_v2.py`、`task_queue_lua_v2_claim.py`、`task_queue_lua_v2_transitions.py` 独占。
- `task_queue_script_bindings.py` 只保存 `(实例属性, Lua 源)` 的唯一有序清单；`DurableTaskQueue` 按该顺序调用 `SCRIPT LOAD`，缓存 SHA，并在 `NOSCRIPT` 后清空全部绑定再重载。
- 脚本顺序、SHA、KEYS/ARGV 参数和键命名是线协议，不能因重构改变。脚本内容哈希由架构门禁固定。
- 服务通过共享 Redis connection pool 执行脚本，单连接客户端用于阻塞 dequeue；连接返回/关闭分别属于调用点，不得用一个全局连接替代两种用途。

## 5. 可执行基线

- `backend/tests/architecture/test_task_queue_protocol_boundaries.py`：21 个脚本哈希、脚本数据模块预算、绑定顺序与源文本、服务尺寸下限。
- `backend/tests/core/test_task_queue_script_bindings.py`：加载顺序、重复加载幂等、NOSCRIPT 全量重载。
- `backend/tests/core/test_task_queue_v1_to_v2_migration.py`：使用 fakeredis + Lua 执行原子迁移成功、v2 满保留 v1、缺失/错配 payload 转 corrupt、已有 v2 guard 去重及半写 v2 hash 冲突保护。
- `backend/tests/core/test_queue_metrics.py`、`test_runtime_metrics_contract.py`：Task 基础字段、指标采样和队列端口契约。
- `backend/tests/integration/test_queue_hardening.py`、`test_queue_fencing.py`、`test_queue_integration.py`：需要 `--run-integration` 和真实临时 Redis。2026-10-24 本机 `redis-server 7.2.5`（127.0.0.1:6380，DB1，无持久化）重放结果：hardening 23 passed、fencing 26 passed、integration 20 passed。
- 2026-10-26 在新建 Unix socket 的独立 Redis 7.2.5 实例、DB1、关闭持久化的环境重放上述 69 项：首轮 68 通过、1 项因测试仍从旧 service 导入私有版本常量失败；只将该测试改为引用实际所有者 `task_queue_contract`，生产代码未改。重跑 69 passed、0 skipped，包含真实 Lua、owner/generation fencing、重试/死信、取消、过期租约回收和迁移；不包含 Redis 进程中断恢复或完整跨进程 worker。测试仅操作新实例的合成数据，完成后停止该实例并保留日志。

## 6. 已知风险与后续

- `drain_v1_to_v2` 的 fakeredis Lua 契约与上述真实 Redis hardening 集成都已覆盖迁移、容量和 cancel/terminal 语义。
- 2026-10-25 修复迁移脚本的写入失败窗口：HSET/RPUSH/SETEX 包裹在 Lua `pcall` 中，任一失败会 LREM 本次 ready 位置、删除 partial v2 hash 与 idempotency guard，并把错误抛回 Python。2026-10-26 修正原失败注入夹具，改为在 fakeredis 的 Lua `redis.call` 内注入 SETEX 失败，实际覆盖 partial 状态清零、v1 队头保留和恢复重试；先前的 socket HSET 注入不能作为该 Lua 失败窗口的有效证据。这不替代真实 Redis 连接中断/进程崩溃测试。
- 2026-10-26 修复 Python 拆分后异常进度丢失：helper 用 `V1ToV2DrainError` 携带已确认迁移数，入口保留原 warning/logger 并返回该数；首项成功、第二项失败返回 1，不输出成功汇总。普通连接/脚本失败返回已确认数量，普通 close 失败不覆盖结果或原错误；取消继续传播并关闭已获取的客户端。迁移、结果契约和协议门禁定向 43 项通过，独立审查 112 组历史/当前行为对照一致。
- 同日补跑 `backend/tests/integration/test_worker_sigterm.py --run-integration`（真实 Redis，worker dispatcher 端口/替身）：7 passed，覆盖 drain 停止新领取、未知类型 dead-letter、heartbeat 安全/不安全 Redis 超时与 Lua 拒绝、取消 checkpoint、并发=1 时不超额执行。修复的是测试端口漂移：`set_draining_v2`/`stop_worker_v2` 现在是 async，heartbeat 替身需抛 `redis.exceptions.TimeoutError`，并保存/恢复模块级 running 标志；未改生产 worker 语义。
- 仍未验证：生产 worker 配置及全部业务 handler、多 dispatcher 并发、生产 Redis 中断恢复、生产角色退出和备份恢复演练。第 7 节为本机独立 Redis 队列恢复，第 8 节为隔离真实 worker 入口与学习投影；这些测试不能替代生产验收。
- Admin 任务页的真实浏览器操作、真实死信重试和长任务取消仍未验收。

## 7. 自有 Redis 进程崩溃与恢复

- `backend/tests/integration/owned_redis.py` 只启动新建 `/tmp/queue-recovery-*` 目录下的子进程，TCP port=0、私有 Unix socket、AOF 开启、`appendfsync=always`；不接受外部 URL 或已有数据目录。退出时只停止自己创建的子进程，保留 AOF、Redis 日志及包含 PID、run ID、版本、退出码、恢复结果的 `evidence.json`，不清库或删除目录。
- `test_queue_redis_recovery.py` 在显式 `cloud_api` 与由 `APP_ENV=production` 推断的有效配置下各执行三种场景，且故意设置 `ALLOW_IN_MEMORY_TASK_QUEUE=True`，证明受限环境仍禁止本地兜底。配置仅由 pytest monkeypatch 在测试进程内修改。
- 就绪任务场景：预热连接与全部 Lua SHA，实际 SIGKILL 并等待退出；中断期间 v1/v2 入队拒绝，v2 dequeue/health 报错。以相同 AOF 目录重启，确认 run ID 已变、脚本缓存为空、Python SHA 仍在；观察真实 `NoScriptError` 并由队列重载全部脚本。同一个队列、pool 和持久客户端恢复，原载荷保留、中断期间被拒的任务未写入、完成后的幂等重放不重新入队，重启后新任务也可完成。
- processing 场景：未过期任务的状态、owner、generation 保留，原持有者能够续租与完成；续租从 120 秒延长至 300 秒，直接核对 Redis 时间、processing score、hash lease 和 heartbeat TTL 的实际增长。短租约在真实停机等待期间到期，reaper 恰好回收一次，新领取提高 generation 并更换 owner。旧持有者每次 heartbeat/complete/fail 被拒绝后，立即比对 task hash、processing score、heartbeat owner/TTL 和 fencing，防止后续合法心跳修复被破坏索引而掩盖问题；新持有者完成且 ready/processing 均为空。
- 未访问中断实例的旧 socket 可能在重启后的第一次操作中抛出 `QueueHealthError` 或 `TaskQueueUnavailableError`。测试通过最多三次调用验证后续重连，并将错误写入证据；不宣称第一次请求必然成功，也未给生产方法添加自动重试。入队/完成等存在响应丢失窗口的操作不由此测试证明 exactly-once 业务效果。
- 2026-10-27 本机 Redis 7.2.5 定向执行：6 passed、0 skipped。复现命令为从 `backend/` 执行 `python -m pytest tests/integration/test_queue_redis_recovery.py --run-integration -q`，需安装 `redis-server` 并使用隔离测试配置；不依赖 `TEST_REDIS_URL`。Reliability Gate 增加同一显式命令及证据 artifact，远端 CI 结果未验证。
- 范围限制：这是私有单节点 Redis、合成任务、AOF always 的本地恢复证据，不覆盖生产 `everysec` 丢写窗口、网络分区、Redis 集群、完整 worker 进程、外部 OCR/AI 调用或备份恢复。

## 8. 真实 worker 进程与学习投影

- `backend/tests/integration/test_worker_process_recovery.py` 使用 `OwnedWorker` 启动未修改的 `python -m app.worker_main`。子进程采用白名单测试环境和新建私有 cwd，不加载仓库 `.env`，不注入替代 handler、信号处理器、dispatcher 或缩短租约的 monkeypatch。真实入口会启动 executors、dispatcher、reaper 和 AI prewarm，关闭 OCR/GPU/向量功能。
- `owned_postgres.py` 通过本机 PostgreSQL server binaries 初始化全新集群，仅监听权限为 0700 的私有 Unix socket，TCP 关闭；Redis 同样使用自有实例。真实 Alembic `upgrade head` 在该集群执行，只有合成用户、题目、不可变版本、知识点和待投影的练习记录被加入。进程身份记录、数据库、AOF、日志和元数据均保留，测试退出只停止自行创建的子进程。
- Linux harness 为服务创建独立 session，关闭前记录实际子孙进程及 PID 出生标记；正常关闭失败时通过 pidfd 仅终止这些自有进程，并核验无运行中的遗留进程。该跟踪也覆盖自行创建其他 session 的 PostgreSQL backend；一个 worker 的强制清理失败不会跳过其他 worker。服务子进程只接收白名单环境，HOME/TMPDIR 指向私有目录，Python 依赖路径保持父解释器的已安装包顺序，不透传父环境凭据。
- SIGTERM 场景：父进程锁定练习记录，确认真实 worker 已领取任务且 PostgreSQL 实际等待该锁，再发送 SIGTERM。进入 drain 后释放锁，当前任务完成，后续任务保留 pending，进程正常退出。替换 worker 执行遗留任务，同一练习事件使用新任务 ID 再投递，业务投影不得重复。
- SIGKILL 场景：同样在真实 SQL 锁等待时终止 worker，确认未产生学习副作用；等待默认 600 秒租约与 heartbeat 自然到期，期间不删 heartbeat、不修改 processing score 或服务器时钟。替换 worker 的真实 reaper/dispatcher 重新领取，generation/token 改变，旧 owner 操作被拒绝，释放锁后投影完成。
- 学习效果由独立 SQL 观察核对：练习投影终态、唯一答题行为及版本、Leitner answer/correct/wrong count 和盒子等级、知识点 attempt/correct/wrong count 与掌握度、adaptive 难度状态及计数；重复投递后结果完全一致。fixture 故意令可变题目答案与不可变版本不同，并使用不同 question/version ID，锁定历史证据来源。该场景不声称覆盖所有题型、错误作答、推荐归因或外部 AI 分析。
- 复现：从 `backend/` 执行 `python -m pytest tests/integration/test_worker_process_recovery.py --run-integration -q`，需安装 PostgreSQL server binaries 与 `redis-server`。完整用例会真实等待约 10 分钟；`-k sigterm` 只运行正常退出场景。CI 配置独立步骤及证据 artifact，远端运行未验证。
- `test_owned_process_isolation.py` 另以真实 SIGSTOP 的 PostgreSQL backend 检查 fast stop 失败后的整组清理，并注入首个 worker 强制等待错误，验证其余 worker 仍被关闭；合成凭据标记不得进入子进程，未标记为自有的进程组必须被拒绝。
- 2026-10-27 本机 PostgreSQL 15.8、Redis 7.2.5 最终冻结七份测试源码执行：上述两文件合计 5 passed、0 skipped，耗时 664.55 秒；相关生命周期、投影、架构与 Redis 回归另有 320 passed。独立审查修复并关闭旧 claim 采样、adaptive 与 immutable 断言、后代进程清理及环境隔离等缺口；缩短租约的独立诊断探针仅用于竞态正反对照，不计入真实 600 秒验收。
- 范围限制：使用 `APP_ENV=test` / `local_import`，不是生产配置验证；生产 PostgreSQL/Redis、外部 OCR/AI、备份恢复和多 dispatcher 竞争仍需单独验收。旧 `test_worker_kill.py` 手动操作键的测试不作为本节实际进程信号证据。

## 9. v2 心跳执行与客户端释放

- `heartbeat_v2` 保留签名、身份解析及 Redis 启用检查，委托 `task_queue_v2_heartbeat_execution.py` 执行脚本与结果处理。任务身份在获取客户端前快照；方法、Lua key/前缀和结果回调仍按原时序动态读取。没有新增 Redis 客户端、连接池、后台任务或协议脚本。
- 修复前，`_load_scripts` 或 `_evalsha_or_reload` 抛出异常或取消时，已获取客户端没有调用 `aclose()`。修复后两条路径都尝试关闭一次，再传播原始异常；未获取客户端时不关闭。正常执行仍先关闭，再转换 Lua 结果及更新指标/本地租约估计。
- 关闭失败不能替换已有的脚本错误或取消，仅在原异常上附加关闭异常类型，不附加可能含连接信息的错误详情；诊断 note 本身失败也不替换主异常。正常关闭没有主异常时，关闭错误继续直接传播。第二次取消若中断异常清理，保留第一次取消及其类型 note；这里只保证关闭尝试，不把中断的关闭宣称为完成。
- 客户端为 `None` 继续返回 0 且不计 fencing 拒绝；Lua `None` 继续按 0 处理并记录 owner mismatch。`0/-1` 继续更新拒绝计数，只有成功结果 1 的 `Task` 才更新本地租约估计，Redis TIME 仍为真实租约依据。Redis 连接、超时、ResponseError 及其他异常保持原类型，不包装为 complete/fail 使用的 unavailable 错误。
- 本地行为基线覆盖 wire 参数、关闭/结果顺序、动态端口、身份快照和异常传播；取消测试使用真实 asyncio Task。修复前保留行为基线 68 项通过，新增清理回归 34 项失败、1 项通过，失败均指向遗漏的关闭路径。该结果不代表生产 Redis、全部 worker handler、真实微信、外部 OCR/AI 或备份恢复验收。
- 修复后定向 115 项与队列相关 282 项均通过，连接守卫零触发；10 个有效破坏版本全部被拒绝，覆盖漏关/重复关闭、取消遗漏、主异常被覆盖、结果过早写回、空客户端误计 fencing、错误 key 前缀、端口快照、身份重读和清理详情泄漏。
- 本批另以自有私有 Unix socket Redis 7.2.5 重放 `test_queue_hardening.py`、`test_queue_fencing.py`、`test_queue_integration.py`、`test_worker_sigterm.py`：76 passed、0 skipped，71.63 秒。守卫只允许本实例 socket，数据库、外部网络及真实 `.env` 读取零触发；实例已停止，AOF、日志与所有权证据保留。最后一个文件使用 dispatcher/heartbeat 端口替身，不能计作真实 `worker_main` 全流程或进程信号验收；本轮没有重跑第 7、8 节的 Redis 崩溃恢复与 worker 进程测试。

## 10. v2 管理转换与过期回收的客户端释放

- `mark_corrupt_v2`、`cancel_v2`、`_reclaim_expired_v2` 继续检查 Redis 是否启用，并保留普通异常的原 warning 和 `False/0` 返回；取消仍向调用方传播。临时客户端执行装配移入 `task_queue_v2_admin_execution.py`，不改变 Lua、键、ARGV、容量、tombstone TTL 或取消状态码。认领路径使用持久客户端，不纳入本批逐次释放。
- 三条路径在脚本装载或执行失败后均尝试关闭已获取客户端一次；取消原因构造与回收结果转换在关闭前失败时也执行清理。未取得客户端时不关闭，成功后不重复关闭。二次取消可能中断关闭，因此“关闭尝试”不能冒充“关闭完成”。
- 清理错误只附加异常类型，不把原错误替换为清理错误，也不输出清理详情；诊断 note 损坏仍保留主错误。普通主错误继续由服务原 handler 记录并返回 `False/0`，主取消则继续传播。正常关闭失败没有主错误时仍按原 handler 处理，正常关闭期间的取消继续传播。
- 转换顺序保持：标记损坏与取消在关闭后解释结果；回收在关闭前按原 `raw or 0` 规则并转换整数，关闭后才检查正数、记录日志及累加 `reaper_reclaimed`。日志失败时不新增计数。mark-corrupt 保留 bool 结果和不截断摘要；cancel 原因仍经原 helper 裁剪至 200 字符，正状态码才输出成功日志。
- 服务方法、配置、键函数、结果/日志/指标端口按原等待边界动态读取，不捕获副本。125 项兼容行为在原实现与新实现均通过；新增清理回归在原实现为 66 failed、3 passed，修复后全部通过。定向行为/架构/协议合计 208 passed，队列相关合计 484 passed，均无外部连接尝试；11 个有效破坏版本全部被拒绝。
- 本批重新启动独立私有 Unix socket Redis 7.2.5，重放第 9 节列出的四个集成文件：76 passed、0 skipped，71.17 秒；仅允许本实例 socket 的守卫零触发，实例正常退出且日志/AOF/所有权证据保留。未执行生产操作、Redis 进程崩溃、真实 `worker_main` 全 handler、真实 Admin 浏览器或备份恢复验收。
