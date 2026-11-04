# 小程序诊断看板请求链兼容边界

2026-10-30，收口账本 `MP-17`，风险 `L2`。消费者为 dashboard 页面，入口为 `GET /api/v1/stats/dashboard-insights`。本批按整条请求链交付，不按七项度量分别开批次；八个输出包含七项度量及 action plan。

## 职责与停止条件

现有 `dashboard_insights_service` 保留 SQL、时区/时钟、查询顺序、异步签名及顶层缓存/并发聚合。纯规则分别归入 quality、topic、speed、balance、action 五个 `dashboard_*_projection.py` 模块，负责评分/稳定性、薄弱与重复错题投影、速度分类、练习结构/投入产出和有序行动建议。模块与函数都符合新增300/50预算。

这五个模块不导入数据库、模型、缓存或服务，日期与序列化能力由 service 提供；纯规则有无需数据库的直接测试。既有 service 中的 SQL 构造和请求聚合保留，不能因为其仍超过300行或个别查询函数超过50行就再开拆分。本批停止于规则可独立测试和请求契约保持；统计消费域整体仍须 `MP-08` 收口检查及全量固定CI。

## 必须保持的行为

- 今日至少5题、每科至少3题等各自阈值、Python round、评分权重、严格大于比较、标签/建议原文和字段顺序保持。缺失用时、重复分组、未来日期及零天直接调用的既有结果不自动归一化。
- 薄弱知识点先读用户知识状态；只有非空时才查询到期复习数，否则用错题绑定的不可变题目版本回退。时间序列化在每个实际非空字段上解析 service 当前函数，保留同一批行之间的替换行为。
- 日期查询保留原下界与未设置上界的行为；方言分支、科目关联、版本关联和参数不变。速度总体分类仍先于科目查询执行；总体与科目分类的20秒/15秒阈值不同。
- 顶层入口保留缓存键、缓存命中对象身份、按 include_topics/include_subjects 选取任务、原顺序及同一 session 的 `gather(return_exceptions=True)`。普通度量异常变为None；CancelledError不属于Exception，仍作为度量结果保留，未改为None。
- 父请求取消继续取消正在等待的度量；缓存读取、overview及action-plan失败继续向外传播。缓存写入TTL120，普通异常忽略，取消继续传播。原动态函数内导入和公共异步入口不变。
- 行动建议仍依次处理到期复习、复发错题、首个薄弱点、新题/复习标签；优先级连续、默认建议与缺字段错误保持。

## 既有缺陷与验收限制

原薄弱点回退查询在当前SQLAlchemy下编译会报 `InvalidRequestError`（多个FROM可作为隐式连接起点）。直接入口契约在原实现与当前实现均确认该结果，SQL表达式未修改；登记 `MP-18 DEFECT`。mock提供查询结果只证明投影行为，不代表真实回退查询执行成功。

2026-10-31 已修复 MP-18：薄弱点回退查询和结构相同的重复错题 Top 知识点查询（`compute_repeat_wrong_analysis`，同样会报 multiple FROMS，原契约测试用 mock 未覆盖）均加 `.select_from(KnowledgePoint)`，连接、过滤、分组和排序不变。新增 `test_dashboard_fallback_topics_db.py`，用真实 sqlite 库执行两条查询（RED 时均抛 `InvalidRequestError`），覆盖冻结 syllabus 名优先于当前名（两条查询均含）、用户隔离、mastered/is_active/未复习过滤，以及计数降序加知识点 id 升序的并列排序；原契约测试从“断言编译失败”改为断言 sqlite/PostgreSQL 方言均可编译。真实 PostgreSQL 执行未验证，归 ENV。

共享 AsyncSession 并发、未来数据包含在下界查询内等原行为仍保留。本批没有修复统计口径、数据库并发、鉴权、schema或客户端展示；隔离FastAPI路由测试使用用户/数据库依赖替身，不代表真实微信/JWT/PostgreSQL验收。

## 验证证据

原始service载入独立模块后运行入口/API契约45项通过；当前实现的8份相关测试与架构门禁111项通过。结构核对（MP-17 时点，早于 MP-18 修复）确认13处SQL执行表达式、11个异步签名以及两个查询辅助函数/顶层聚合器完整AST保持；MP-18 修复后其中薄弱点回退与重复错题 Top 两条查询的 AST 因 `.select_from(KnowledgePoint)` 有意变更，其余不变。一次独立审查指出纯模块门禁遗漏参数传入的数据库操作，已添加execute/commit/flush/rollback/add等检查和负例，该时点业务源码未变，定向18项通过；审查者已窄复核关闭P3，无剩余P0–P3。新测试同步固定CI清单，但本批没有重放全量固定CI，不能据此关闭 `MP-08`。

精确结果、模块预算、源哈希、审查和提交状态见[结果清单](refactor-results/miniprogram-dashboard-insights-2026-10-30.json)。临时 `extract.py` 是源码写入工具，不得作为验证脚本重跑。真实客户端、PostgreSQL/Redis、外部服务和生产验收留到全栈结构重构完成后的最后阶段；本文件不授权生产操作。

---

## 相关链接

- [[docs/architecture/SYSTEM_ARCHITECTURE.md|SYSTEM_ARCHITECTURE]] — 系统架构
- [[docs/architecture/PRODUCTION_ARCH.md|PRODUCTION_ARCH]] — 生产架构
- [[docs/architecture/API_ROUTER_STRUCTURE.md|API_ROUTER_STRUCTURE]] — 路由结构
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/frontend/UI_RULES.md|UI_RULES]] — 小程序 UI 规则
