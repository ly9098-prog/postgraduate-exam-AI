# Admin 模型配置、推荐与系统任务兼容边界

2026-10-30，§329 / ADM-05。六页、38 个归属消费契约及 6 个无当前静态浏览器消费形状的注册端点评估为 `RETAIN`。依据是已有职责和边界已分属明确 owner；本轮新增页面契约，未修改业务运行时。映射范围与端点明细见 [结果清单](refactor-results/admin-operations-retention-2026-10-30.json) 和 [Admin 消费者映射](ADMIN_CONSUMER_MAP.md)。

## 1. 范围与保留理由

| 页面 | 现有职责归属 | 保留的边界 |
| --- | --- | --- |
| `/ai-settings` | 页面及模型/OCR/补全/向量子组件；配置注册、全局解析设置与向量配置各自的 API/service | 模型稳定 ID、软删除、最后一个启用模型保护；数据库凭据加密、固定掩码响应；临时连接测试与持久化分开 |
| `/recommendation/experiments` | 页面表单、实验纯规则、实验服务与缓存 | 稳定分组、流量上限、安全阈值和自动暂停；状态 PATCH、安全检查 POST、创建 POST |
| `/recommendation/strategies` | 页面编辑状态、策略纯规则、策略服务与缓存 | 旧权重/综合权重和嵌套配置；种子初始化与保存分开；不重拆运行时推荐引擎 |
| `/recommendation/metrics` | 页面日期范围、指标服务 | 查询/补跑使用选择区间，聚合默认日期由后端决定；聚合锁与唯一性、逐日补跑失败隔离 |
| `/recommendation/reports` | 页面三类独立请求、质量服务和健康服务 | 推荐质量、知识质量和健康报告保持各自 SQL/投影口径 |
| `/system/tasks` | 页面请求/详情/确认状态、system-task-utils；Admin 路由、可观测服务/规则、系统任务与备份服务、outbox 服务 | 诊断/定时任务轮询、Redis 可用性门禁、trace/任务标识编码；重试/取消后刷新列表与当前详情；队列原子协议和调度锁仍归原服务 |

注册但无本次有界静态消费形状的 6 项继续保留：AI 月用量、Redis bypass token 创建/撤销、Redis OCR 任务检查、在线统计、队列状态。静态映射未找到当前页面形状不等于没有外部调用方。

## 2. 不变的协议与副作用

模型/向量路由仍要求 super_admin，全局解析设置使用 `ai_setting:read/write`；推荐读取使用 `recommendation:read`，写入使用 `question:write`。系统任务读取/执行分别使用 `system:read/write`，备份历史及手动备份的附加 `system:backup` 检查保留。

配置响应不暴露明文或加密凭据字段，掩码固定；模型软删除保留历史 ID，并按原规则清除被删模型的 embedding 选择。连接测试继续使用未保存的 Base URL/model/provider 编辑值，按能力选择 embedding/chat/Paddle 适配器。本轮没有调用真实外部服务。

路由提交、审计、配置/推荐缓存失效的现有顺序保持。系统任务能力检查在加锁前，执行遥测在取得锁后开始；Admin 取消仍调用现有 `cancel_v2`，旧 answer_projection 协议仍拒绝重试。Admin 端点结构收口不代表 worker、恢复、共享生命周期或 OCR 结构已经完成。

## 3. 新增契约与既有缺陷

新增 `operations-page-contracts.test.ts` 的 16 项用例直接调用六个真实 Client 页面和 `VectorConfigSection`，通过隔离的 hook/query/mutation/request 端口验证设置回填与保存、Embedding 参数/空选择、实验请求、指标日期范围、独立报告、策略请求，以及任务查询门禁/编码/取消后的刷新和错误反馈。

这些用例只证明端口行为。策略嵌套配置用例验证 mutation 请求序列化，没有证明编辑表单的整条转换；表单纯规则继续由已有 helper 测试约束。未挂载 DOM，未执行 React/TanStack 完整调度、effect 清理、原生 fetch 或浏览器 JWT。

另登记 `ADM-09 DEFECT`：真实 `admin_tasks.cancel_task` 获取 pooled client 后，在 `hgetall` 抛出异常时，执行不到后面的显式 `aclose`。隔离探针令 `_get_redis_client` 返回 `hgetall` 抛 `RuntimeError` 的 AsyncMock，调用真实入口后观察到 `aclose.await_count == 0`。复现脚本与结果位于本轮证据目录；结果清单保留可重建步骤。

这是原有异常路径清理缺口，运行时未改。尚未测量真实 Redis 连接泄漏数量、连接池耗尽或线上影响。修复须另行确认，并覆盖读取失败/取消、任务不存在、正常取消及客户端关闭时序。

## 4. 验证和证据复用

- 管理端初次全套 147 文件、1837 项通过；本域 5 文件、134 项，包含新增 16 项。审查后补强同 16 项中的日期窗口断言，冻结时钟并精确检查对比/安全检查的 30 天范围；最终该文件 16 项、typecheck 和单文件 ESLint 窄复验通过，没有把最终新 SHA 冒称进入初次全套。初次 lint 为 0 错误、138 条既有警告。运行时与构建配置未变，未执行 build。
- 后端已有 13 文件、138 项通过，pytest 7.37 秒，涵盖配置安全、实验/指标、健康和系统任务纯规则。不是完整 Admin HTTP/真实事务/外部服务验收。
- app 项目 CI 忽略集 Ruff、compileall、diff 检查通过；没有修改 Python 文件，无改动文件严格 Ruff 项。
- 1116 运行时路径和固定命令的 473 个测试输入逐项核对不变。固定 CI 8155 项复用 §323，OpenAPI 334 路径复用 §321，均非本轮新跑。原 2246 输入的 2243 项不变、3 项既有固定命令外测试例外沿用先前窄复验证据。
- 一次独立只读审查完成；一项日期窗口断言 P3 已补强并独立窄复验 16 项通过，无剩余 P0–P3。提交及文档/记忆/保护收尾后才进入下一轮。

结果清单记录精确路径、哈希、适用验证和限制；证据目录为 `/tmp/admin-operations-assessment-2026-10-30/`。

## 5. 最终环境出口

真实 Admin 浏览器、JWT/RBAC/审计持久化、PostgreSQL/Redis 事务并发与资源清理、实际模型连通性、定时任务/备份执行及多 worker 行为均未在本轮验收，继续归 ENV-02..05。所有真实环境仍在结构条目全部进入终态后执行；生产验收最后，生产操作另行授权。

下一项 ADM-06：公式、资源与考试管理六页，再 ADM-07、OCR 和共享条目。已确认的既有缺陷继续明确保留，不能写成已经修复。
