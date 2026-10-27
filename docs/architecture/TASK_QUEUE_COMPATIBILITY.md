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

## 11. v2 worker 分发、fencing 生命周期与工作副本清理

- `_process_task_v2` 从 310 行收敛至 21 行，保留签名、docstring、None 返回及最先导入
  context 回调的边界。`worker_v2_execution.py` 组合准备、资源清理和 post-fence；
  `worker_v2_dispatch.py` 保留九类任务的有序分支；pipeline/aux handlers 保留各分支的
  延迟导入及参数装配。`worker_v2_state.py` 只持有本次任务身份、载荷引用、token 和工作
  副本清单；五个新增业务文件均满足 300 行/50 行预算，独立导入不启动运行时或加载 ORM。
- 保留各 handler 的执行顺序：PDF 先 verify 再 staging，图片先 staging 再 verify，
  Excel 先 staging/读字节再 verify，admin resume 先 staging/checkpoint 再 verify 和
  session。批量图片保留原 staging 列表的序号空位、逐项工作副本与 payload 默认值。
  直接学习投影和错因分析仍调用原 worker 端口，formula 保留查询结束后执行 batch。
- record ID、task type、pipeline ID 与 payload 引用按原时点捕获；owner/generation、
  worker 端口与 fencing 类型集合仍在原等待边界读取。分支内导入的业务回调不因后续 await
  被替换，batch source 构造器与每次 cleanup 回调继续动态读取。Excel 仍支持 worker
  命名空间的 open 端口。成功清理后才执行原子 post-fence：拒绝仍 rollback 并抛出
  FencingRejectedError，普通 post-fence 异常仍沿用非致命 warning 策略，取消继续传播。
- 修复原 finally 的失败窗口：原先第一个 cleanup 报错/取消会跳过后续副本及 context
  reset，并覆盖 handler 的主错误。现在顺序尝试所有已登记工作副本，再尝试一次 context
  reset；已有主错误时保留其原对象和类型，否则传播最早的清理错误。后续失败仅添加异常
  类型 note，不添加清理详情；note 损坏也不阻断剩余清理。有任何主错误或清理错误时均
  不执行 post-fence。这里只处理该 claim 登记的工作副本，不删除 staging 原件或扩展清理范围。
- 82 项原有行为刻画在原实现与拆分后均通过；新增清理回归在原实现为 14 failed、
  2 passed，修复后全部通过，包含真实 asyncio Task 的主取消及清理期间第二次取消。
  7 项架构检查约束入口绑定、依赖、预算、staging 身份参数和 fresh import。反向展开
  helper 后，准备、九类分发、staging 解析及 post-fence 的业务 AST 与原实现一致；
  worker 其他定义一致。12 个故障变体均被拦截，对照 98 项通过，隔离守卫无违规尝试。
- 关联队列、staging、运行时、学习投影、错因分析与架构纯端口回归 818 项通过，守卫零
  触发。真实 checkpoint 的 13 项 SQLite 契约另在仅允许专属临时目录 `.db` 的守卫下通过，
  放行 67 次连接，无违规。独立私有 Unix socket Redis 7.2.5 的四文件集成回归 76 项
  通过、无跳过，74.44 秒；实例正常退出，AOF、日志和所有权证据保留。
- 本批另重放第 8 节真实 `worker_main` SIGTERM 场景：PostgreSQL 15.8 / Redis 7.2.5、
  真实迁移、SQL 锁等待、drain、替换 worker、投影及重复投递断言均通过；1 passed、
  1 deselected，24.31 秒，排除项为 SIGKILL/600 秒租约恢复场景。父 pytest 守卫仅允许
  私有目录的 Unix socket，零违规；子进程沿用白名单测试环境，两个 worker 与自建 PG/Redis
  均正常退出，日志和数据保留。该结果不等于生产配置、全部 OCR/AI handler、外部 provider、
  多 dispatcher 或备份恢复验收；v1 执行与 v2 dispatcher/claim/heartbeat 仍有剩余大函数。

