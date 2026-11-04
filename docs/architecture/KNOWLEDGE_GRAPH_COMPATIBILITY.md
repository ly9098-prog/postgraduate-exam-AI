# 知识图谱与自适应学习兼容基线

核对日期：2026-10-24。对应重构计划阶段 0；范围仅限学生端 408 知识图谱/掌握度地图、轻量知识边、知识点关联与自适应状态，不表示学习域、OCR 导入或全栈阶段 0 完成。

## 1. 入口与消费者

| 用例 | 注册入口和实现 | 当前消费者 | 兼容边界 |
| --- | --- | --- | --- |
| 知识地图总览 | `GET /api/v1/knowledge-map/overview` → `knowledge_map_service.get_overview` | 小程序知识地图 | 只接受活跃 `exam408` 根和四个活跃 canonical 核心科目；无有效范围或活跃考纲时 `scope_ready=false` 且返回空 subjects，不做名称/别名降级。 |
| 科目知识地图 | `GET /api/v1/knowledge-map/subjects/{subject_id}` → `get_subject_map` | 小程序科目地图 | 仅核心科目；父边只选最高优先级 source 且拒绝环；树行排序以考纲快照 `sort_order/name_snapshot` 为准，失败时保持确定性 ID 排序。 |
| 知识点详情 | `GET /api/v1/knowledge-map/points/{id}` → `get_point_detail` | 小程序知识点详情/练习入口 | 知识点必须属于活跃考纲成员；最近答题走 `QuestionVersionKnowledgePoint` 不可变版本映射；练习路由参数对父节点开启 descendants、叶子节点按可练题数封顶。 |
| 知识点掌握状态 | `GET /api/v1/knowledge/states`、`/weak-points` → `mastery_service` | 小程序掌握度/推荐入口 | 状态只来自 `UserKnowledgeState`；可靠度阈值 0.30、weak/developing/good/mastered 阈值不变。 |
| 自适应概览/难题/路径 | `GET /api/v1/adaptive-learning/*` → `adaptive_learning_service` | 学习报告/推荐诊断 | 概览从 profile、knowledge adaptive、difficulty state 聚合；路径阻塞只统计一跳、置信度达标的薄弱前置。 |
| 知识边管理 | `GET/POST /api/admin/v1/knowledge/*` → `knowledge_graph_service`、`knowledge_point_service` | Admin 知识图谱页 | 边创建/upsert 校验同科目、活跃端点和合法 relation；`inferred` 边可 force rebuild，manual/imported/ai 边不受影响。 |
| 知识点关联同步 | 导入/题目编辑 → `knowledge_point_service.sync/replace` | 题库、练习、导出 | 当前题走 `question_knowledge_points`，不可变版本走 `question_version_knowledge_points`；`position` 两阶段更新避免唯一约束瞬时冲突。 |

## 2. 语义与数据边界

- 知识地图是只读投影，不生成第二套掌握度；科目和节点汇总均复用 canonical `UserKnowledgeState`。
- 可练题统计必须同时满足：活跃 canonical 知识点、题目/当前版本活跃、版本类型可答、版本科目与题目一致、审核通过。仅 `QuestionKnowledgePoint` 命中不等于可练。
- 科目汇总是“可靠状态”的置信度加权：`required_reliable=min(3, trainable_count)`。一个高置信薄弱节点足以把科目状态判为 weak；观测不足仍保持 insufficient，不能用单点观测放大为科目结论。
- 父边构造按 source 优先级去重并做 cycle 检测；边列表不做跨科目补全。详情中的 prerequisite/next/related 只展示同一活跃考纲成员，并按 confidence、weight、ID 排序后截断。
- 自适应图上下文是有界 BFS：按 `(node, origin)` 去重，深度/节点数受配置约束；硬阻塞只来自直接、置信度达标的薄弱前置，未知前置只作为软诊断候选。
- 自适应三类状态首次创建统一 savepoint claim + 唯一冲突重载 winner；非唯一数据库错误继续抛出。批量知识点输入先去重，避免同事务重复更新。
- `get_prerequisites` 最多两层、按 depth/weight 排序；`get_next_nodes` 缺失 next 时降级到双向 related。

