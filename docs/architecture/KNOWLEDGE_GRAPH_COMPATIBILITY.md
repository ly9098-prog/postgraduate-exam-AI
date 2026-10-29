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
