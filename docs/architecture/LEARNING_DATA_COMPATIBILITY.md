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

## 9. 学习报告纯投影边界

- `study_report_projection.py` 只承接无 IO 响应投影；`study_report_service.py` 继续持有数据库查询、subject 校验、知识点批量装载、时间窗口和响应编排。本批不修改 API schema、筛选参数、排序、limit 或数据库语义。
- 基础规则保留：accuracy 为百分数并保留 2 位小数、除零返回 0；题目标题取第一个 text 段并截断 100 字符；掌握度先按 confidence `< 0.3` 判 unknown，再按 mastery `< 40 / < 70 / < 85` 分级；复习优先级保留逾期 `>=3` 天、错误 `>=3` 次、box `<=1` 为 high，逾期 `>=1` 天或错误 `>=1` 次为 medium。
- overview 保留今日/近期/累计计数与百分数 accuracy；review plan 保留逾期天数、box、错误/正确次数和知识点首条映射；knowledge mastery 保留 summary 计数、mastery 1 位、confidence 2 位四舍五入及固定建议文案；wrong questions 保留 repeated_wrong > not_mastered > needs_review 的状态优先级。
- Leitner 分布保留固定 0-5 六盒元数据、缺失盒子补零和 tracked 总数；study trend 保留北京时间日期值归一化、请求窗口内缺失日期补零、`wrong_count = total - correct` 及百分数 accuracy。数据库分组查询和自然日窗口仍由 service 持有。
- 回归入口：`test_study_report_projection.py`、`test_study_report_compatibility.py`、`test_study_report_service.py`、`test_study_report_projection_boundaries.py`。2026-10-25 定向运行 78 项通过；仍不覆盖真实 PostgreSQL、微信页面或生产报告链路。

## 10. 学习报告 overview 查询编排拆分

- 2026-10-28，`study_report_service.get_overview` 从 191 行收敛至 47 行，签名、
  参数与响应字段不变。查询与计数按职责抽为 8 个模块级 helper：
  `_practice_counts_query`（50 行）、`_load_practice_counts`（21）、
  `_review_state_count_query`（10）、`_count_review_states`（33）、
  `_wrong_state_count_query`（12）、`_count_wrong_states`（15）、
  `_knowledge_state_count_query`（8）、`_count_knowledge_states`（42）；全部满足
  50 行预算，模块 625 行。
- 保持原有查询语义与顺序：practice 单次聚合（today/recent/total）→ due → overdue →
  wrong_total → repeated_wrong → subject 存在性探测 → weak → unstable → mastered。
  subject 过滤保持“题目表 join 条件”与“知识点 subject_id 条件”两种原写法；阈值保持
  `< 40`、`>= 40 && < 85`、`>= 85` 与 confidence `>= 0.3 / >= 0.5`、
  `next_review_at <= now` / `< now-1d`、`wrong_count > 0` / `>= 3`。subject 不存在时
  仍返回知识点 0 但保留已算出的错题统计；helper 不做写入，模块保持只读（无
  commit/flush/add/delete）。
- 7 项固定契约在拆分前的原实现与拆分后均通过：4 项查询形态/参数契约（SQLite 与
  PostgreSQL 双 dialect 编译，覆盖过滤列、join、阈值参数与调用顺序）与 3 项真实
  SQLite 差分（无 subject、subject 过滤、缺失 subject 三条路径的计数结果）。
  14 个故障变体全部被拒绝，覆盖 today 窗口、practice subject 过滤、today_correct
  取值、due/overdue 参数互换与 join 移除、repeated 阈值、wrong 基础过滤、weak 阈值与
  confidence、mastered 阈值、知识点 subject 过滤、subject 探测反转、recent 窗口与
  调用顺序。
- AST 校验：三个闭包查询构造器与 practice select 在变量改名归一后与原实现一致，
  知识点过滤构造（列表初始化 + append 条件）一致，8 次 `db.execute` 顺序一致；服务
  其余定义不变（`/tmp/study-overview-ast-report.json`）。
- 4 项架构门禁约束 overview 与 helper 的预算、overview 不再内联 select/聚合/标量读取、
  subject 探测先于知识点计数的分支形状、阈值仅在 helper 中单点出现、模块无写入调用，
  并含“阈值泄漏进 overview”“反转 subject 分支”两项反向自检。
- 定向回归：study report overview/服务/兼容/投影与 stats、pomodoro 统计、学习时间
  投影门禁合计 242 passed；严格 Ruff/format、compileall、50 行预算与 diff-check 通过。
- 冻结业务、测试与 CI 清单后，本机按当前 YAML 的静态步骤精确重放 404 个测试文件：
  6926 passed、0 failed、64 条既有弃用 warning，436.54 秒；Mocked readiness
  boundary regression 69 passed；Cloud OCR profile boundary regression 30 passed。
  这是本地清单重放，不代表远端 CI 或生产验收。
- 仍未执行生产操作、真实 PostgreSQL、微信页面或生产报告链路；本批不覆盖
  `study_hub_service`、`adaptive_learning_service` 等学习域其余大函数，也不声称
  学习域整体完成。

## 11. 学习中心 overview 编排拆分

- 2026-10-28，`study_hub_service.get_study_hub_overview` 从 285 行收敛至 50 行，拆除为
  十个小函数：`_scope_not_ready_overview`（29 行）、`_load_study_hub_inputs`（31 行）、
  `_build_review_task`（20 行）、`_build_weakness_task`（37 行）、`_build_hard_task`
  （32 行）、`_build_path_task`（30 行）、`_build_smart_task`（30 行）、
  `_collect_study_hub_tasks`（38 行）、`_finalize_study_hub_tasks`（49 行）、
  `_build_review_summary`（9 行），全部满足 300/50 预算。
- 语义与顺序保持：科目树异常（root 缺失或核心科目数不等于 4）仍返回原失败态字段
  （`scope_ready=False`、`fallback_used=True`、`tasks=[scope-not-ready]` 且
  `primary_task` 与 `tasks[0]` 同对象）；加载顺序保持 review → 408 计数 → 掌握度 →
  `total>0` 才探测章节 → 弱项 → 难题 → 知识路径；`remaining_review` 仍取
  `today_remaining_count`；候选组装保持复习/章节/弱项（与章节同学科则跳过）/难题/
  知识路径（`used_kp_ids` 去重）/智能练习的既有守卫与顺序，配额仍为弱项 8、路径 6、
  智能 10、难题按结果数且 `per_question_sec=120`；收尾保持 task_order 1-6 排序、
  完成项顺延、`[:3]` 槽位、`priority=index`、逐任务签发 plan token（plan_date 用
  ISO 字符串）与 review 汇总五字段。
