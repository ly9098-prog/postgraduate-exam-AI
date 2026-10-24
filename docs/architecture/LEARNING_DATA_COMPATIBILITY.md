# 学习数据域语义与兼容基线

核对日期：2026-10-25。对应重构计划阶段 0；这里只对明确列出的用例给出审查结论，不表示学习数据域或全栈审查全部完成。

推荐实验、学习计划、用户趋势、推荐指标并发和错题编辑缓存的补充基线见 `LEARNING_DECISION_COMPATIBILITY.md`（2026-10-23）。

## 1. 真实入口与消费者

| 用例 | 注册入口和实现 | 当前消费者 | 处理决定 |
| --- | --- | --- | --- |
| 专注开始、暂停、恢复、完成、中断 | `backend/app/api/v1/pomodoro.py` → `services/pomodoro_service.py` | `miniprogram/pages/pomodoro/pomodoro.js` 及该页 recovery/storage 模块 | 保留路由提交事务；service 持有行锁、flush、状态与时间校验。未在本批拆状态机。 |
| 当前专注和统计日设置 | 同上 `/active`、`/settings` | 番茄钟页面、`subpackages/productivity/pomodoro-stats/index.js` | 保留服务端 active 事实、`day_start_minute` 和既有本地恢复队列；不是题库同步。 |
| 当日、趋势、区间和累计专注统计 | 同上 `/stats`、`/trends`、`/daily-summary`、`/range-summary`、`/statistics-overview` → `build_pomodoro_statistics_snapshot` | 番茄钟及统计页 | 本批只抽取无 IO 的科目投影；查询窗口、归属引擎、次数定义和响应组合保留在原调用点。 |
| 统一学习记录 history | 同上 `/history` → `get_history` | 统计页的首屏及日期切换、分页 | 保留三来源 UNION ALL 后统一排序/分页，不改成每来源先截断再拼接。 |
| 用户学习看板 | `api/v1/stats.py` → `stats_service.py` | `pages/home/home.js`、`pages/dashboard/dashboard.js` | 保留 `/dashboard-v2` 与旧 `/dashboard` 回退、可选成长与自适应字段、缓存和 AI 降级；overview、趋势、学科、风险、成长、自适应与年度摘要的纯投影已分离，见第 7 节。 |
| 学习报告 | `api/v1/study_report.py` → `study_report_service.py` | Public API 注册；具体当前客户端消费仍待逐端核对 | 保留独立报告 schema、筛选及状态来源，不因函数同名就与 stats 合并。 |
| 学习计划完成量 | `services/study_plan_service.py` 的 `_today_completion`、`_load_activity_dates` | `/study-plan/overview`，首页消费 | 与番茄钟共用时间归属引擎，但科目范围分配保留现有独立语义，见第 4 节。 |
| Admin dashboard | `/api/admin/v1/dashboard/*` → `admin_dashboard_service.py` | `admin-frontend/src/app/(admin)/dashboard/page.tsx` | 是管理统计和运维指标，使用 Admin client/JWT；不迁入用户学习看板。 |
| 题库同步导入 | `api/v1/sync.py` `/api/v1/sync/import` → `features/sync_merge_service.py` | Admin `sync:write` 权限入口 | 归题库治理/导入域，不归用户专注或学习记录同步。manifest 数量与上限校验、errors rollback、成功 commit 保持。 |

注册以 `backend/app/api/v1/router.py`、`backend/app/api/admin/router.py` 为准。图工具本轮不可用，以上来自当前源码及调用点搜索；未依据索引缺失推断死代码或没有消费者。

## 2. 事务与时间事实