## 3. 可执行基线

- `backend/tests/test_services/test_knowledge_map_compatibility.py`：真实 SQLite 覆盖无考纲 fail-closed、canonical 408 范围、父边树与状态语义、不可变版本最近答题、练习路由参数和非活跃/范围外知识点 404 语义。
- `backend/tests/test_services/test_knowledge_graph.py`：边创建/upsert/跨科目校验、名称推断、prerequisite/next/related 查询与环防护。
- `backend/tests/test_services/test_adaptive_learning_service.py`、`test_adaptive_learning_concurrency.py`：间隔/难度纯函数、特征开关、图上下文阻塞语义和三类状态 claim/reload。
- `backend/tests/test_services/test_mastery_concurrency.py`、`test_phase2_mastery.py`、`test_knowledge_point_refactor.py`：掌握度更新、知识点归一化/关联、position 约束和版本映射。

## 4. 未完成和未验证

- 知识地图当前测试为 SQLite `Base.metadata.create_all` 服务路径，不等于生产 PostgreSQL 查询计划或大数据量性能验收。
- Admin 知识图谱浏览器的边编辑、force rebuild 和错误提示未做真实浏览器验证。
- 推荐实验/策略管理、指标与质量报告已在 `LEARNING_DECISION_COMPATIBILITY.md` 单独登记，本文件不重复声明其完成。
- 真实微信知识地图页面渲染、真机弱网刷新和外部 OCR/AI 产生的知识点数据质量仍待环境可用后验收。

## 5. 知识地图投影拆分（2026-10-29）

- `knowledge_map_service.py` 从 942 行收敛至 633 行；查询、父边选择、树排序和三个服务入口仍由原模块持有。科目汇总/状态阈值、子树元数据、节点响应分别迁入 `knowledge_map_summary.py`、`knowledge_map_hierarchy.py`、`knowledge_map_nodes.py`，三个模块均不访问数据库，文件 ≤300 行、函数 ≤50 行。
- 保留既有区别：科目汇总把缺失掌握分数的可靠观测按 50 分计算，子树可靠观测则要求分数非空；子树仅对可练节点按题数和置信度加权，可练节点为空时才使用全部可靠观测。未将这两套口径合并。
- 新增 `test_knowledge_map_projections.py` 11 项刻画与 `test_knowledge_map_boundaries.py` 10 项门禁，CI 显式纳入；四个尚未拆分的服务长函数保留各自冻结预算，不表示该模块已完成治理。
- 隔离环境验证：相关图谱/自适应/掌握度/知识点回归共 149 passed；迁移前后 11,250 次确定性投影比较一致，12 个剩余函数完整 AST 不变，5 组真实 SQLite 服务响应及 SQL/参数执行顺序一致。差分脚本与日志位于 `/tmp/knowledge-map-batch/`，临时文件不作为长期回归入口。

## 6. 知识地图查询与详情编排拆分（2026-10-29）

- 继上批投影拆分后，`knowledge_map_service.py` 从 633→195 行，保留 overview/subject/detail 入口与顺序编排。只读 SQL、父边选择/树排序、关系投影、详情标签/响应分别归属 `knowledge_map_queries.py`、`knowledge_map_topology.py`、`knowledge_map_relations.py`、`knowledge_map_detail.py`。8 个知识地图模块均 ≤300 行，全部函数（含嵌套函数）≤50 行。
- 保留查询条件、subject map 的 ID 排序与 detail 的无 ORDER BY 查询；保留父边 source 优先级、成环拒绝、树展示深度上限 8、详情祖先完整深度、关系先舍入后排序/每组截断 8、最近答案不可变版本映射。详情继续先查关系再查最近答案，响应字段顺序与练习参数不变。
- 新增 topology 3 项和 detail 3 项刻画（在拆分前实现上均通过）；架构门禁扩大至 14 项，覆盖全部模块登记、300/50 预算、service 无 SQL、投影依赖和禁止数据库写入。SQLite 比较继续确认 5 组实际响应与 SQL/参数执行顺序一致；独立审查另对 200 组数据 × 3 个入口作 600 次响应、递归字段顺序与 SQL 调用/条件/排序差分，全部一致。
- 仅完成该服务的静态职责收敛；第 4 节列出的 PostgreSQL、真实客户端与外部服务验收限制继续有效。