- 15 项固定契约在拆分前的原实现与拆分后均通过，覆盖科目树异常与核心科目不足回退、
  新用户单任务与免章节探测、复习逾期/窗口两套文案与汇总计数、现有练习才探测章节、
  同学科弱项跳过、弱项两套文案与 allowed repeat、难题有/无错次文案与 question_ids、
  路径同学科点跳过与目标名缺省、完成项顺延后截断编号、仅完成项仍保留在尾部，以及
  加载调用顺序与 core_ids 投影。
- 36 个故障变体全部被拒绝（证据 `/tmp/study-hub-overview-mutants-tdj7ngfx`），覆盖失败态
  标志与任务回显、守卫运算符、章节探测条件、加载顺序与 core_ids、复习任务键/阈值/
  分钟、弱项阈值与配额与 repeat、难题极值/题目集/学科、路径目标名/配额/过滤、
  `used_kp_ids` 过滤、智能模式/键/配额/入参、候选条件、槽位截断、完成标记、优先级、
  token 日期、汇总字段与响应字段。
- 反向展开十个 helper（按 `return` ↔ `tasks.append`、8 元组装载、纯表达式内联等六项
  已记录归一化）后与原实现 AST 一致；模块其余定义不变
  （`/tmp/study-hub-overview-ast-report.json`）。
- 3 项架构门禁（`tests/architecture/test_study_hub_overview_boundaries.py`）约束十个
  函数预算、入口委派顺序与不内联查询、装载器返回元组与入口解包逐项一致、候选守卫、
  文案/配额单点、收尾顺序与优先级循环，含“放宽槽位截断到 4”“交换智能模式三元”
  两项反向自检。
- 定向回归：学习中心/学习计划/学习报告/番茄钟统计/学习时间投影相关契约与门禁合计
  203 passed；`tests/practice/test_batch_issuance.py` 30 passed。严格 Ruff/format、
  compileall、50 行预算与 diff-check 通过。
- 冻结业务、测试与 CI 清单后，本机按当前 YAML 的静态步骤精确重放 408 个测试文件：
  6961 passed、0 failed、64 条既有弃用 warning，449.78 秒；Mocked readiness
  boundary regression 69 passed；Cloud OCR profile boundary regression 30 passed。
  这是本地清单重放，不代表远端 CI 或生产验收。
- 仍未执行生产操作或真实 PostgreSQL 验收；本批不覆盖 `study_hub_service` 其余大函数
  （`_pick_weak_point` 93、`_pick_chapter_recommendation` 92、
  `_pick_path_prerequisite` 73、`_build_subject_mastery` 60）与
  `adaptive_learning_service` 的大函数，也不声称学习域整体完成。

## 12. 学习中心推荐投影拆分

- 2026-10-28，`study_hub_service` 四个推荐投影函数收敛：`_build_subject_mastery` 60 → 13 行、
  `_pick_chapter_recommendation` 92 → 24 行、`_pick_weak_point` 93 → 15 行、
  `_pick_path_prerequisite` 73 → 26 行；拆出 16 个 helper：`_fetch_subject_mastery_rows`（23）、
  `_subject_mastery_entry`（24）、`_rank_practiced_subjects`（21）、`_chapter_task_payload`（39）、
  `_chapter_task_for_subject`（36）、`_weak_point_columns`（15）、`_weak_point_joins`（16）、
  `_weak_point_filters`（18）、`_weak_point_group_by`（13）、`_weak_point_order_by`（9）、
  `_weak_point_statement`（13）、`_weak_point_payload`（14）、`_prerequisite_target_ids`（15）、
  `_rank_blocked_targets`（6）、`_rank_prerequisite_blockers`（9）、`_trainable_prerequisite`（34），
  全部满足 300/50 预算；模块 983 → 1080 行，增量仅为 helper 定义与文档字符串。
- 掌握度投影语义保持：聚合查询仍是 `user_id` + 科目 id 集 + `attempt_count > 0` +
  `GROUP BY subject_id` 且无 ORDER BY；核心科目顺序与逐条投影不变；聚合缺失的科目仍返回
  `mastery_score=None`、`confidence=0.0`、`attempt_count=0`、`accuracy=None`，命中行
  attempts=0 时仍返回 `mastery_score=0.0`、`data_available=False`、`accuracy=None`；
  `mastery_score`/`confidence`/`accuracy` 小数位仍是 1/3/4。
- 章节推荐语义保持：排序仍为 mastery asc（缺失按 100.0）、confidence asc、attempt_count desc、
  subject_id asc，仍只探测 `practiced[:2]` 且逐科目 requery `days=30`；
  `trainable_knowledge_points` 仍 clamp 到 `[3, SMART_TASK_COUNT]`；任务键
  `chapter:{subject}:{kp}`、类型、优先级、文案回退、`route=practice`、`include_descendants=True`、
  `allow_repeat=True`、`estimated_minutes` 与 subject 标签回退（诊断结果优先、其次科目行）不变。
- 弱项投影语义保持：select 列、5 个 join 顺序、14 条过滤、10 列 GROUP BY、
  `HAVING count(distinct(questions.id)) >= 3`、排序（`CASE recent_wrong_count>=2` 优先、
  recent desc、mastery asc、wrong desc、知识点 id asc）与 `limit(1)` + `.first()` 读取不变；
  拆分后渲染出的 SQL 文本与绑定参数（含 `_ANSWERABLE_TYPES` post-compile 列表、
  attempts≥2、mastery<70、`review_status='approved'`、HAVING 阈值、LIMIT）与拆分前逐字节一致。
- 知识路径语义保持：target id 查询（科目作用域、`relation_type='prerequisite'`、`is_active`、
  distinct、id asc）不变；仍只检查阻塞前置最多（同数取 id 更小）的**单个** target，其阻塞项按
  mastery asc、path_quality desc、知识点 id asc 排序，并逐个跳过非核心科目、非法知识点、
  可训练题不足 3 或科目行缺失的候选；全部失败时返回 `None`，不回退下一个 target。
- 21 项固定契约（`tests/test_services/test_study_hub_recommendation_contract.py`）在拆分前原实现与
  拆分后均通过：在原有 18 项基础上补齐“缺失掌握度按 100.0 排名”“诊断标签优先于科目行标签”
  “阻塞项取最低掌握度”三项用例，并给掌握度聚合查询与弱项查询补上绑定参数、join/GROUP BY/
  ORDER BY 顺序断言，避免只断言 SQL 片段造成的弱守卫。
- 1600 例随机差分（`/tmp/study_hub_recommendation_differential.py`，四个投影各 400 例）比较
  payload/异常、渲染 SQL、绑定参数与语句条数：0 mismatch；含 47/79/41 例两侧同样抛出的
  TypeError 边界，失败路径也逐项一致。
- 39 个故障变体全部被拒绝（日志 `/tmp/study-hub-recommendation-mutants.log`，报告
  `/tmp/study-hub-recommendation-mutants-jxvdp7hs/report.json`），覆盖掌握度取整/可用标志/缺失分支/
  列下标/core_ids/过滤阈值/聚合查找，章节排序四键、探测上限、建议守卫、知识点与配额守卫、
  分钟与路由、descendants、标签优先级、优先级与键，弱项 is_active/review_status/attempts 阈值/
  HAVING/分组列/排序顺序/join 顺序/取整/列下标/投影，以及路径 target 排序两键、阻塞项排序两键、
  可训练下限、作用域守卫、top target、科目必查与知识点名来源。