## 12. v2 已领取任务的启动、监督与资源释放

- 2026-10-28，`_process_claimed_task_v2` 从 141 行收敛至 26 行，保留签名、
  docstring 和最先导入日志 context 回调的边界。新增 `worker_claimed_state.py`、
  `worker_claimed_execution.py`、`worker_claimed_outcome.py`、
  `worker_claimed_cleanup.py`，分别持有本次资源、启动三个子任务、监督业务与终态转换、
  顺序清理；新业务文件均满足 300 行/50 行预算，独立导入不加载配置、ORM 或 worker。
- 修复启动不完整时的泄漏：非法 payload、日志身份准备失败、子协程构造失败、部分
  `create_task` 失败都进入资源清理；未提交成功的协程尝试关闭，已登记的子任务取消并
  等待。日志 reset 失败也继续尝试释放已持有的 semaphore 槽位。没有更改 claim 协议、
  payload 校验或数据库/Redis 状态机；非法 payload 仍传播原错误。
- 已有主错误或取消优先保留，后续清理错误只附加异常类型 note，不附加错误详情；
  note 损坏也继续释放资源。没有主错误时传播最早的清理错误。原来等待 heartbeat/watcher
  时忽略普通异常和取消的策略保持；清理顺序仍为 watcher、heartbeat、必要时 process、
  日志 context、semaphore。只保证尝试清理，不能把被二次取消中断的等待表述为完成。
- 修复业务 `TimeoutError` 被误判为硬超时：当业务 Task 已结束且未取消，异常进入原
  业务失败/fencing 策略，不增加 hard-deadline 指标，也不再发生先 fail 后 complete。
  真正由 `wait_for` 取消业务 Task 的超时仍沿用原硬期限策略。外层在业务等待期间取消
  仍按原 owner-loss 策略处理，终态转换期间取消仍向调用方传播；不扩大本批取消语义。
- heartbeat 继续覆盖 complete/fail 转换。日志回调在生成身份前捕获；worker 端口、
  日志器、指标与完成回调在原执行边界动态读取；三个子任务仍按 heartbeat、process、
  owner-loss watcher 顺序创建。完成码 `1/0/-1`、fencing 处理、500 字符错误摘要和
  原日志保持。逆向展开 helper 并移除上述超时修复后，业务 try/except 与原 AST 一致；
  context 准备与 worker 其余定义也一致。
- 41 项兼容性用例在原版和修复版均通过；33 项新增回归在原版全部失败，修复版全部
  通过，包含实际 claim adapter 可产生的非法 payload。另有 8 项架构检查，共 82 项
  定向通过；队列、staging、运行时、学习投影与错因分析关联回归共 900 项通过，隔离
  守卫零违规。10 个有效故障变体均被拒绝，覆盖漏关协程、漏放槽位、跳过部分子任务、
  主错误被覆盖、超时误判、过早停心跳、完成码、指标、摘要长度及 note 损坏。
- 冻结业务、测试与 CI 清单后，本机按当前 YAML 的静态步骤精确重放 384 个测试文件：
  6733 passed、0 skipped、55 条既有弃用 warning，529.14 秒。新 Python 文件的
  3.11 语法、预算、严格 Ruff/format，app 正确性 Ruff、compileall 与 diff-check
  均通过；这是本地清单重放，不代表远端 CI 或生产验收。
- 独立私有 Unix socket Redis 7.2.5 四文件集成回归 76 passed、0 skipped，
  71.20 秒；仅放行自有 socket，守卫零违规。实例已停止，AOF、日志和所有权证据保留。
  本批另重放第 8 节未修改的真实 `worker_main`，独立 PostgreSQL 15.8 / Redis 7.2.5、
  实际迁移、SQL 锁等待、SIGTERM drain、SIGKILL 后默认 600 秒租约自然到期、
  替换 worker 与重复学习投影检查：2 passed、0 skipped，666.11 秒。父 pytest 守卫
  零违规，子进程使用白名单测试环境，数据及日志保留。
