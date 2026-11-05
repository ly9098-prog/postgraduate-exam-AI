# 小程序复习、统计与学习中心职责核查

> 2026-10-30，HEAD `d91fab53`，账本 `MP-08`。本轮为只读结构评估，不修改业务代码、测试、CI、API 或数据库。范围来自已完成的[消费者映射](MINIPROGRAM_CONSUMER_MAP.md)，不是长文件清理。

## 三条链路的处置

| 链路 | 已确认的职责与证据 | 处置及退出边界 |
| --- | --- | --- |
| 复习：5个当前消费契约 | `review.py`保留用户依赖、请求校验、缓存与HTTP错误；`review_scheduler`拥有版本重绑定、锁/幂等、SM-2、批改、会话记录、概览和掌握状态。现有直接契约与projection边界门禁覆盖这些职责，未发现需要再拆的具体结构问题 | 保留当前结构，不因service仍较长继续拆分；真实PostgreSQL锁、并发和微信闭环仍在最终验收表 |
| 学习中心：`GET study-hub/overview` | 路由为依赖/响应适配；service已有科目范围、查询/候选、章节诊断复用、各任务构建、排序/截断、完成项与plan token职责。overview/recommendation/token直接契约和门禁可独立约束原行为 | 保留当前结构；章节诊断规则已由`MP-07`独立评估为保留，知识地图等消费族仍单列 |
| 统计：8个当前消费契约 | 普通看板、趋势、行为、成长、AI诊断和LLM分析复用既有`stats_service`查询/投影模块；但`GET stats/dashboard-insights`进入另一个未纳入该分层门禁的`dashboard_insights_service` | `MP-08`整体仍OPEN。保留已有统计分层，将已证实的诊断度量职责耦合登记为`MP-17`，完成后回到`MP-08`确认统计链收口 |

保留不表示没有既有业务缺陷，也不将路由缓存、用户身份或事务移入纯模块。原字段、分页、时区、错误/取消、缓存键与TTL、事务所有权全部保持。

## MP-17 的具体问题

真实消费者是 `pages/dashboard/dashboard.js`，后端入口是 `stats.py::get_dashboard_insights`。它经函数内导入调用 `dashboard_insights_service.get_dashboard_insights`，不能只看`stats_service`的既有门禁就认为统计链全部覆盖。

- `compute_weekly_consistency`在同一异步入口中读取SQL、补齐日期、计算离散度/权重/分级并组装响应；这些稳定性规则尚无脱离数据库端口的纯入口。
- 薄弱知识、重复错题、速度/正确率、新题/复习与投入产出等度量也混有查询与派生规则。八个输出包括七项度量和action plan，适合按领域规则聚合，不按函数数目拆成多轮。
- `get_dashboard_insights`持有缓存、按开关构造任务、`gather(return_exceptions=True)`、位置结果读取、overview/action plan和响应。原共享session、异常/取消分类与缓存失败语义属于兼容边界，本轮没有修复或改变。
- 现有`test_stats_service_boundaries.py`约束的是`stats_service`及其查询/部分投影模块，不能作为这些诊断度量已纯化的证据。本轮未定位到该诊断链的专属直接契约，实施前必须先刻画原入口。

下一批以整个诊断看板请求链为一次`L2`交付：先建立八个输出及开关/缓存/失败/取消的语义契约，再抽取职责明确的纯评分/投影模块；service保留原SQL/参数/时间范围与异步请求顺序。新模块≤300行、函数≤50行，复用既有实现，不引入依赖，不顺手修复共享session并发或统计口径。新增测试同步固定CI清单；一次提交前独立审查关闭P0–P3。

## 本轮验证与限制

19个受影响API、service契约及架构门禁文件合跑263项通过。测试覆盖复习版本/状态/重放、统计窗口与投影、学习中心任务选择/排序/完成项/token及相关反例门禁；这个结果不覆盖尚待刻画的诊断看板链，也不代表整个学习业务域已完成。

严格Ruff检查7个现有业务文件时，`review_scheduler.py`报告14项既有F401；7文件与HEAD逐字一致，未自动移除历史导入或扩大忽略名单。按仓库原有CI参数`--ignore I001,F401,N818`检查这些文件通过，应用compileall通过。不能将这组结果写成“严格Ruff全通过”。

精确命令、文件、结果、当前源哈希和问题退出条件集中于[评估结果清单](refactor-results/miniprogram-review-stats-hub-assessment-2026-10-30.json)。本轮不重放全量固定CI；`MP-08`尚未收口。独立只读审查及文档/记忆收尾记录在§315；真实微信、PostgreSQL/Redis、外部服务和生产验收仍留最后阶段。

## MP-08 有限结构收口核查（§317，2026-10-30）

以上§315评估原文保留。本轮基于业务HEAD `05b62b44`，再次核对原消费者表中精确14个MP-08契约：复习5、统计8、学习中心概览1。每个调用站点、候选页面、当前路由及其函数调用清单均登记于[领域收口结果](refactor-results/review-stats-hub-closure-2026-10-30.json)，不把模块可达关系冒充每页真实运行轨迹。46个当前证据源文件及原映射553哈希匹配；原映射本身不覆盖所有service，不能用它证明整个后端未变。

复习/学习中心与统计既有查询、投影、状态与AI边界保留；诊断看板的具体结构缺口由MP-17（`05b62b44`）交付，见 [诊断看板兼容说明](DASHBOARD_INSIGHTS_COMPATIBILITY.md)。不因其余service仍长再开拆分。回退SQL连接歧义以MP-18 DEFECT保留，不把mock投影通过写成真实查询通过；身份/知识地图/考试/番茄钟/AI其余条目继续独立调度，不能据此宣布所有小程序结构完成。

本轮readiness替身69项、cloud profile隔离30项通过，原/现服务冷进程完整OpenAPI334路径一致；按原CI参数的应用Ruff和compileall通过。当前工作流465文件固定静态回归8049项通过（546.56秒墙钟）；这是Static architecture & non-GPU固定清单，不包含所有GitHub Actions作业。2238条应用/测试/CI路径保持本轮前哈希。一次独立审查已核对有限覆盖/源哈希和已有职责，最终CI与收尾元数据已做证据窄复核，P3旧context状态残留已明确为历史并复核关闭，无剩余P0–P3；未重复实现审查或业务测试。MP-08结构范围处置DONE；此处的终结不代表真实环境或既有缺陷已修复。

真实微信/JWT、PostgreSQL/Redis锁/并发/缓存、外部AI/OCR、导出/队列/生产链路仍由ENV-01..06最终验收表承接，状态WAITING-FINAL。生产验收最后，授权边界不变。本轮不修改业务/测试/CI，不新增业务提交；任务和相关文档按既有未暂存边界保留。

---

## 相关链接

- [[docs/architecture/SYSTEM_ARCHITECTURE.md|SYSTEM_ARCHITECTURE]] — 系统架构
- [[docs/architecture/PRODUCTION_ARCH.md|PRODUCTION_ARCH]] — 生产架构
- [[docs/architecture/API_ROUTER_STRUCTURE.md|API_ROUTER_STRUCTURE]] — 路由结构
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/architecture/REVIEW_SYSTEM_DESIGN.md|REVIEW_SYSTEM_DESIGN]] — 复习系统设计