- AST 证明（`/tmp/verify_study_hub_recommendation_ast.py`、报告
  `/tmp/study-hub-recommendation-ast-report.json`）：模块其余 19 个定义与 HEAD AST 完全一致；
  6 个 payload 字典字面量与 47 个比较/排序表达式逐字保留；渲染 SQL 与拆分前逐字节相同。
- 4 项架构门禁（`tests/architecture/test_study_hub_recommendation_boundaries.py`）约束 20 个函数的
  预算、四个入口的签名（overview 装载器与其 mock 依赖该形状）、掌握度/章节/弱项/路径的委派顺序与
  单点语义（阈值与 SQL 子句只出现在 helper 内），并含“放宽章节探测到 3”“反转阻塞项排序”
  “放宽弱项 attempts 阈值”三项反向自检。
- 定向回归：`tests/test_services -k study` 201 passed；
  `tests/architecture -k "study or knowledge_summary or learning_time or smart or practice_projection"`
  59 passed；严格 Ruff、`ruff format --check`、compileall、50 行预算与 `git diff --check` 通过。
- 冻结业务、测试与 CI 清单后，本机按当前 YAML 的静态步骤精确重放 414 个测试文件：
  7027 passed、0 failed、64 条既有弃用 warning，457.12 秒；Mocked readiness
  boundary regression 69 passed；Cloud OCR profile boundary regression 30 passed。
  这是本地清单重放，不代表远端 CI 或生产验收。
- 仍未执行生产操作、真实 PostgreSQL、真实 OCR/AI、微信真机或生产 Admin 浏览器验收；本批不覆盖
  `study_hub_service` 其余函数与 `adaptive_learning_service`、`study_report_service`、
  `review_scheduler`、`wrong_question_service`、任务队列、OCR 导入编排、AI 分析执行等学习域大函数，
  也不声称学习域整体完成。

## 13. 自适应学习服务路径推荐与状态投影拆分

- 2026-10-28，`adaptive_learning_service` 八个入口收敛：
  `get_recommendation_graph_context` 228 → 44 行、`adjust_recommend_weights` 106 → 45 行、
  `get_adaptive_overview` 102 → 31 行、`update_adaptive_state_after_answer` 93 → 44 行、
  `apply_personalized_interval` 91 → 44 行、`update_question_difficulty_state` 89 → 26 行、
  `get_hard_questions` 88 → 12 行、`update_knowledge_interval_factor` 59 → 26 行；拆出 51 个 helper
  （`_load_knowledge_adaptive_states` 13、`_ensure_knowledge_adaptive_states` 15、
  `_adjust_knowledge_interval_state` 26、`_difficulty_delta` 33、`_apply_difficulty_counters` 19、
  `_update_avg_answer_time` 14、`_apply_difficulty_answer` 35、`_log_difficulty_change` 17、
  `_load_question_kp_ids` 10、`_load_user_interval_factor` 7、`_load_knowledge_interval_factor` 21、
  `_load_difficulty_interval_factor` 14、`_load_user_question_state` 13、`_override_next_review_at` 30、
  `_resolve_review_flags` 19、`_update_difficulty_from_answer` 24、`_apply_leitner_interval_override` 11、
  `_update_interval_factors` 27、`_interval_status` 9、`_count_fast_forgetting_points` 9、
  `_count_user_hard_questions` 9、`_count_path_blocked_knowledge` 27、`_weight_status` 25、
  `_hard_questions_statement` 19、`_load_hard_question_labels` 48、`_hard_question_item` 21、
  `_empty_graph_context` 7、`_graph_origin_ids` 3、`_bounded_graph_limits` 5、
  `_graph_edge_conditions` 24、`_fetch_graph_edges` 19、`_graph_relation_payload` 26、
  `_expand_graph_layer` 37、`_collect_graph_relations` 35、`_load_graph_kp_info` 15、
  `_load_graph_mastery` 20、`_graph_relation_item` 36、`_graph_candidate_rank` 7、
  `_graph_current_rank` 7、`_graph_candidate_eligible` 3、`_graph_context` 11、
  `_record_graph_relation` 13、`_keep_graph_candidate` 15、`_project_graph_relations` 29、
  `_graph_scope_ids` 8、`_preference_weights` 3、`_recent_practice_stats` 20、`_recent_due_stats` 20、
  `_weight_adjustments` 31、`_apply_weight_adjustments` 10、`_log_weight_adjustments` 13），
  全部满足 300/50 预算；模块 1352 → 1802 行，增量仅为 helper 定义与文档字符串。
- 图推荐语义保持：origin id 仍按 `dict.fromkeys(int(k) ... if k)` 去重并跳过空值；深度/节点上限仍是
  `max(1, min(int(max_depth or 1), GRAPH_MAX_DEPTH))` 与 `max(1, int(max_nodes or GRAPH_MAX_EXPANSION_NODES))`；
  单层前置边查询仍是“目标 id 集 + `relation_type='prerequisite'` + `is_active`”，给定科目时追加边
  `subject_id` 与两端知识点子查询；分组键仍是 `target_knowledge_point_id`；
  `(node, origin)` 访问集、`max_nodes` 中途截断、`depth_decay`（depth 1 为 1.0，其余 0.65）、
  `normalize_edge_weight`/`_clamp01`、`path_quality` clamp 到 `[0, 1]` 与关系字典键序完全不变。
- 图投影语义保持：知识点名/科目查询仍带 `is_active`，掌握度查询仍是 `user_id` + id 集；缺失知识点整条
  跳过；科目过滤对 prereq 与 origin 双向生效；缺失掌握度仍回退 `(50.0, 0.0)`；
  `confirmed_gap = prereq_conf >= min_confidence and prereq_mastery < min_mastery`、`unknown_gap = prereq_conf < min_confidence`；
  `mastery_score`/`mastery_confidence` 小数位仍是 1/3；硬阻塞仍只取 `depth == 1 and confirmed_gap`；
  候选资格仍是 `confirmed_gap or (depth == 1 and unknown_gap)`；同一前置仍按
  `(1 if confirmed_gap else 0, path_quality, -depth)` 与已存候选比较后择优。
- 间隔语义保持：用户/知识点倍率仍按答错 ×0.92、逾期答对 ×1.08、其余答对 ×1.04 调整，知识点级仍 clamp 到
  `[0.6, 1.6]` 并保留 `round(factor, 4)`、到期计数与逾期错计数；缺失状态仍走
  `_start_explicit_transaction` + savepoint 认领 + 唯一冲突后重读；知识点级更新仍按
  `dict.fromkeys(knowledge_point_ids)` 顺序去重，冲突后仍单次 `flush`。