- 本批没有执行生产操作、全部业务 handler、外部 OCR/AI、真实微信、生产 Admin 浏览器、
  多 dispatcher 竞争或备份恢复；这些仍需单独验收。worker 的 v1 执行、v2 dispatcher
  与 heartbeat 等仍有剩余大函数，不能把本次结果表述为任务队列或全部优先任务完成。

## 13. legacy v1 任务分派处理器拆分

- 2026-10-28，`_process_task` 从 207 行收敛至 35 行，保留签名、task_type/payload/
  pipeline_id 的读取、初始 info 日志、工作副本清单、`_resolve_legacy_staging` 闭包、
  try/finally 清理顺序与 `namespace=globals()` 动态命名空间。九类 v1 分支移入
  `backend/app/services/worker_legacy_handlers.py`（228 行，最长函数 39 行），入口改为
  `select_legacy_handler(task_type, globals())` + `await handler(context)`，仍在原
  try/finally 内执行，finally 仍按登记顺序清理工作副本。
- 分支顺序与惰性导入保持：import、image、excel、resume、admin-resume、
  answer-projection、error-diagnosis、formula、batch-image。九个 handler 的业务导入
  全部延迟到调用时；Excel 仍读取 worker 命名空间的 open 端口；answer/error 仍调用
  原 worker 端口；formula 仍在 session 关闭后执行 `process_batch`；batch-image 保留
  原始 1 基序号（含空档）、逐项工作副本和“无有效来源即 FileNotFoundError”；未知类型
  仍抛出完全一致的 `unknown_task_type: {task_type}`。admin-resume 的 payload 字段
  读取时点与原实现一致（staging 解析之后、checkpoint 与 session 之前）。
- 12 项固定契约在拆分前的原实现与拆分后均通过（8 项原有 + 4 项新增：Excel 命名空间
  open 覆盖、admin payload 读取顺序、空 staging 不登记也不清理、batch-image 空来源
  守卫）。18 个故障变体全部被拒绝，覆盖选择器映射与未知错误文本、惰性导入、命名空间
  open、实时端口、payload 读取时点、formula session 顺序与 cards、batch 序号/路径/
  守卫、pipeline_id 捕获、resolve 钩子、工作副本登记与 finally 清理、空命名空间、
  初始日志移除。
- 7 项架构门禁约束 300/50 预算、显式依赖集合、模块级零 `app.*` 导入（业务导入只能
  出现在函数体内）、选择器九分支顺序与 `namespace[...]` 动态常量、入口委托与清理
  所有权、worker 模块不再定义 handler、fresh import 不加载 config/ORM/业务模块，
  并含两项门禁反向自检。worker 定义除 `_process_task` 外与原实现 AST 一致，选择器
  分支顺序经 AST 校验（`/tmp/worker-legacy-dispatch-ast-report.json`）。
- 既有 question writer / formula batch 依赖门禁同步改为新 owner：writer 的消费方
  列表与 formula batch runner 的导入方由 `task_queue_worker` 改为
  `worker_legacy_handlers`，并保留“spec service 不得被 worker/legacy 反向导入”的
  方向约束；未删除或放宽任何原断言，所有权现由新增模块的显式依赖集合门禁覆盖。
- 定向回归：新增契约/门禁与 worker v2、claimed、AI prewarm、formula 批次合计
  246 passed；task queue v1/v2 契约、协议与脚本绑定合计 122 passed；严格
  Ruff/format、compileall、300/50 预算与 diff-check 通过。
- 冻结业务、测试与 CI 清单后，本机按当前 YAML 的静态步骤精确重放 398 个测试文件：
  6884 passed、0 failed、64 条既有弃用 warning，430.14 秒；Mocked readiness
  boundary regression 69 passed；Cloud OCR profile boundary regression 30 passed。
  这是本地清单重放，不代表远端 CI 或生产验收。
