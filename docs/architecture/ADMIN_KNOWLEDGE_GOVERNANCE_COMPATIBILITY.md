# Admin 知识治理四页兼容说明

> 2026-10-30；§327，ADM-03，L2。覆盖 `/coverage`、`/knowledge-graph`、`/subjects`、`/syllabus` 四个入口及 16 个当前静态消费契约。结论为 `RETAIN`：现有页面编排、纯规则、路由协议和服务 owner 已能承载当前消费者，没有因文件或函数长度继续拆分。本结论是结构评估，不是真实浏览器、PostgreSQL 事务或 Admin JWT/RBAC 验收。

## 1. 契约与边界

| 页面 | 当前静态消费契约 | 保留职责 | 必须保持的行为边界 |
| --- | ---: | --- | --- |
| `/coverage` | 3 | 页面版本/科目/阈值/本地过滤状态；`coverage-utils` 纯规则；`admin_coverage` 协议与权限；`coverage_service` 题库和试卷覆盖投影 | 覆盖率页优先选择 active 版本；草稿阈值输入与应用后阈值分离；非法或不存在的科目选择清空；只有完整四位数年份进入请求；本地关键词/状态不变成服务端过滤。知识点统计基于当前 approved+active 题库映射，历史试卷覆盖基于已发布 paper item 固定的不可变版本知识点快照，不能合并为同一口径。年份范围只约束试卷年份报告，不改写整个题库汇总。 |
| `/knowledge-graph` | 2 | 页面查询/视图状态；`GraphCanvas`/`SubjectOverview` 展示；`knowledge-graph-utils`、`geometry`、`layout` 纯规则；`admin_knowledge.get_knowledge_graph` 有界读投影 | 科目、关系、深度、搜索、中心点共同进入查询身份；搜索草稿与提交词分离并有防抖；总览请求 24 节点，聚焦/搜索请求 36 节点，后端仍保留 120 节点硬上限；全部关系统计与过滤后的可见边并存；边保持 `source -> target` 有向语义，BFS 只做无向取景；当前科目存在活跃知识点时，非法显式中心返回404；活跃知识点集合为空时先返回空图，不进入中心校验。当前页面只读；边创建、推断和状态端点虽无当前静态浏览器请求形状，仍保留。 |
| `/subjects` | 2 | 页面查询与乐观 mutation；`subject-tree-utils` 树关系/展示规则；`admin_subjects` 协议、提交、刷新与缓存失效；`admin_subject_service` 加锁目录变更、审计、路径和状态约束 | 页面使用独立 `subject:write` 权限；启用子科目自动启用非活跃祖先，父科目存在活跃后代时禁止停用；408 产品根停用必须显式确认。乐观更新前取消同域查询并保留精确快照，失败恢复同一快照，`onSettled` 统一失效。服务端继续保持同节点锁、层级最多三级、环检测、唯一编码、408 根/核心身份和路径同步；启停不删除历史题目或学习记录。 |
| `/syllabus` | 11 | 页面六个读作用域、六个 mutation 与目录/映射编辑状态；`syllabus-utils` 目录过滤/分组/成员差异纯规则；`admin_syllabus` 协议、错误映射、审计、提交；`syllabus_service` 生命周期与不可变成员快照 | 编辑页在 draft 可用时优先 draft，active 次之，否则首项；列表页新建后选中新版本并失效全部六类依赖查询。成员 ID 以稳定排序提交。手工映射只允许 `merged/split/replaced`，端点必须是不同版本的知识点成员，不能用同版本或同一 ID。激活时锁版本和 408 根，先将旧 active 归档并 flush，再重建自动映射、激活新版本；手工 merged/split/replaced 保留。active 版本不能直接归档。路由继续负责 404/409/422 映射与关键审计，提交仍由路由层完成。 |

表内是每页去重契约数；跨页共享的版本列表和知识科目列表在整个领域只计一次，因此领域共 16 类。

`ADMIN_CONSUMER_MAP.md` 中的 8 个注册端点没有当前有界静态浏览器请求形状：知识边创建、推断、状态、映射状态，考纲版本 PATCH，科目创建、删除、详情。它们按同域保留，不能据此推断无外部调用或删除。

## 2. 保留理由