- 难度校准语义保持：基础 ±4/+8、慢答 +3/+4、快答 −3、逾期答错 +5 与 `> 1.5` / `< 0.6`（含
  `expected_time_seconds > 0` 守卫）逐字不变；计数更新顺序、`overdue_wrong_count` 条件、滑动平均
  `avg*(n-1)+t / n`（n 为自增后的作答数）与 `round(new_score, 1)`、标签阈值（<30/<70）不变。
- 个性化间隔语义保持：profile → 题目知识点 → 知识点倍率 → 难度 → 用户题目状态五段查询顺序不变，
  知识点倍率仍取平均值、无知识点时不再查询、无状态时不写库也不记录日志；写库仍为
  `utcnow() + timedelta(days=final_days)` 且只在存在用户题目状态时执行。
- 难题列表语义保持：仍按 `hard` 标签、个人难度降序、`limit` 截断；知识点名称仍按
  `question_id asc, question_knowledge_points.id asc` 取首行；`next_review_at` 仍经
  `serialize_utc_datetime`；`avg_answer_time_seconds` 为 0 时仍返回 `None`，分数仍保留 1 位小数。
- 概览与权重语义保持：状态标签阈值仍是 0.9 / 0.98 / 1.1；回忆率仍 `round(..., 3)`；快速遗忘计数与
  个人难题计数查询不变；路径阻塞计数与权重摘要仍为 best-effort（异常回落 0 / 未调整）；权重微调仍是
  “到期正确率 <0.6 且 ≥3 → +1、≥0.85 且 ≥5 → −1、近期正确率 <0.5 → weakness +1、
  近期答题数 <10 → 新题 +1、>30 → −1”，步长 0.05、clamp `[0.7, 1.3]`，字段导出顺序仍是 `_WEIGHT_FIELDS`。
- 答题入口语义保持：`ADAPTIVE_LEARNING_ENABLED` 关闭时不查询；`is_due_review`/`is_overdue_review`
  仍只在未显式传入时按 `next_review_at` 回退计算（`>= nra` / `>= nra + 1 天`）；用户倍率与知识点倍率仍只在
  `ADAPTIVE_INTERVAL_ENABLED and is_due_review` 时更新；难度仍按 `Question.difficulty or 3` 估算期望时间；
  覆盖仍只在 `not ADAPTIVE_DRY_RUN and uqs is not None` 时按 `LEITNER_INTERVAL_DAYS.get(box_level, 1)` 执行。
- 134 项固定契约（`tests/test_services/test_adaptive_learning_projection_contract.py`）在拆分后与拆分前均可通过
  （HEAD 原实现经 AST 提取后以 pytest 插件回放：134 passed），覆盖阈值边界（0.89/0.9/0.98/1.1、置信度
  等于阈值、`due_count` 4/5、`recent_count` 9/10/30/31）、小数位（1/3/4）、clamp、守卫取反、
  查询语句文本与绑定参数、访问器用法（`scalars().all()` vs `scalar_one_or_none()`）、
  认领/冲突/重读路径、dry-run 与显式标志优先级，以及 `_start_explicit_transaction` 事务门禁。
- 5600 例随机差分（`/tmp/adapt-batch/differential.py`，八个入口各 700 例）比较返回值/异常、渲染 SQL 与
  绑定参数序列、结果访问器序列、`flush`/`add`/`begin_nested` 事件、日志调用、子函数间谍调用序列与全部状态
  快照：0 mismatch、0 harness gap。差分覆盖被稀疏与稠密图、环、`max_nodes` 截断、科目作用域、缺失行、
  显式与回退标志、`<5` 条记录、认领冲突与 `ADAPTIVE_DRY_RUN` 组合。
- 99 个故障变体全部被拒绝（日志 `/tmp/adapt-batch/mutants.log`），每个变体仅作用于单个函数，覆盖图遍历
  （深度/节点上限、访问集、截断、子查询作用域、掌握度元组顺序、`path_quality` clamp、候选排序/资格/阻塞深度）、
  概览阈值与摘要、难题排序/首行/取整/零耗时、权重阈值与双向调整、知识点倍率与事务门禁、难度增量与比值、
  个性化间隔默认值、Leitner 默认盒间隔与标志矩阵。
- AST 证明（`/tmp/adapt-batch/verify_ast.py`、报告 `/tmp/adapt-batch/ast-report.json`）：模块 23 个未触及定义
  与 HEAD AST 完全一致，模块级语句（导入与常量）逐字一致；八入口消失的表达式仅 15 个属性链、2 个字符串常量
  与 6 个比较表达式，全部为并入共享 helper（去重）、局部变量改名（`r` → `row`、`q` → 语句构造 helper）或
  守卫取反（`is not None` → `is None: return`），无未解释差异。
- 6 项架构门禁（`tests/architecture/test_adaptive_learning_projection_boundaries.py`）约束 59 个函数的
  预算、八个入口的签名与默认值、委派顺序、冻结的单行语义（图上限、候选排序/资格、状态标签）、
  阈值与 SQL 单点，并含“放宽图深度上限”“反转记录顺序”“放宽权重/难度阈值”“在入口内联 SQL”
  四项反向自检。
- 定向回归：`tests/test_services -k "adaptive or smart or scored or leitner or study or report or review_scheduler"`
  与 `tests/architecture -k "adaptive or smart or scored or leitner or study or learning or dependency"`
  合计 661 passed；严格 Ruff、`ruff format --check`、compileall、50 行预算与 `git diff --check` 通过。
- 冻结业务、测试与 CI 清单后，本机按当前 YAML 的静态步骤精确重放 416 个测试文件：
  7167 passed、0 failed、64 条既有弃用 warning，454.15 秒；Mocked readiness boundary regression 69 passed；
  Cloud OCR profile boundary regression 30 passed。这是本地清单重放，不代表远端 CI 或生产验收。
- 仍未执行生产操作、真实 PostgreSQL、真实 OCR/AI、微信真机或生产 Admin 浏览器验收；本批只覆盖
  `adaptive_learning_service`，不覆盖 `study_report_service`、`review_scheduler`、
  `wrong_question_service`、任务队列、OCR 导入编排、AI 分析执行等学习域大函数，也不声称学习域整体完成。

## 14. 错题本服务投影与批量操作拆分