## 7. MP-13 两条小程序消费链保留评估（2026-10-30，§320）

当前消费者映射精确覆盖知识科目页的 `GET /knowledge-map/subjects/{}` 与详情页的 `GET /knowledge-map/points/{}`；本轮不把历史表中的 overview、mastery 或 adaptive-learning 归属描述当作这两个页面的真实调用证据。overview 路由原样保留，Admin 编辑与其他消费族按各自账本继续核查。

后端现有八个知识地图模块职责已清楚：service 只编排读取，queries 持有只读 SQL，summary/hierarchy/nodes/topology/relations/detail 持有各自规则与投影。service 195 行，全部模块和函数满足已有 300/50 门禁；两个路由继续负责用户身份、参数、404 和响应 schema。客户端科目页已有请求序号及隐藏/卸载守卫、分离的节点/统计/考纲/视图状态辅助函数；详情页已有缓存、在途复用、关系切换序号及归一化辅助函数。决定保留这些现有职责，不按页面长度新增拆分。

新增四项 HTTP/schema 接线契约，在专用 FastAPI app 上覆盖两个消费者的成功序列化、404 和非法整数 422；DB 仅使用已有 `tmp_path` SQLite 夹具，用户依赖也只在该专用 app 上替换。现有服务/投影/拓扑/门禁 36 项与新 HTTP 4 项合计 40 项通过。这不等于真实 JWT/微信或 PostgreSQL 验收。

新增九项实际 Page 请求契约（MP-19 修复后该文件共 17 项，见下）：科目页只发布最新响应、隐藏后不发布、首屏与后台错误分流、练习回执只在直接计数达到预期后清理；详情页在途复用/缓存/强刷与失败重试、父节点子树显示/关系优先去重、卸载后关系切换的迟响应抑制，以及下一段的原有竞态。测试恢复 Page、wx、计时器、API/回执端口及页面 require cache；不访问真实平台、网络或本地用户存储。当前 reliability 步骤 186 条命令的证据由 §319 未变输入的 185 条结果加新增命令 9 项组成，不能表述为新一次全 shell 重跑。

原有竞态单列 `MP-19 DEFECT`：普通 `loadDetail` 不检查关系切换的 `_switchToken`。实际测试先挂起 point1 的普通读取，再完成 `openRelation` 到 point2，最后释放 point1 响应，得到 `knowledgePointId=2`、`data.detail.knowledge_point_id=1`。此项在修复前是既有行为刻画，不将保留评估扩大为“详情页所有迟响应均安全”。

2026-10-31 已修复 MP-19：`loadDetail` 在发起时记录请求的知识点 id，`await` 之后若页面已卸载或 `knowledgePointId` 已变（关系切换已发布），丢弃成功结果和失败分支，不再改写详情或错误态。普通加载、后台刷新、强刷和失败四种时序各有契约用例，另有卸载后的成功/失败不发布、当前 id 仍正常应用与失败提示；原“旧响应覆盖详情”的刻画用例已替换，另固定切换失败后旧 id 加载仍应用、切换期间 retry 的 loading 最终清除。`openRelation` 的 `_switchToken` 逻辑不变。仍以刻画页面端口为证据，没有真实微信交互、弱网或渲染验证，归 ENV。

当前全量固定静态 CI、源码哈希、一次独立审查与提交状态统一见 [本轮结果清单](refactor-results/miniprogram-knowledge-map-retention-2026-10-30.json)。真实微信交互/渲染/弱网、PostgreSQL 查询、跨端状态与生产验收仍在最终环境阶段；生产验收最后，生产操作不由本轮自动授权。

---

## 相关链接

- [[docs/architecture/SYSTEM_ARCHITECTURE.md|SYSTEM_ARCHITECTURE]] — 系统架构
- [[docs/architecture/PRODUCTION_ARCH.md|PRODUCTION_ARCH]] — 生产架构
- [[docs/architecture/API_ROUTER_STRUCTURE.md|API_ROUTER_STRUCTURE]] — 路由结构
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