- 覆盖面最大的 `coverage_service.build_coverage_report` 虽然较长，但围绕一个报告构建一组有明确顺序和范围的聚合查询；拆成跨事务的多服务会让题库当前状态与试卷历史快照更难核对。现有纯图像引用异常规则已独立、可测。
- 图谱页的几何、布局和通用展示计算已分成三个无状态模块；页面剩余职责是画布交互和请求编排。仅因 `GraphCanvas` 或页面组件行数长继续切分，会新增端口和状态同步面，却没有已登记的具体消费者缺陷。
- 科目服务持有同一目录事务中的锁、祖先修复、路径同步和审计。把乐观回滚或树构建混进后端不会减少职责；页面已有纯 `subject-tree-utils`，只需契约固定。
- 考纲服务持有版本状态机、切换锁、成员替换和自动/手工映射重建。其激活顺序和手工映射保护是事务语义，继续按函数长度拆分反而难以保证行为兼容。

因此 ADM-03 记为 `RETAIN`。没有新增结构缺陷或业务修复；真实浏览器、审计落库、PostgreSQL 并发、Redis 缓存和跨进程环境仍在最终验收表。

## 3. 本轮契约证据

新增 `admin-frontend/src/app/(admin)/syllabus/governance-page-contracts.test.ts`，共 15 项，直接调用四个真实页面函数，以隔离的 hook/query/mutation/request/cache 端口记录请求和状态动作。覆盖：

- coverage 版本选择、版本未选时不请求报告、完整年份与已应用阈值、报告查询键/重试/占位数据；
- graph 无科目时不请求、总览/聚焦/搜索查询键和节点预算、搜索与关系参数；
- syllabus 六作用域、draft 优先、读端点和六个写端点的请求体、创建后失效全部依赖缓存、写失败不触发成功刷新；
- subjects 读写端点、根科目确认字段、取消查询先于乐观更新、祖先联动、精确快照回滚和 settled 失效。

测试只显式执行适用的初始版本选择 effect，不挂载 DOM、不依赖 React 调度、不执行原生 fetch，也不验证画布指针/全屏/导出或 mutation 库的真实调度。`coverage/page.tsx` 被代码图 coverage 目录排除规则漏索引，已直接读取完整源码；新增测试尚未进入当前代码图，结论不依赖其索引状态。

## 4. 验证与复用

- 新增 15 项页面契约通过；管理端全套 145 文件/1803 项、本治理域 7 文件/158 项先通过。独立审查发现取消屏障断言不够强，随后只加强同一用例的 deferred cancel 断言并窄复验该文件15项；未重新跑全管理端。TypeScript 通过，lint 0 错误、138 条既有警告。运行时和 Next 配置未变，未跑 build。
- 受影响后端 3 文件/32 项通过：科目 API、科目服务端口测试、覆盖率图像异常兼容测试。它们不覆盖图谱/考纲完整事务链，不能扩大为全后端验收。
- 1116 个后端/管理端运行时路径与 §326 最终基线相同；固定后端 CI 的 2246 个冻结输入仍为 2244 个原输入不变 + §326 两个已窄复验测试，未新增后端或固定命令输入。因此复用 §323 的 473 文件/8155 项结果，不是本轮新鲜全量 CI。§321 的 334 路径 OpenAPI 快照也因后端运行时未变而复用。
- Ruff（项目CI忽略集）、`compileall` 和 `git diff --check` 通过。一次独立只读审查完成，两项P3（取消等待屏障、空图与404先后限定）均已修正并窄复核关闭，无剩余P0–P3；独立前端15项、后端32项通过。
- 结果清单：[admin-knowledge-governance-retention-2026-10-30.json](refactor-results/admin-knowledge-governance-retention-2026-10-30.json)。

## 5. 未验证与下一步

未验证真实 Admin JWT/RBAC、浏览器 effect/画布交互、PostgreSQL 考纲切换锁与审计持久化、缓存失效、Redis/多进程和外部服务。这些属于 `ENV-02`、`ENV-03`、`ENV-05` 等最终环境阶段，不能以页面替身测试替代。ADM-03 的结构收口不关闭这些环境项。

下一项为 ADM-04（登录、根入口、Admin/App 用户、角色、审计日志）六页身份/RBAC/审计链。生产验收仍固定在全部结构条目终态之后，生产操作另行授权。

---

## 相关链接

- [[docs/architecture/SYSTEM_ARCHITECTURE.md|SYSTEM_ARCHITECTURE]] — 系统架构
- [[docs/architecture/PRODUCTION_ARCH.md|PRODUCTION_ARCH]] — 生产架构
- [[docs/architecture/API_ROUTER_STRUCTURE.md|API_ROUTER_STRUCTURE]] — 路由结构
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/admin/ADMIN_ARCHITECTURE.md|ADMIN_ARCHITECTURE]] — 管理端架构
