# Admin 有界消费者映射

2026-10-30；§324，L1 文档盘点。覆盖当前 Git 列出的管理端 src 源码、Next 页面约定及后端 Admin 注册面。映射只建立有限治理范围，不代表结构验收、实际请求轨迹或真实浏览器验收。

## 范围与证据

- 32 个页面入口（含根重定向及路由组外 URL）、275 个非测试 TS/TSX 源文件；包含类型和孤立模块，不能称为全部运行时模块。
- 157 个静态消费契约形状、有限 action 展开后的 211 个调用位置；按方法和路径去重，查询参数与请求体不在本映射的完整校验范围。
- 后端注册 216 个 Admin operation，其中 157 个对应当前静态消费形状；其余 59 个逐项保留归属，不据此判断外部无调用或删除。
- 330 个源文件哈希见[结构化清单](refactor-results/admin-consumer-map-2026-10-30.json)，逐项列出调用位置、可能页面、后端 handler 和 operation ID。
- TypeScript AST 解析错误与未解析本地导入均为 0；可能导入可达仅表示候选归属，不能证明页面实际调用每个接口。

## 有限领域

| 账本 | 页面入口 | 归属契约数 | 下一步退出条件 |
| --- | --- | --- | --- |
| `ADM-01` | `/questions`、`/review` | 17 | 评估职责及兼容证据，DONE／RETAIN／DEFECT／ENV-BLOCKED；映射后仍为 OPEN |
| `ADM-02` | `/imports/batch-image`、`/imports/history`、`/imports/maintenance`、`/imports/questions`、`/imports/review`、`/imports/tasks`、`/imports/text-import` | 31 | 评估职责及兼容证据，DONE／RETAIN／DEFECT／ENV-BLOCKED；映射后仍为 OPEN |
| `ADM-03` | `/coverage`、`/knowledge-graph`、`/subjects`、`/syllabus` | 16 | 评估职责及兼容证据，DONE／RETAIN／DEFECT／ENV-BLOCKED；映射后仍为 OPEN |
| `ADM-04` | `/admin-users`、`/app-users`、`/audit-logs`、`/roles`、`/login`、`/` | 18 | 评估职责及兼容证据，DONE／RETAIN／DEFECT／ENV-BLOCKED；映射后仍为 OPEN |
| `ADM-05` | `/ai-settings`、`/recommendation/experiments`、`/recommendation/metrics`、`/recommendation/reports`、`/recommendation/strategies`、`/system/tasks` | 38 | 评估职责及兼容证据，DONE／RETAIN／DEFECT／ENV-BLOCKED；映射后仍为 OPEN |
| `ADM-06` | `/exams/[id]`、`/exams`、`/formulas/[id]`、`/formulas/categories`、`/formulas/new`、`/formulas` | 32 | 评估职责及兼容证据，DONE／RETAIN／DEFECT／ENV-BLOCKED；映射后仍为 OPEN |
| `ADM-07` | `/dashboard` | 5 | 评估职责及兼容证据，DONE／RETAIN／DEFECT／ENV-BLOCKED；映射后仍为 OPEN |

共享身份壳和跨页导入会产生多页面可能可达；契约按后端职责唯一归属，不按页面重复计数。Admin 导出由 questions 链归 ADM-01；ADM-06 对应实际公式和考试页面。无当前消费的 watermark-rules 归 ADM-02，Redis 运维归 ADM-05；不新增页面或重构批次。

## 动态边界与保留项

- 导入审核 18 个具体注入请求位置经页面 apiRequest 绑定与 hook/request capability 解析，8 个显式注入绑定列于结果。另一个 export 业务回调接收 payload，并非 GET URL；真正导出 POST/blob 已按调用者记录。
- 6 个高层泛型转发／业务委托及 2 个 fetch 传输层不当作独立端点；SSE、blob、有限 action 联合已展开。
- DELETE `/api/admin/v1/formulas/{}/graph-assets/uploaded` 对应后端 `{source_type}` 路由，固定绑定 uploaded；handler 允许 uploaded/template，属于合法消费。
- `src/lib/api/question-types.ts:70` 的 GET `/metadata/question-types` 未发现当前页面导入可达，单列保留，不宣称死代码。
- 58 个资源候选（29 href、24 src、4 window.open、1 form action）未发现额外静态 /api/ 请求；响应生成、签名资源地址留真实浏览器／存储验收。

## 检索、验证与限制

代码图 generation 2026-10-29T17:24:11Z 为 best_effort，417 个模块分页已耗尽；330 路径分三次 coverage 检查已耗尽。coverage/page.tsx 被通用 coverage 排除规则漏索引，另有 TSX 部分行缺口；以有界全源 AST 补足，不能把图结果当完整调用证明。

后端路由 AST 与 §321 的 334-path OpenAPI 快照对应；841 个 backend/app 文件哈希未变，复用该 schema，并非本轮冷进程或服务器验证。运行时、测试和 CI 未改，未重放 typecheck/lint/test/build 或完整 CI；§323 的 473 文件／8155 passed 仅作既有证据，不作为本轮新跑结果。

一次独立只读审查完成，无 P0–P3 遗留；独立核对页面枚举、330 哈希、注册差集、注入中继及 uploaded 允许值；取消有限组合截断的扫描重算结果一致，4287 个原源码／测试／CI 路径未变。实际浏览器、Admin JWT/RBAC、PostgreSQL/Redis、外部 OCR/AI、worker 和生产均未在本轮验收。所有真实环境项目在结构工作结束后执行，生产最后且另行授权。

---

## 相关链接

- [[docs/architecture/SYSTEM_ARCHITECTURE.md|SYSTEM_ARCHITECTURE]] — 系统架构
- [[docs/architecture/PRODUCTION_ARCH.md|PRODUCTION_ARCH]] — 生产架构
- [[docs/architecture/API_ROUTER_STRUCTURE.md|API_ROUTER_STRUCTURE]] — 路由结构
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/admin/ADMIN_ARCHITECTURE.md|ADMIN_ARCHITECTURE]] — 管理端架构