- 仍未执行生产操作、全部业务 handler、外部 OCR/AI、真实微信、生产 Admin 浏览器、
  多 dispatcher 竞争或备份恢复。v1 执行仍有剩余大函数：`run_pipeline_worker` 131 行、
  `run_dispatcher_v2` 108、`_v2_heartbeat_loop_with_lease_window` 102、
  `_enqueue_v2_with_local_fallback` 72、`graceful_shutdown_v2` 56；task queue service
  的 `retry_from_dead_v2`、`heartbeat`、`dequeue_v2` 等仍在待拆分清单。

## 14. legacy v1 worker 循环监督拆分

- 2026-10-28，`run_pipeline_worker` 从 131 行收敛至 49 行，保留签名、docstring、
  `_worker_running` 全局读写、`task_types = DISPATCHER_TASK_TYPES` 的一次性读取、
  draining 跳过、dequeue 失败告警、空轮询休眠，以及 CancelledError 日志和 finally
  复位。逐任务监督抽为 6 个模块级 helper：`_process_supervised_task`（19 行，创建
  heartbeat、processing、owner-loss monitor 并委托）、`_settle_supervised_task`
  （27 行，持有 try/except/finally 与清理所有权）、`_dispatch_supervised_outcome`
  （15 行）、`_complete_supervised_task`（14 行）、`_fail_supervised_task`（18 行）、
  `_cancel_supervised_tasks`（25 行）；全部满足 300/50 预算。
- 保留原语义，包括可观察的运行特性：处理中被取消仍按 owner-loss 吞掉取消、指标累加
  两次且外层循环继续；空闲期（dequeue/休眠）取消则抛出 CancelledError、记录
  “Pipeline worker cancelled”并在 finally 复位 `_worker_running=False`；complete
  抛错转入 fail 路径；fail 被拒绝、owner-lost 跳过 fail 各自累计 `owner_fencing_rejected`；
  heartbeat 在取消后抛出的非取消异常只告警；heartbeat/processing/monitor 的创建顺序、
  monitor→heartbeat→processing 的清理顺序与 “处理已结束则不再二次取消” 均未改变。
- 14 项固定契约在拆分前的原实现（本次先写测试后改代码）与拆分后均通过。18 个故障
  变体全部被拒绝：16 个由断言捕获，2 个（跳过取消 monitor 或 heartbeat）表现为
  监督协程永不结束、测试挂起超时，同样判定为检测成功。反向展开 6 个 helper 与
  `run_pipeline_worker` 的委托调用后，AST 与原实现完全一致；worker 其余定义不变
  （`/tmp/worker-legacy-loop-ast-report.json`）。
- 4 项架构门禁约束循环与 helper 的 50 行预算、draining→dequeue 顺序、dequeue
  lease 参数、监督创建顺序、settle 的 except/finally 归属、清理顺序与 heartbeat
  异常告警，并含“内联监督/交换创建顺序会被拒绝”两项反向自检。
- 定向回归：新增契约/门禁与 worker v2、claimed、legacy dispatch 批次合计 224 passed；
  worker lifespan/readiness 端口与 task queue v1 契约合计 199 passed；严格
  Ruff/format、compileall、300/50 预算与 diff-check 通过。
- 冻结业务、测试与 CI 清单后，本机按当前 YAML 的静态步骤精确重放 400 个测试文件：
  6902 passed、0 failed、64 条既有弃用 warning，434.11 秒；Mocked readiness
  boundary regression 69 passed；Cloud OCR profile boundary regression 30 passed。
  这是本地清单重放，不代表远端 CI 或生产验收。
- 仍未执行生产操作、全部业务 handler、外部 OCR/AI、真实微信、生产 Admin 浏览器、
  多 dispatcher 竞争或备份恢复。v1 循环已收敛后，worker 剩余大函数为
  `run_dispatcher_v2` 108、`_v2_heartbeat_loop_with_lease_window` 102、
  `_enqueue_v2_with_local_fallback` 72、`graceful_shutdown_v2` 56；task queue service
  的 `retry_from_dead_v2`、`heartbeat`、`dequeue_v2`、`enqueue` 等仍在待拆分清单。