- 番茄钟写路由在 service 返回后 `commit()`；service 的开始路径使用 nested transaction + flush，唯一索引分别约束同一用户的 client_start_id 与一个 active 会话。相同 key 重试先于 active guard，载荷变化报幂等冲突。不能给抽出的规则增加事务操作。
- 暂停、恢复和结束按用户及会话过滤，锁定 `PomodoroSession`；服务端当前时间、显式 client action 时间容差、最后事件时间及暂停区间共同决定有效动作。旧暂停缓存与缺失区间有专门兼容路径，不能以“修复数据”为名在规则抽取中补造区间。
- 统计仅计入 persisted completed/interrupted 专注；running/paused 通过 active 接口展示，不提前累入历史。终态次数归开始统计日，时长按实际活跃区间分摊到各统计日。
- `pomodoro_attribution.py` 是专注/刷题/复习时长拆日及重叠扣除的现有权威实现；统计日由用户 `day_start_minute` 决定，修改后历史即时重算。`stats_service`、`study_report_service` 的今日答题聚合使用北京时间自然日，不等价于可配置专注统计日。
- 刷题及今日复习只补充专注活跃区间未覆盖的时长，不增加顶层番茄次数。科目级 sessions 和 participation_sessions 的含义不同，不能把两者合成一个字段。
- history 按 `start_time DESC, record_type DESC, id DESC` 排序，record_key 包含来源；只有 pomodoro 来源装配 subject_allocations，同 ID 的 practice/review 不能套用其分配。
- history 的逐行响应投影已迁至 `pomodoro_history_projection.py`：pomodoro 无持久化分配时保留单科 10000 权重回退；多分配时保留 `equal_408_core_v1`，单分配/回退为 `single`；非 pomodoro 的 `allocation_mode` 为 `None` 且不得继承同 ID 分配；缺失科目显示“未分类”。UNION ALL 查询、过滤、分页、科目与分配装载仍由 service 持有。

## 3. 本批治理的科目投影

`backend/app/services/pomodoro_subject_projection.py` 承接以下原有纯规则，唯一应用依赖是 `app.core.subject_scope`：

| 规则 | 兼容要求 | 回归证据 |
| --- | --- | --- |
| `resolve_subject` | 无分配快照的旧会话按当前产品科目可用性解析；不可用/孤立科目进入未分类。英语等额外学科的产品可用性不能简化为 `is_active`。 | legacy 可用性、孤立 ID、英语 inactive 用例 |
| `resolve_allocations` | 持久化快照优先，保留名称、ID 和权重；ORM snapshot 字段优先于 lite 字段，即使值为空。复制列表后排序，不能改写输入；四科顺序使用中立 `EXAM408_CORE_CODES`，其他 code 字典序跟随。 | 持久化/lite 快照、原列表未变、空 snapshot 优先 |
| `allocation_group_key` | 删除科目仍按 snapshot code 保持独立身份；无 ID/无 code 才进入未分类键。 | 两个已删除科目不合并，正常 ID 原样保留 |
| `allocate_seconds_by_weight` | 总秒数转整数且不小于0；负权重按0参与；权重总和非正时仍报错，包括总秒为0时。最大余数按输入顺序打破平局，精确保留整数秒总量。 | 整数、小数、负数、空列表、零权重、四科余数 |
| 原 snapshot 调用位置 | 区间统计按每日先分科再累加，不能把区间秒数先加总再分科；两个各1秒的日切片给第一科2秒，与合计2秒后分成1/1不同。 | 实际 `build_pomodoro_statistics_snapshot` 跨日用例，连同开始日计数及一次有界加载断言 |

旧私有 helper 定义已移除，服务直接调用新函数，已有权重测试也直接导入新规则；没有保留转发壳或 `__init__.py` 重导出。服务的开始校验与统计投影共用已有中立四科常量，顺序与旧本地 tuple 完全相同；未修改四科均分方案、数据库权重或产品交互。

## 4. 发现的相似实现为什么暂不合并

`study_plan_service._focus_duration_for_subject_scope` 与统计分科都使用最大余数，但输入和异常语义并不相同：

- 学习计划保留传入 allocation 顺序；统计先规范四科顺序，再对每日秒数做分配。平局余数可能落在不同位置。
- 学习计划分母使用原始转换后权重之和，分子将负值裁为0；统计分母为裁剪后权重之和。合法持久化权重下通常一致，但异常输入并不一致。
- 学习计划遇到非正分母跳过，统计抛 `ValueError`；学习计划保留 seconds 输入，统计先 `int` 并裁非负。

因此本轮不建立通用分配器、不让学习计划反向调用统计 service，也不以重构名义改变异常数据处理。后续如需统一，应先用真实两类消费者刻画上述差异，再决定显式策略参数或独立缺陷修复。

