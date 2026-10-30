# Admin 仪表盘兼容边界

2026-10-30，§331 / ADM-07。仪表盘单页的 5 个归属消费契约评估为 `RETAIN`；页面同时调用 ADM-05 归属的任务诊断接口，共发起 6 个请求。已有统计服务、页面纯规则与图表组件职责清楚，本轮补充页面契约，保留业务运行时。端点、哈希和验证范围见 [结果清单](refactor-results/admin-dashboard-retention-2026-10-30.json) 及 [Admin 消费者映射](ADMIN_CONSUMER_MAP.md)。

## 范围与停止条件

| 现有 owner | 保留的职责与边界 |
| --- | --- |
| dashboard 页面 | 请求身份门禁、7/30 日选择、刷新状态和展示组合 |
| dashboard-utils 与两个图表组件 | 数字/序列/占比、Redis/任务健康展示规则和图表渲染 |
| admin_dashboard 路由与服务 | 参数/权限/限流、Admin 运营统计、SQL 分组、概览锁和短期缓存 |
| admin_ai_settings_service | 同时聚合生成日志和聊天日志；仪表盘汇总使用最近 7 日，AI 设置页默认汇总保持本月 |
| admin_health | Admin 诊断响应，保留其与基础设施 readiness 的区别 |
| ADM-05 task diagnostics | 共享读取入口及现有观测服务；worker/队列/恢复结构仍归 OCR/SHR |

现有 dashboard service 为 191 行，已集中承载同域读取与缓存，没有确立需要迁移的结构缺陷；不按文件长度拆分页面或共享服务。Admin 用户/题库/导入/审计运营计数保持现有筛选，不能以小程序学习统计的口径替换。

另有 3 个注册端点 `/health/live`、`/health/export`、`/health/export/metrics` 未在有界映射中找到当前浏览器消费形状，均保留；这不证明没有外部调用方。

## 保持的行为

- 六个 query 均使用 `isAuthenticated && !isBootstrapping`；这不代表浏览器细粒度 RBAC 已验收。仪表盘读取要求 `dashboard:read`，任务诊断仍要求 `system:read`。
- daily 的 7/30 日窗口按上海日期包含今天及前 6/29 日；AI 指标始终请求 `days=7`。query key、staleTime 和 health/AI/task 的 retry 设置保持。
- 手动刷新并行调用六个 refetch，使用 `Promise.allSettled` 等待全部结束；单项失败不提前结束 busy 状态，最后清除刷新状态。
- 概览缓存仍使用 `admin:dashboard:overview`、UUID 锁值和 10 秒锁；抢锁失败等待 0.1 秒后重读，未命中再计算；持锁分支缓存 TTL 为 300 秒并抖动，`finally` 释放原锁。
- daily 参数仍拒绝倒置或相差超过 365 天的区间，SQL 按上海日界取数、补齐空日。日期差不超过 31 天时缓存日期序列，序列化/恢复与缓存异常容忍保持；SQLite 和 PostgreSQL 分桶实现不改。
- 题库分组仍按 subject_id/review_status/difficulty 聚合，空分组名为 `unknown`。Admin ready 的数据库失败返回 degraded；数据库成功、Redis 失败仍可返回整体 ok 与 Redis degraded，不更改该既有诊断协议。

## 验证与限制

新增页面测试 9 项直接调用真实 DashboardPage，通过隔离的 hook/query/request 端口检验身份转换、六请求归属/参数、上海跨日窗口、图表 period 回调、刷新等待及 busy 展示。已有 dashboard-utils 40 项继续约束纯规则，共 2 文件 49 项。没有挂载 DOM 或执行 React/TanStack 完整调度，不能当作真实浏览器验收。

本轮管理端全套 149 文件 1865 项、typecheck 通过，lint 0 错误及 138 条既有警告；后端相关 3 文件 34 项通过，使用隔离数据库和替身，不是实际 Redis/PG。app Ruff、compileall 和 diff 检查通过；未改 Python，没有改动文件严格 Ruff 项。未改运行时/构建配置，未执行 build。

核对 §330 已提交描述符，重建的 1117 运行时路径、2248 CI 输入和 330 消费映射源哈希均与当前一致。固定后端 CI 474 文件 8172 项、OpenAPI 334 路径、readiness 69 和 cloud 30 复用 §330 结果，均非本轮新跑；既有固定命令外测试仍沿用其原窄复验证据。新增前端测试的最终 SHA 与本轮全套运行一致。

一次独立只读审查及提交状态以结果清单和交接摘要为准。真实浏览器/JWT/RBAC、PG/Redis 并发、实际 AI 日志、队列与多 worker 仍归 ENV-02..05。Admin 有界结构条目终态不等于全部 Admin 行为验收；已登记的 ADM-08/09 缺陷仍保留。

本轮文档、记忆和保护门禁结束后，下一项为 OCR-02/03 有界消费者映射，再按账本处理 SHR-01..03。所有结构条目处置后才启动真实环境验收，生产验收最后，生产操作另行授权。