- 2026-10-28，`wrong_question_service` 五个入口收敛：`record_wrong` 65 → 39 行、`get_stats` 111 → 23 行、
  `list_wrong_enriched` 196 → 44 行、`batch_operate` 195 → 46 行、`get_task_flow` 115 → 37 行；拆出 37 个 helper
  （`_wrong_list_item` 38、`_load_all_task_flow_items` 35、`_wrong_stats_summary_statement` 31、
  `_batch_set_mastered_state` 31、`_batch_remove_from_book` 29、`_rebind_wrong_review_schedule` 25、
  `_batch_delete_wrong_questions` 25、`_today_due_statement_conditions` 24、`_wrong_mastery_pct_subquery` 24、
  `_reactivate_existing_wrong_question` 21、`_task_flow_bucket` 20、`_wrong_stats_by_subject` 19、
  `_wrong_list_base_query` 19、`_add_wrong_question_to_review` 18、`_force_schedule_due_now` 17、
  `_task_flow_summary` 17、`_apply_wrong_topic_scope` 15、`_load_batch_wrong_questions` 15、
  `_new_wrong_question` 14、`_batch_add_to_review` 14、`_wrong_next_review_subquery` 13、
  `_wrong_list_optional_conditions` 13、`_wrong_stats_summary` 11、`_wrong_last_reviewed_subquery` 11、
  `_reactivate_wrong_question_row` 11、`_load_wrong_question` 10、`_wrong_book_conditions` 10、
  `_task_flow_groups` 10、`_today_due_wrong_question_count` 9、`_wrong_review_record_count_subquery` 9、
  `_empty_batch_result` 9、`_wrong_mastery_percent` 8、`_wrong_stats_by_error_type` 7、
  `_ordered_batch_wrong_questions` 7、`_dedupe_batch_ids` 5、`_apply_wrong_subject_scope` 3、
  `_wrong_ai_analysis_status` 2），全部满足 300/50 预算；模块 772 → 963 行，`get_by_id`、`update_wrong`
  与全部 15 条模块级语句逐字未动，新增 4 条任务流常量。
- 错题记录语义保持：仍先取 user+question 事务锁再查行；软删除/已掌握行仍复用同一行并清空 `ai_analysis`、
  更新 `wrong_answer`/`question_version_id`、`review_count+1`、`last_review_at`，并再次清零 mastered 状态；
  新行仍是 `review_count=1`；仍调用 `auto_schedule_wrong_question(..., commit=commit)`，`commit=False` 时
  补 `flush` 后 `refresh` 返回。
- 统计语义保持：仍是一次覆盖索引聚合（total/unmastered/mastered/high_frequency `review_count >= 3`）+
  错误类型分组 + 当前题库科目分组（join `questions`/`subjects`）+ today_due 去重计数；today_due 仍是
  ReviewSchedule 侧 `is_active`、`~mastered`、`next_review_at <= 今日结束` 且 question 落在本人生效错题本内的
  子查询，给定科目时追加同一题目科目子查询；缺失值仍回落 0，返回键序不变。
- 列表语义保持：过滤条件（本人 + 生效 + 可选科目/错误类型/中国日历半开区间）与四个关联子查询逐字保留——
  复习记录数按历史 `question_version_id` 计数，下一次/最近复习时间分别按升/降序取一行，掌握度仍按
  `mastered → 1.00`、`repetitions >= 5/4/3/2/1 → 1.00/0.90/0.80/0.65/0.45`、否则 0.20；仍以可变的当前
  `Question`/`Subject` 外连接展示、按 `updated_at desc, id desc` 稳定分页，先计数后 offset/limit，
  知识点仍按当前题目 id 集合批量加载；`mastery_percent` 仍以 `WrongQuestion.mastered` 为最终态优先，
  `ai_analysis_status` 仍只对非空 dict 返回 `ready`。
- 批量操作语义保持：先按出现顺序去重（`seen`/`seen.add`），空列表仍返回 `success=False` 且不触库；
  仍单次按 `id.in_(deduped_ids)` + `user_id` 取行，not_found 在动作处理后才并入 `skipped_ids`；
  仍按 `(question_id, wq_id)` 排序执行以避免交叉批次死锁；`add_to_review` 仍逐条 savepoint 并吞掉异常，
  重新激活行、按版本重绑 schedule（`commit=False`）、把未来到期压到 now 并在未重绑时 `occurrence_seq+1`；
  `mark_mastered`/`unmark_mastered` 仍跳过非生效行且无 savepoint；`remove_from_book` 仍先取锁、跳过非生效行、
  置 `is_active=False`/`removed_at=now` 并停用 schedule、`occurrence_seq+1`；`delete` 仍先取锁再依次删除
  ReviewRecord → ReviewSchedule → WrongQuestion；未知 action 仍不处理条目但照常提交并返回成功；
  仍单次 `await db.commit()`，响应键与计数语义不变。
- 任务流语义保持：仍按 500/页循环调用 `list_wrong_enriched` 直到取满 total 或空页，分组仍是
  today_due（`next_review_at <= 今日结束` 且未掌握）→ 高频（`wrong_count >= 3` 且未掌握）→ 最近新增
  （`created_at` 在 14 天内且未掌握）→ 待巩固 → 已掌握的优先级去重链；五组键、标题、`items[:preview_size]`
  与 summary 的四个非互斥计数（total/mastered/high_frequency/today_due）不变。
- 34 项固定契约（`tests/test_services/test_wrong_question_service_contract.py`）在拆分后与拆分前均可通过
  （HEAD 原实现经 AST 提取后以 pytest 插件回放：34 passed），覆盖优先级链边界（`next_review_at` 等于今日结束、
  `wrong_count` 等于 3、14 天窗口含等值）、掌握度换算与四位小数、savepoint 逐条隔离与异常吞咽、
  版本重绑与 `occurrence_seq` 递增规则、批量锁顺序、删除三段语句顺序、not_found 追加顺序、
  分页参数与全部过滤 SQL 片段。
- 3500 例随机差分（`/tmp/wq-batch/differential.py`，五个入口各 700 例）比较返回值/异常、渲染 SQL 与绑定参数序列、
  访问器序列、`flush`/`add`/`commit`/`begin_nested` 事件、review_scheduler 间谍调用、分页调用参数与全部状态快照：
  0 mismatch、0 harness gap。
- 97 个故障变体全部被拒绝（日志 `/tmp/wq-batch/mutants.log`），每个变体仅作用于单个函数，覆盖错题重录字段、
  统计聚合标志位/阈值/列序、四个关联子查询与日期边界、批量去重/排序/守卫/savepoint/异常吞咽/锁顺序/
  三段删除、任务流阈值/窗口/分页/优先级链/预览与摘要。
- AST 证明（`/tmp/wq-batch/verify_ast.py`、报告 `/tmp/wq-batch/ast-report.json`）：未触及的 `get_by_id`、
  `update_wrong` 与 HEAD AST 完全一致；模块级语句 15/15 逐字保留并新增 4 条任务流常量；五个入口消失的
  29 个表达式全部解释（4 个去重缺口 + 25 个并入 helper/命名常量的显式白名单），无未解释差异。
- 8 项架构门禁（`tests/architecture/test_wrong_question_projection_boundaries.py`）约束 42 个函数的预算、
  五个入口签名与默认值、委派顺序、冻结的单行语义（去重/排序/重激活/到期压平/任务流分桶与摘要）、
  阈值与 SQL 单点，并含“放宽任务流阈值”“颠倒 commit 与 not_found 合并”“入口内联 SQL”
  “移除 remove 生效守卫”“改为互斥摘要”五项反向自检。
