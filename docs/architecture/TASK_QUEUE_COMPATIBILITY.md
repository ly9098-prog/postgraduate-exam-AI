# 任务队列语义与兼容基线

核对日期：2026-10-23。对应重构计划阶段 0/3；范围仅限 `DurableTaskQueue`、v2 worker/outbox 调用和 Redis 键空间，不代表完整 worker 循环、生产 Redis 故障恢复或备份演练已完成。

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
| v1→v2 迁移 | `drain_v1_to_v2`、`drain_all_v1_to_v2`、`delete_v1_keys` | 一次性迁移/运维工具 | v1 仅兼容保留，不被 v2 dispatcher 消费；每个任务由原子 Lua 迁移，校验身份、写 v2 hash/admission guard/ready list 后才移除 v1 位置。v2 满时保留 v1 队头；payload 缺失或身份不符时转为 v2 corrupt 诊断。 |

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
- reaper 只能回收“lease 过期且 heartbeat 不存在”的任务；仍有心跳的 processing 任务不得被回收。
- 管理重试死信任务必须重置 retry budget/error，但保留 generation/fencing 事实；普通 `retry_from_dead_v2` 与 LREM 删除是不同操作。

## 4. Lua 脚本缓存

- 21 个 Lua 源文本分别由 `task_queue_lua_v1.py`、`task_queue_lua_v1_recovery.py`、`task_queue_lua_v1_to_v2.py`、`task_queue_lua_v2_claim.py`、`task_queue_lua_v2_transitions.py` 独占。
- `task_queue_script_bindings.py` 只保存 `(实例属性, Lua 源)` 的唯一有序清单；`DurableTaskQueue` 按该顺序调用 `SCRIPT LOAD`，缓存 SHA，并在 `NOSCRIPT` 后清空全部绑定再重载。
- 脚本顺序、SHA、KEYS/ARGV 参数和键命名是线协议，不能因重构改变。脚本内容哈希由架构门禁固定。
- 服务通过共享 Redis connection pool 执行脚本，单连接客户端用于阻塞 dequeue；连接返回/关闭分别属于调用点，不得用一个全局连接替代两种用途。

## 5. 可执行基线

- `backend/tests/architecture/test_task_queue_protocol_boundaries.py`：20 个脚本哈希、脚本数据模块预算、绑定顺序与源文本、服务尺寸下限。
- `backend/tests/core/test_task_queue_script_bindings.py`：加载顺序、重复加载幂等、NOSCRIPT 全量重载。
- `backend/tests/core/test_task_queue_v1_to_v2_migration.py`：使用 fakeredis + Lua 执行原子迁移成功、v2 满保留 v1、缺失/错配 payload 转 corrupt、已有 v2 guard 去重及半写 v2 hash 冲突保护。
- `backend/tests/core/test_queue_metrics.py`、`test_runtime_metrics_contract.py`：Task 基础字段、指标采样和队列端口契约。
- `backend/tests/integration/test_queue_hardening.py`、`test_queue_fencing.py`、`test_queue_integration.py`：需要 `--run-integration` 和真实临时 Redis；当前环境未启动 Redis，因此只能执行静态/替身回归，不能宣称通过。

## 6. 已知风险与后续

- `drain_v1_to_v2` 的 fakeredis Lua 契约已覆盖上述丢失路径；但本机没有可用 `redis-server`，尚未在真实 Redis 执行迁移、容量并发或故障注入，不能把 fakeredis 结果记为真实集成通过。
- 完整 worker 主循环、lease 过期回收、多 dispatcher 并发、Redis 中断恢复、生产角色退出和备份恢复演练仍未验证。
- Admin 任务页的真实浏览器操作、真实死信重试和长任务取消仍未验收。