另有两个不能直接合并的报告口径：stats overview 的 accuracy 为0到1并保留4位小数；study report 的 `_safe_accuracy` 为百分数并保留2位小数。待复习聚合也使用不同模型/状态查询，不能用一处总览覆盖另一处契约。

## 5. 可执行基线与剩余工作

第114批先在未改实现上运行新增22项刻画，再迁移实现。已有 `test_pomodoro_subject_allocation.py` 的3项、学习日统计、scheduler、刷题/复习时长、study-plan 保存回归及新架构门禁用于验证实际消费者。命令和最终结果见任务记录第一百二十三节。

架构门禁 `tests/architecture/test_pomodoro_subject_projection_boundaries.py` 约束纯模块依赖、100行文件/50行函数预算、实际 snapshot 接线、无重复定义及新进程导入无配置/数据库/模型/任务副作用；与两份科目规则测试接入原 CI static 步骤。

第115批修复第114批发现的21项旧测试契约缺口，未修改生产代码：

- `test_practice_session_stats.py` 通过真实 revision 创建/最新版本读取与 HMAC 签名提交；不再绕过协议或假设缺失 session 可写答案。验证幂等重放、session/records/outbox 关联、非法请求三表零残留、104/128字符 request_id 原样保存与129/255/263字符拒绝、科目篡改拒绝、显式 answered_count、时长上限和墙钟检查。
- used_time 用例先确认 committed record/outbox 已存在、AnswerBehavior 尚未生成，再调用真实 `project_practice_answer`，分别核对正确/错误题的40/120秒行为记录。异步投影没有被伪装为提交同步副作用。
- fixture 使用规范科目码和真实修订；只在本模块自建临时 SQLite 库中重置全部表，避免无 FK cascade 时复用用户/记录 ID 后残留 outbox、错题或掌握度污染。原时长合并、跨日、重叠扣除和 history 用例保留。
- stats/study-report 的8项失败补齐异步 `db.connection()` 替身，固定北京时间日期，分别以 SQLite/PostgreSQL dialect 编译断言 +8小时分桶、用户/科目过滤和时间窗口；日期字符串与 date 对象结果均有确定断言。
- 另以真实临时 SQLite 执行两个日期聚合服务：`2026-10-21 15:59:59 UTC` 与 `16:00:00 UTC` 分别进入北京时间21日与22日，连续天数、百分数、补零及用户隔离一并验证。PostgreSQL 这里只编译 SQL，不声称已执行真库查询。
- 三份恢复的测试已加入原 CI static 步骤，最终运行结果见任务记录第一百二十四节；不通过 skip/xfail 或放宽业务实现消除旧失败。

仍待治理：

1. 番茄钟 snapshot 仍338行，混合窗口装配、来源归属、维度累计与响应；后续先扩充真实入口的组合/错误/取消契约，再按明确职责拆分。数据库加载与用户/时间范围守卫保持原所有者。
2. 小程序完整 controller、前后台/断网恢复、统计视图派生和 Admin 页面状态仍待逐段治理；本批未改客户端，不声称编译、模拟器或真机已验收。
3. 本地 SQLite 和替身端口不证明 PG 并发或外部 provider；上一轮隔离 PG/Redis 证据覆盖答题链，未覆盖本批专注统计的真库/生产版本。生产仍运行部署时镜像，本批没有重新部署。

## 6. 第一百一十八批：用户统计自然日投影共享边界