- 定向回归：`test_wrong_question_batch`、`test_wrong_question_date_filter`、`test_wrong_question_service`、
  `test_wrong_question_compatibility` 与两个新文件合计 99 passed；严格 Ruff、`ruff format --check`、
  compileall 与 `git diff --check` 通过。
- 冻结业务、测试与 CI 清单后，本机按当前 YAML 的静态步骤精确重放 418 个测试文件：7209 passed、0 failed、64 条既有弃用 warning，508.26 秒；Mocked readiness boundary regression 69 passed；Cloud OCR profile boundary regression 30 passed；
  这是本地清单重放，不代表远端 CI 或生产验收。
- 仍未执行生产操作、真实 PostgreSQL、真实 OCR/AI、微信真机或生产 Admin 浏览器验收；本批只覆盖
  `wrong_question_service`，不覆盖 `review_scheduler`、`study_report_service`、任务队列、OCR 导入编排、
  AI 分析执行等学习域大函数，也不声称学习域整体完成。


## 15. 复习调度服务（review_scheduler）入口拆分

- 2026-10-28，`review_scheduler` 十一个超预算入口收敛：`grade_batch_review` 192 → 44 行、
  `submit_review` 164 → 41 行、`_get_today_review_task_state` 149 → 50 行、`get_review_stats` 135 → 33 行、
  `get_today_review_result` 115 → 45 行、`_prepare_latest_review_revisions` 88 → 50 行、
  `_record_review_session` 83 → 31 行、`set_mastered_state` 75 → 49 行、`get_today_review_overview` 66 → 47 行、
  `get_today_review` 65 → 23 行、`auto_schedule_wrong_question` 60 → 36 行；拆出 65 个 helper
  （按行数降序）：
  `_apply_review_grade` 41、`_today_mastered_schedules` 35
  `_lock_and_rebind_latest_revision` 34、`_review_submit_payload` 34
  `_today_result_subject_stats` 34、`_today_review_batch_metrics` 32
  `_build_review_record` 31、`_batch_review_error_payload` 30
  `_grade_batch_review_item` 30、`_add_review_session_rows` 28
  `_batch_review_success_payload` 28、`_grade_batch_review_loop` 28
  `_resolve_review_replay` 27、`_restore_review_schedule` 27
  `_review_schedule_subject_rows` 26、`_load_locked_review_schedule` 24
  `_prewarm_review_wrong_answers` 24、`_batch_review_missing_payload` 23
  `_review_replay_payload` 23、`_maybe_update_user_question_state` 22
  `_today_result_records` 22、`_reviewed_by_subject_today` 21
  `_today_due_review_statement` 21、`_new_wrong_review_schedule` 20
  `_review_stats_by_subject` 20、`_today_reviewed_schedules` 20
  `_rebind_if_stale` 19、`_validate_review_replay` 19
  `_apply_manual_mastery_to_schedule` 18、`_apply_sm2_update` 18
  `_reset_wrong_review_schedule` 18、`_review_accuracy_since` 17
  `_today_reviewed_context` 17、`_review_session_subject_map` 16
  `_count_today_review_schedules` 15、`_review_session_stats_by_subject` 15
  `_apply_manual_mastery_to_wrong_question` 14
  `_load_today_review_schedules` 14、`_merge_today_task_schedules` 14
  `_today_mastered_question_ids` 14、`_tomorrow_due_count` 14
  `_batch_review_question_answer` 13、`_today_completion_metrics` 11
  `_today_result_metrics` 11、`_today_review_overdue_split` 11
  `_today_reviewed_rows` 11、`_dedupe_records_by_question` 10
  `_latest_revision_candidates` 10、`_ordered_review_items` 10
  `_review_session_already_recorded` 10、`_today_review_conditions` 10
  `_count_reviews_between` 9、`_latest_revision_view` 9
  `_log_missing_review_revision` 9、`_pending_today_schedules` 9
  `_subject_code_names` 9、`_batch_review_prewarm_candidate` 8
  `_count_overdue_reviews` 8、`_count_remaining_today` 8
  `_load_wrong_question_revision` 8、`_toggle_schedule_mastery` 8
  `_count_active_review_schedules` 5、`_today_due_review_schedules` 5
  `_valid_revision_schedule_filters` 5、`_first_wrong_review_at` 3
  全部满足 300/50 预算；模块 1653 → 2197 行，顶层定义 25 → 90；`get_review_history`、`mark_mastered`、
  `unmark_mastered`、`get_next_today_review_batch`、`_normalize_review_session`、
  `_allocate_review_session_duration` 等 14 个未触及函数逐字未动。
- 提交语义保持：评分范围校验仍在取锁之前；仍先 `lock_review_request` 再 `lock_question_review_state`；
  幂等重放仍在任何可变 schedule 读取之前解析，重放键仍是 `question_id`/`question_version_id`/`schedule_id`/
  `occurrence_seq`/`rating`/`user_answer` 全字段相等，冲突时仍抛
  `ValueError("复习 request_id 已用于不同提交")`，重放成功仍返回 `already_submitted=True` 且不触库；
  锁行后的六类校验（不存在并带 schedule_id、题目不匹配、已移出队列、已标记掌握、版本已更新、
  occurrence 已失效）文案与顺序不变，读取仍带 `with_for_update()`；SM-2 仍由 `calc_sm2`
  （`rating`→quality、`efactor`/`interval`/`repetitions`/`review_date`）驱动并写回
  `ease_factor`/`interval`/`repetitions`/`next_review_at`/`last_reviewed_at`；`is_correct` 仍是
  `rating >= 3`、自动掌握仍是 `is_correct and review_auto_mastered(repetitions)`；仍只在
  `latest_version_id == question_version_id` 时调用 `update_user_question_state_after_answer`；
  仍构造同字段 `ReviewRecord` 并把 `occurrence_seq+1`；`auto_commit=False` 时仍不提交不 refresh，
  提交时仍 `commit` + `refresh(schedule)`；返回键序不变，`wrong_question_id`/`wrong_review_count`/
  `wrong_answer` 仍只在答错且同步到错题行时出现。
- 批量批改语义保持：空列表仍抛 `ValueError("复习列表不能为空")`；仍先一次性预载不可变版本视图，再按
  `(question_id, schedule_id, 原始下标)` 稳定排序逐条批改以规避交叉批次死锁；每条仍以
  `auto_commit=False` 调 `submit_review`，仍只把 `ValueError` 转为条目错误载荷；版本缺失仍走
  `REVIEW_VERSION_MISSING` 载荷而非错误载荷；批改后仍单次 `commit`，再做 AI 预热，最后按原下标还原
  结果顺序并写复习时段；`total`/`correct_count`/`wrong_count` 仍只统计成功条目，错误条目仍携带
  `error_code`/`retryable`/`refresh_required`/`correct_answer`/`rating`。