## 15. v2 dispatcher 循环与 Redis 退避拆分

- 2026-10-28，`run_dispatcher_v2` 从 108 行收敛至 39 行，保留签名、docstring、
  `_v2_worker_running` 置位、调用时的 `get_worker_semaphore` 延迟导入、
  `DISPATCHER_TASK_TYPES` 一次性读取、启动日志与 CancelledError/finally 复位；循环体
  抽为 `_run_dispatcher_v2_loop`（41 行），Redis 退避抽为
  `_handle_v2_redis_failure`（28 行）与 `_probe_v2_redis_recovery`（14 行），任务派生
  抽为 `_spawn_v2_processing`（10 行），全部满足 300/50 预算。
- 并发槽所有权保持：先 acquire 再认领；draining/running 变化时 release 后停止；
  Redis 失败释放后进入退避，空队列释放后按 `poll_interval` 休眠，派生成功则由处理
  任务在完成时释放。退避算术保持 `min(retry_after * (1 << min(count-1, 4)), 300)`，
  连续失败计数在任意成功认领（含空队列）后归零；第 10 次失败输出 critical 并进入
  降级探测，探测按 5 秒分片推进且每步检查 running/draining，可提前退出；派生使用
  `proc:<task_id>` 名称并登记/注销 `_v2_active_processing`，之后 `await asyncio.sleep(0)`
  让新任务起步。
- 9 项固定契约在拆分前的原实现（AST 提取原 `run_dispatcher_v2` 运行）与拆分后均
  通过，覆盖派生与槽释放、draining、失败计数与退避、300 秒上限、第 10 次熔断后的
  分片探测序列、探测对 draining/running 的提前退出、成功认领后的计数归零与取消复位。
  21 个故障变体全部被拒绝，覆盖探测步长/目标/提前退出、计数与指标、退避位移与上限、
  熔断阈值与 else 分支、派生名称与登记/注销、失败计数归零、认领 lease、任务类型快照、
  draining 释放、启动置位、启动日志与取消日志。
- 反向展开各 helper 并按三项已记录归一化（循环内失败计数器提升、`if 熔断: … continue`
  ＋尾随 `await sleep; continue` 折叠为 if/else、调用方赋值时丢弃同值 return）后，
  AST 与原实现一致；worker 其余定义不变（`/tmp/worker-dispatcher-v2-ast-report.json`）。
- 4 项架构门禁约束入口/循环/退避/探测/派生的预算与结构，含“删掉 draining 分支
  release”“把请求指标换成计数”两项反向自检。定向回归：dispatcher、legacy 循环/分派、
  worker v2/claimed 与心跳/管理执行批次合计 408 passed；runtime/lifespan 端口与
  task queue v1/v2 契约合计 387 passed；严格 Ruff/format、compileall、300/50 预算与
  diff-check 通过。
- 冻结业务、测试与 CI 清单后，本机按当前 YAML 的静态步骤精确重放 402 个测试文件：
  6915 passed、0 failed、64 条既有弃用 warning，434.90 秒；Mocked readiness
  boundary regression 69 passed；Cloud OCR profile boundary regression 30 passed。
  这是本地清单重放，不代表远端 CI 或生产验收。
- 仍未执行生产操作、全部业务 handler、外部 OCR/AI、真实微信、生产 Admin 浏览器、
  多 dispatcher 竞争或备份恢复。worker 剩余大函数为
  `_v2_heartbeat_loop_with_lease_window` 102、`_enqueue_v2_with_local_fallback` 72、
  `graceful_shutdown_v2` 56；task queue service 的 `retry_from_dead_v2`、`heartbeat`、
  `dequeue_v2`、`enqueue` 等仍在待拆分清单。

## 16. v2 心跳租约窗口拆分