- `stats_service` 与 `study_report_service` 原本各自实现 SQLite/PostgreSQL 的北京时间日期 SQL 表达式；另有重复的“北京时间今日零点转 naive UTC”辅助函数。将日期表达式、小时表达式、今日 UTC 起点和 DB 日期值归一化移至 `services/learning_time_projection.py`，两个消费者直接引用实际定义，不留重复函数体或转发实现。
- `shanghai_today` 与 `shanghai_date_utc_range` 仍直接来自 `core.time_utils`，是既有时间事实的权威来源；共享模块没有引入新的时区常量、自然日规则或缓存。
- 保留 stats 连续天数 365 日窗、统计趋势补零及自然日 accuracy 比例；study report 自身 days/subject 筛选和百分比 accuracy 不变。未合并两套复习数据来源、accuracy 格式、专注统计日或学习计划科目分配。
- 新架构门禁检查单向依赖、50 行函数预算、真实消费者指向和新进程无配置/模型/服务副作用。原趋势回归的 SQLite fixture 补齐 schema 当前必填的 `question_version_id`，并同时冻结 `utcnow` 与 `shanghai_today`，只恢复原测试所声称的固定自然日窗口，不更改生产规则。
- 相关 stats/report/trend/真实 SQLite 日期聚合与架构回归共 153 项通过；新增后原 CI static 清单131文件、2,437项通过；readiness 69项、cloud OCR 30项通过。SQLite真查询覆盖跨北京时间零点及用户隔离；PG 查询仅由既有测试编译 SQL，不称真库验收。
- `pomodoro_service.build_pomodoro_statistics_snapshot` 已由第116/117批将窗口规划、响应与两来源累计分离，入口现155行；仍持有设置/请求装载、状态初始化和调用顺序。累计模块仍拥有顶层状态口径，真实 PostgreSQL 专注统计、客户端与生产镜像更新未验证。

## 7. 用户学习看板 v2 投影边界

- `stats_dashboard_projection.py` 只承接无 IO 响应投影；`get_dashboard_v2` 继续持有缓存 key/TTL、数据库查询、`include_growth` / `include_adaptive` / `include_yearly_summary` 开关、异常吞掉后的 `None` 降级和最终响应组装。
- overview 保留今日正确率、错题掌握率的 4 位小数与 0 值边界；trends 保留当前/上一周期相邻且不重叠、整体正确率而非逐日平均、活跃天数和摘要文案；subjects 保留原列表顺序及 `max/min` 的首个平局选择；review risk 保留伪掌握数量与 top topics 前 5。
- growth 分区保留已解锁徽章优先、不足 3 个时按锁定进度降序补足、已解锁超过 3 个时取输入顺序最后 3 个；adaptive 分区保留可见性、状态标签、目标召回率默认 0.8，并由既有 `_adaptive_summary` 生成摘要；yearly 分区保留 365 天活跃天数、总题数、最佳日期后 5 位文本与“暂无记录”回退。
- 可选分区查询失败仍静默降级为 `None`，不把异常传播给整个 dashboard；这不是外部 AI 故障验收，只登记当前兼容行为。缓存命中仍直接返回，不重新计算分区。
- 回归入口：`test_stats_dashboard_projection.py`、`test_trends_previous_period.py`、`test_stats_recommendation_compatibility.py`、`test_dashboard_stats_compatibility.py`。2026-10-25 定向运行 61 项通过；仍不覆盖真实 PostgreSQL、微信页面、生产 Admin 浏览器或外部 AI。

## 8. 学习 AI 诊断与看板 LLM 降级边界

- `stats_ai_projection.py` 只承接 provider 输出净化、LLM 输入 payload、prompt、成功响应投影和规则降级；`stats_service` 继续持有数据库聚合、模型配置解析、一次 provider 调用、42 秒同步超时、900/1000 token 预算、日志和异常边界。
- `get_ai_diagnosis` 的 provider/config/JSON/空结果失败都返回本地数据诊断，不向同步小程序请求抛 500；无最近 60 天错题时直接返回“暂无足够错题数据”。知识点名称必须为字符串，建议非字符串置空，accuracy 大于 1 时按百分数归一并钳制到 0-1。
- `get_dashboard_llm_analysis` 只发送聚合 payload：overview、趋势整体比率、最多 12 个科目、遗忘风险与 top topics 前 5；不发送原始题目、用户身份或凭据。provider 返回必须为 JSON object，summary 截断 320 字符，findings/risks/actions 分别限 6/4/4，空结果回落规则分析。
- 规则降级保持 `model="rule-based"`、`generated=False`，并按“到期复习 → 高频遗忘/长期未掌握 → 薄弱学科 → 保持练习”生成行动；这不是外部 AI 可用性验收，只保证模型/配置/超时失败时响应可用。
- 回归入口：`test_stats_ai_projection.py`、`test_dashboard_stats_compatibility.py`。2026-10-25 定向运行 35 项通过；未调用真实外部模型，不证明生产 AI 超时、网络故障或模型配置数据库行为。