- 统计语义保持：仍是四路去重计数（生效 schedule 数、今日 review 数、今日剩余
  `next_review_at <= 今日结束` 且未掌握、逾期 `next_review_at < 今日开始` 且未掌握）+ 近 N 天准确率
  （`rating >= 3` 记正确、四位小数）+ 科目维度（schedule 侧按可变 `subject_id` 分组、复习历史按不可变
  revision 科目分组），缺失值仍回落 0 与空字符串，返回键序不变。
- 今日任务语义保持：`_get_today_review_task_state` 仍是「当前到期 ∪ 今日已产生 review 记录的 schedule ∪
  今日已手动掌握的 schedule」合并视图，仍排除
  `question_versions.question_id != review_schedules.question_id` 的脏行，仍按
  `(next_review_at or 今日结束, id)` 升序排序，仍以 `(已复习题目 ∪ 已掌握题目) ∩ 任务题目` 计算已完成集合，
  未完成集合仍要求未掌握；入口页与结果页仍由该状态派生，`is_completed` 与完成率仍由同一纯函数给出
  （本批把入口页内联的 `max(0, due - remaining)` 与 `is_completed` 表达式收敛到 `_today_completion_metrics`，
  两者在模块内各只剩 1 处）；结果页仍按题目去重取最新一条 review，明日到期数仍是
  `[tomorrow_start, tomorrow_end]` 区间，入口页仍用 10 条批量与 120 分钟上限。
- 复习时段语义保持：`_normalize_review_session` 未改动（request_id 必填、时长必须 > 0、完成时间不得
  超前 now + 容差、起点早于终点或超出上限时按 duration 回推、前台时长大于墙钟时扩展起点）；
  `_record_review_session` 仍是尽力而为边界——窗口为空或无成功条目直接返回，同一 client segment
  重复写入仍是 no-op，时长仍按成功条目数在最大组优先分配余数，异常仍只 `rollback` + `logger.warning`，
  不抛出，不影响已提交的 SM-2 进度。
- 掌握与到期重建语义保持：`set_mastered_state` 仍先取题目锁，再分别读错题行与 schedule；已是目标态仍
  返回 `False`（元数据修复不算用户可见转换），`mastered_at` 仍只在本次请求真正造成转换且原来为空时打点；
  schedule 侧仍是同态返回 `False`、异态切换并 `occurrence_seq+1`、缺行时仅在取消掌握且错题行仍生效
  且有版本时重建；`auto_schedule_wrong_question` 仍先取锁、校验 revision 归属，按「错题首次复习 = 明日」
  建新行（interval=1、ease_factor=2.5、repetitions=0、occurrence_seq=0）或重置既有行并
  `occurrence_seq+1`，`commit=False` 仍只 `flush`。
- 63 项固定契约（`tests/test_services/test_review_scheduler_projection_contract.py`）在拆分后与拆分前均可通过
  （HEAD 原实现经 AST 提取后以 pytest 插件回放：63 passed），覆盖 SM-2 应用与掌握投影、幂等重放六字段
  逐项冲突、重放载荷默认值与标志位、六类 schedule 校验错误文案、`rating=2` 判负、错题行回显规则、
  锁行/提交/refresh 顺序、批改排序与三类载荷字段、统计四路计数与科目回落、今日任务合并与分页指标上限、
  时段归一化与余数分配、掌握转换与重建守卫。
- 7700 例随机差分（`/tmp/rs-batch/differential.py`，十一个入口各 700 例）比较返回值/异常、渲染 SQL 与绑定
  参数序列、访问器序列、`commit`/`flush`/`rollback`/`refresh`/`add` 事件、日志、错题同步与 AI 预热间谍调用
  以及全部状态快照：0 mismatch、0 harness gap、0 dead queue（22 个响应队列均被真实消费）。该差分工具
  在本批中同步修正四处自身缺陷：`count(distinct(...))` 分类里 `<=`/`>=`/`<` 的优先级与 GROUP BY 行集被聚合
  形状遮蔽、结果对象改为按访问器惰性取响应、每个入口的用例桩未在用例结束后还原（导致后续用例复用首个
  用例的闭包）、以及把同步的 `_normalize_review_session` 用异步桩替换从而静默走异常分支。
- 137 个故障变体全部被拒绝（日志 `/tmp/rs-batch/mutants.log`），每个变体仅作用于单个函数，覆盖 SM-2 字段
  写回、正确性阈值与掌握判定、幂等键各字段与默认值、锁行与 `with_for_update`、用户题目状态镜像条件与
  排序、批改排序/提交契约/载荷字段/异常边界/预热筛选、统计四路窗口与分组列、今日任务合并与脏行守卫、
  入口页与结果页指标边界、时段上限与余数分配、掌握转换/修复/重建守卫、脏版本重建与提交条件；另有 5 个
  变体经论证为观测等价（同一 patched 瞬时、`due > 0` 时批量上限恒 ≥ 1 的两处、失败载荷 `is_correct`
  恒为 `False` 使 success 门不可观测、每条 review 恰好产出一个结果使 `len(results) == len(reviews)`），
  单独登记在 `EQUIVALENT` 中而非计入幸存者。
- AST 证明（`/tmp/rs-batch/verify_ast.py`、报告 `/tmp/rs-batch/ast-report.json`）：14 个未触及函数与 HEAD AST
  完全一致（0 differing、0 old-only）；模块级语句 31/31 逐字保留、0 新增；十一个入口消失的 37 个表达式
  全部解释（0 去重缺口 + 37 条并入 helper/重命名局部量/重写 docstring 的显式白名单），无未解释差异。
- 8 项架构门禁（`tests/architecture/test_review_scheduler_projection_boundaries.py`）约束 76 个函数的预算、
  十一个入口签名与默认值、委派顺序、15 个纯 helper 的冻结单行语义、SM-2/记录构造/复习时段边界的单点归属，
  以及今日/逾期/明日窗口与统计窗口 SQL 的单点，并含「放宽 helper 预算」「把重放查询移到锁行读取之后」
  「入口内联 SQL」「丢失复习时段尽力而为边界」「颠倒明日窗口比较」五项反向自检。
- 定向回归：新增两文件合计 71 passed；既有 `test_review_scheduler`、`test_review_scheduler_service`、
  `test_review_scheduler_compatibility`、`test_review_session_stats`、`test_review_overview_dirty_schedule`
  加 `test_e2e_review_flow`、`test_review_service`、`test_phase2_mastery`、`test_review_api`、
  `test_review_master_api`、`test_practice_service`、`test_recommendation_phase4` 合计 247 passed；
  严格 Ruff 与模块 50 行预算扫描通过。