- 2026-10-28，`_v2_heartbeat_loop_with_lease_window` 从 102 行收敛至 22 行，保留签名、
  docstring 与 `interval = max(lease_sec // 3, 10)`；单轮心跳体抽为
  `_v2_heartbeat_tick`（50 行），取消读取抽为 `_v2_heartbeat_cancel_requested`（18 行），
  失败登记抽为 `_abandon_v2_heartbeat`（8 行），瞬时错误重试抽为
  `_retry_v2_heartbeat_once`（22 行），全部满足 300/50 预算。
- 语义与顺序保持：成功心跳先读任务 hash 判断 `cancel_requested`（hash 缺失或读取异常
  均按非致命处理，原因缺省为空串），随后 `sleep(interval)` 继续；显式 Lua 拒绝
  （`ok != 1`）立即 owner-lost 并累加 `lease_renewal_failure`；瞬时错误
  （`ConnectionError`/`TimeoutError`）先算 `lease_window_remaining = lease_expires_at -
  time.time()`，小于 `interval * 2` 直接 owner-lost，否则告警后重试一次
  （`sleep(1)` + heartbeat），重试成功继续循环，重试被拒或抛错仍 owner-lost；
  `CancelledError` 静默退出；其他异常按 unexpected 处理并 owner-lost。失败登记固定为
  `logger.warning` → `queue_metrics["lease_renewal_failure"] += 1` → `owner_lost.set()`，
  owner_lost 置位后循环停止且不再尝试心跳。
- 14 项固定契约在拆分前的原实现（AST 提取原循环运行）与拆分后均通过，覆盖成功间隔
  休眠与取消标记跳过、取消请求、缺失原因默认空串、hash 缺失与读取异常、显式拒绝与
  指标、短窗口瞬时错误、安全窗口重试成功并继续循环、重试被拒、重试抛错、未预期异常、
  取消无副作用、无 owner_lost 事件时仍退出。25 个故障变体全部被拒绝（24 个产生失败、
  `while True` 变体超时判定为拒绝；证据 `/tmp/worker-heartbeat-v2-mutants-uq42szzy`），
  覆盖取消判定、读取失败处理、失败登记与指标、重试条件/休眠/异常范围、短窗口比较与
  参数、handler 顺序与类型、租约窗口取值、循环退出条件与间隔公式。
- 反向展开四个 helper 并按四项已记录归一化（`return True/False` 折回 `continue`/`break`、
  取消读取 try/except 折成谓词 helper、`return await _retry_v2_heartbeat_once(...)`
  就地内联、`_abandon_v2_heartbeat` 展开为 warning → 指标 → `owner_lost.set()`）后，
  与拆分前 AST 一致；worker 其余定义不变（`/tmp/worker-heartbeat-v2-ast-report.json`）。
- 3 项架构门禁（`tests/architecture/test_worker_heartbeat_v2_boundaries.py`）约束五个函数
  预算、循环委派与无 try/无指标、取消谓词结构、失败登记顺序、重试结构与单轮 handler
  顺序，含“去掉失败指标”“把短窗口比较放宽为 `interval`”两项反向自检。
- 定向回归：心跳/派发/legacy 循环与分派/claimed 边界合计 79 passed；worker claimed/v2、
  task queue v1/v2 心跳与管理执行批次合计 302 passed。`tests/integration/test_worker_sigterm.py`
  本机 7 skipped（缺 Redis 等依赖），未执行。
- 冻结业务、测试与 CI 清单后，本机按当前 YAML 的静态步骤精确重放 406 个测试文件：
  6943 passed、0 failed、64 条既有弃用 warning，441.55 秒；Mocked readiness
  boundary regression 69 passed；Cloud OCR profile boundary regression 30 passed。
  这是本地清单重放，不代表远端 CI 或生产验收。
- 仍未执行生产操作、真实 Redis 故障恢复、多 dispatcher 竞争或备份恢复。worker 剩余
  超预算函数为 `_enqueue_v2_with_local_fallback` 72、`graceful_shutdown_v2` 56、
  v1 `_heartbeat_loop`；task queue service 的 `retry_from_dead_v2`、`heartbeat`、
  `dequeue_v2`、`enqueue` 等仍在待拆分清单。