- 冻结业务、测试与 CI 清单后，本机按当前 YAML 的静态步骤精确重放 420 个测试文件：7280 passed、0 failed、
  64 条既有弃用 warning，422.94 秒；Mocked readiness boundary regression 69 passed；
  Cloud OCR profile boundary regression 30 passed。这是本地清单重放，不代表远端 CI 或生产验收。
- 仍未执行生产操作、真实 PostgreSQL、真实 OCR/AI、微信真机或生产 Admin 浏览器验收；本批只覆盖
  `review_scheduler`，不覆盖 `study_report_service`、任务队列、OCR 导入编排、AI 分析执行等学习域大函数，
  也不声称学习域整体完成。

## 16. 学习报告明细投影（study_report_service）拆分

- 2026-10-28，`study_report_service` 两个超预算入口收敛：`get_review_plan` 98 → 31 行、
  `get_wrong_questions_summary` 91 → 31 行；新增 4 个 helper：`_wrong_summary_items_query` 28、
  `_load_first_knowledge_point_map` 26、`_count_wrong_summary_states` 26、`_review_plan_items_query` 22，
  全部满足 300/50 预算；模块 625 → 614 行，顶层定义 15 → 19，其余 13 个函数逐字未动。
- 该批次优先复用既有单点而非新增平行实现：`get_review_plan` 的两路去重计数改为调用既有
  `_count_review_states`（其内部复用既有 `_review_state_count_query`），`get_wrong_questions_summary`
  的两路计数改用同一 `_review_state_count_query` 组装；原先在两个入口里逐字重复的知识点批量加载
  （含 `question_knowledge_points.id` 升序取首条、`IN` 批量、join `knowledge_points`）收敛为
  `_load_first_knowledge_point_map`，模块内该 loader 只有一处定义、两处调用，两个入口内不再出现
  `QuestionKnowledgePoint`。
- 复习计划语义保持：仍先取 `utcnow()` 一次并派生 `overdue_threshold = now - 1 天`；到期计数仍是
  `next_review_at <= now AND next_review_at IS NOT NULL`，逾期计数仍是
  `next_review_at < overdue_threshold AND next_review_at IS NOT NULL`，给定 `subject_id` 时两者都
  追加 `JOIN questions ... AND questions.subject_id = ?`；明细仍是同一列集
  （`question_id`/`box_level`/`wrong_count`/`correct_count`/`next_review_at`）配同一组过滤，
  仍按 `next_review_at ASC, box_level ASC, wrong_count DESC` 排序并 `LIMIT`，仍批量取知识点、
  缺失时回落 `knowledge_point_id=None`/`knowledge_point_name=None`，返回键序
  `due_count`/`overdue_count`/`today_recommended_count`/`items` 不变。
- 错题摘要语义保持：总数仍是 `wrong_count >= min_wrong_count`，重复错题仍是
  `wrong_count >= 3 AND wrong_count >= min_wrong_count`（两条阈值并存这一历史形态逐字保留），
  给定科目时同样追加科目 JOIN 过滤；明细仍是 8 列（含 `questions.content AS q_content`），
  无论是否限定科目都 JOIN `questions`，仍按 `wrong_count DESC, box_level ASC,
  last_answered_at DESC NULLS LAST` 排序并 `LIMIT`，题目状态仍按
  「`wrong_count >= 3` → `repeated_wrong`，否则 `correct_count == 0` → `not_mastered`，否则
  `needs_review`」的优先级判定，返回键序与 `items` 投影不变。
- 一处时间点差异已记录：`int(due_count)`/`int(wrong_total)` 等换算从「返回载荷时」提前到
  「共享计数 helper 内」，对真实数据库不可观测——`COUNT()` 永不返回 NULL，而 HEAD 的共享 helper
  本来就是提前换算；本批差分工具因此只注入合法聚合结果（0/正整数），并在工具内注明该约束。
- 13 项固定契约（`tests/test_services/test_study_report_detail_contract.py`）在拆分后与拆分前均可通过
  （HEAD 原实现经 AST 提取后以 pytest 插件回放：13 passed），覆盖语句顺序、科目 JOIN 的有无、
  两路计数的绑定参数、`LIMIT` 与阈值透传、`IS NOT NULL` 与 `<=` 边界、排序键顺序、`NULLS LAST`、
  首条知识点胜出、载荷缺省回落与错题状态优先级，以及「同一次 `utcnow()` 同时喂给计数与逐行投影」。
- 1400 例随机差分（`/tmp/srs-batch/differential.py`，两个入口各 700 例）比较返回值、异常、渲染 SQL 与
  绑定参数序列、结果访问器序列以及响应队列消费集合：0 mismatch、0 harness gap、0 dead queue。
- 32 个故障变体全部被拒绝（日志 `/tmp/srs-batch/mutants.log`，32/32 rejected），每个变体仅作用于单个函数，
  覆盖计数阈值与范围透传、计数投影互换、`LIMIT` 透传、时间窗口（`<=` 边界、单次取时钟）、`IS NOT NULL`
  守卫、排序键顺序与 `NULLS LAST`、科目 JOIN、知识点 join 与首条规则、明细列集与 `>=`/`>` 边界。
- AST 证明（`/tmp/srs-batch/verify_ast.py`、报告 `/tmp/srs-batch/ast-report.json`）：13 个未触及函数与 HEAD AST
  完全一致（0 differing、0 old-only）；模块级语句 23/23 逐字保留、0 新增；两个入口消失的 57 个表达式由
  15 条allowance 规则全部解释且每条规则至少命中一次（反空规则自检），0 去重缺口、0 未解释差异。
- 架构门禁（`tests/architecture/test_study_report_projection_boundaries.py`）在既有 3 项之上新增 6 项：
  6 个函数的预算、两个入口签名与默认值、4 个 helper 的冻结单行语义、委派顺序、单点归属
  （计数经 `_count_review_states`/`_review_state_count_query`、知识点 loader 唯一、`.limit(limit)` 与
  `NULLS LAST` 各一处），并含「放宽 helper 预算」「颠倒计数与明细读取顺序」「复制知识点 loader」
  三项反向自检。
- 定向回归：新增契约 13 + 门禁 9 与既有 `test_study_report_service`、
  `test_study_report_compatibility`、`test_study_report_projection`、
  `test_study_report_overview_query_contract` 合计 104 passed；严格 Ruff、`ruff format --check` 与
  50 行预算扫描通过。
- 冻结业务、测试与 CI 清单后，本机按当前 YAML 的静态步骤精确重放 421 个测试文件：7299 passed、0 failed、
  64 条既有弃用 warning，420.35 秒；Mocked readiness boundary regression 69 passed；
  Cloud OCR profile boundary regression 30 passed。这是本地清单重放，不代表远端 CI 或生产验收。
- 仍未执行生产操作、真实 PostgreSQL、真实 OCR/AI、微信真机或生产 Admin 浏览器验收；本批只覆盖
  `study_report_service` 的两个明细入口，不覆盖任务队列、OCR 导入编排、AI 分析执行等学习域大函数，
  也不声称学习域整体完成。
