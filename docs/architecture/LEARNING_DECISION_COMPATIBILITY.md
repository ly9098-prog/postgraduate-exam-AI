# 学习决策与并发语义兼容基线

核对日期：2026-10-23。对应重构计划阶段 0；范围仅限推荐实验分组、学习计划、用户趋势、推荐指标日聚合和错题编辑缓存，不表示学习闭环或全栈语义审查全部完成。

## 1. 入口与消费者

| 用例 | 注册入口和实现 | 当前消费者 | 兼容边界 |
| --- | --- | --- | --- |
| 推荐实验策略解析 | `practice_service` 调用 `recommendation_experiment_service.resolve_strategy_for_user`；Admin 路由管理实验 | 小程序 smart 练习、推荐实验页/报告 | 保留 scene、默认策略、流量 cap、稳定 hash 和失败降级；实验分配不能污染调用方事务。 |
| 用户实验分组 | `assign_user_to_variant` | 策略解析及 Admin 实验消费者 | 已分组用户仍重新应用当前流量上限；首次并发只接受数据库唯一约束的 winner。 |
| 推荐日指标聚合 | `POST /api/admin/v1/recommendation/metrics/aggregate`、`/metrics/backfill`、推荐指标 scheduler | Admin 推荐报告、健康报告、系统任务页 | 保留北京时间自然日、subject/scene/strategy/variant 维度和覆盖式聚合；variant 为空的维度也必须唯一。 |
| 学习计划保存 | `PUT /study-plan` → `study_plan_service.upsert_study_plan` | 小程序学习计划页 | 每用户一条计划；只有配置实际变化才递增 revision。 |
| 学习计划日快照 | `_ensure_day_snapshot` → `PUT /study-plan`、`GET /study-plan/overview` | 首页学习计划卡片、计划页 | 每计划每天一条稳定快照；完成量继续实时投影自 Review/Practice/Exam/Pomodoro 事实。 |
| 用户统计趋势 | `/api/v1/stats/trends`、dashboard 内部调用 → `stats_service.get_trends` | 首页/dashboard | 指定窗口为半开区间，accuracy 为 0 到 1 小数。 |
| 学习报告趋势 | `/api/v1/study-report/*` → `study_report_service.get_study_trend` | 学习报告消费者 | 固定截止当前北京时间自然日；accuracy 为百分数，不能与 stats 合并。 |
| 错题分类编辑 | `PUT /api/v1/wrong-questions/{id}` | 错题本编辑入口 | 成功更新后失效该用户的错题列表与统计缓存；404 不失效。 |

注册入口以当前 router 和页面请求为准。推荐缓存失效函数没有生产调用点这一现象只登记为后续兼容清理候选，不能仅凭无引用删除。

## 2. 事务与并发事实

### 推荐实验分组

- 是否进入实验使用 `(experiment_id, user_id, "traffic")` 稳定桶；分到哪个 variant 使用独立 `"variant"` 稳定桶。不能复用同一桶，否则 50% 流量且 A/B 各半时 B 永远没有用户。
- 历史用户即使已有 assignment，也必须重新应用管理员当前 `traffic_ratio` 与 `max_traffic_percent`；下调 cap 后超出范围的历史用户立即不进入实验。
- 首次分组在 savepoint 内插入。唯一冲突只回滚 savepoint，随后重读 `uq_rea_experiment_user` 的 winner；不能回滚整个请求事务，也不能因异常把用户静默切回默认策略。
- SQLite 在 savepoint 前显式启动外层事务，避免 deferred BEGIN 下释放 savepoint 后，调用方后续 rollback 仍残留首次分组。

### 学习计划与日快照

- `StudyPlan` 由每用户唯一约束约束；PostgreSQL 更新已有计划时使用行锁，SQLite 依赖写序列化。并发首次创建同样使用 savepoint claim，冲突后重读 winner。
- revision 只在目标日期、每日分钟、每周天数、优先级模式或激活状态实际变化时递增；首次创建固定为 1。
- `StudyPlanDay` 由 `(plan_id, plan_date)` 唯一约束约束。快照行携带当时 plan revision、分配和 `day_start_minute` basis；plan revision 或统计日设置变化时重算当日快照。
- 日快照首次并发创建冲突后不再执行全事务 rollback，保留调用方已加载的计划和未提交修改；唯一冲突只允许重读 winner。
- 学习计划的分科最大余数算法与番茄统计相似但异常、输入裁剪和顺序语义不同，不能强行合并。

### 推荐指标日聚合

- `recommendation_metrics_daily.variant_key` 可空，而 SQLite/PostgreSQL 都把多个 `NULL` 视为不同唯一值；仅依赖现有唯一约束不能阻止两个并发聚合器各插入一条无实验分组行。
- 聚合入口使用数据库级范围锁：PostgreSQL 按 `(target_date, subject_id)` 获取事务级 advisory lock；SQLite 在读取前执行 `BEGIN IMMEDIATE`。这样无需改表或把可空 variant 改成业务哨兵值，同时保持 API 中的 `null` 语义。
- 单日手动聚合、日期区间补跑和 scheduler 共享同一锁范围；补跑仍在每天 savepoint 内隔离失败，但 SQLite 的 writer lock 在整个补跑事务中保持。
- 聚合仍是覆盖式 UPSERT：以最近一次 `recommendation_logs` 聚合结果更新曝光、点击、答题、正确/错误、平均分、完成率和准确率。锁只消除同维度并发重复，不改变指标口径。

## 3. 时间与缓存边界

- stats 趋势使用请求 `start_date` 与 `days` 构造 `[start, start + days)`，历史周期查询不能扫描当前周期或未来记录。
- study report 趋势使用 `[today - days + 1, tomorrow)` 的北京时间自然日窗口，不读取未来记录。
- 两服务共享 DB 日期投影，但 stats accuracy 为 0 到 1、study report accuracy 为百分数；待复习和错题来源也不同，当前不建立统一报告聚合器。
- 错题编辑成功后按 `wrong_questions:*:{uid}*` 与 `stats:*:{uid}*` 失效缓存。批量操作和诊断确认还包含 review/dashboard 专用 pattern，不能用一个过宽的通配模式替代。

## 4. 可执行基线

- `backend/tests/test_services/test_recommendation_assignment_concurrency.py`：savepoint 冲突不污染外层、stale 首读后重载 winner、两个并发分配收敛到一条稳定记录。
- `backend/tests/test_services/test_recommendation_metrics_concurrency.py`：真实临时 SQLite 上两个无 variant 的并发日聚合最终只有一条记录。
- `backend/tests/test_services/test_study_plan_concurrency.py`：日快照唯一冲突后，外层计划修改仍可提交且数据库只有一条快照。
- `backend/tests/test_services/test_learning_stats_query_bounds.py`：SQLite/PostgreSQL SQL 编译及 stats/study-report 半开窗口上界。
- `backend/tests/test_api/test_wrong_question_update_cache.py`：成功编辑的精确缓存 pattern，以及 404 不失效。
- 既有 recommendation phase 4/4.5、metrics、stats、study-report、study-plan 保存/API 回归继续作为行为基线。

以上测试已接入 `.github/workflows/ci.yml` static 步骤。

本地重放同一 CI static architecture/non-GPU 步骤的结果为 `2513 passed, 8 warnings`；warning 均为既有 datetime 弃用提示，不是本批新增失败。

## 5. 未完成和未验证

- PostgreSQL advisory lock 只通过 SQL 构造审查和 SQLite 并发等价验证；本机没有 PostgreSQL 服务端，未执行真实 PG 并发验收。
- 未执行生产 Admin 浏览器、真实推荐日志回填、完整 scheduler/worker 循环或 Redis 中断恢复。
- 已入库题目 `re_pending`、重审/版本回滚已由 Admin 题库域实现；学习决策域仍只消费 `approved + is_active` 题目，不参与审核状态迁移。
- `practice_service` 的 `get_similar_practice_questions` / `get_smart_practice_questions` 保留 `use_leitner` 形参，但实际到期过滤与 fallback 由 issuance 层 `candidate_schedule.filter_due_candidates` 统一执行（`question_issuance.issue_practice_questions` 调用），不再在各召回函数内重复实现。

## 6. scored 选题编排边界（2026-10-26）

- `get_smart_scored_questions` 负责候选与学习上下文装载，并在图谱扩充后、评分前快照候选 ID；后续 fallback 排除范围沿用这一快照，不能从评分器可能修改过的候选列表重建。
- `practice/scored_policy.py` 组合排序、top5 日志、元数据投影和多样性选择。真实评分器、排序器、选择器、元数据构造器和 logger 由服务入口显式注入；运行时配置中的 graph 对象保持原引用。该模块不装载数据库或运行时配置，不捕获评分/选择异常。
- `_complete_scored_selection` 留在 `practice_service`，继续绑定原 SQL loader、fallback 过滤器、采样器和合并器，保留降级级别、最终日志和结果切片。事务、持久化与推荐最终记录职责不变。
- `test_scored_policy_boundaries.py` 与五个 scored 架构测试约束新的调用链、精确端口绑定、两个服务入口禁止直接执行 SQL、候选快照时序和模块导入无运行时副作用。mutation 用例分别向选题入口和 completion 的 AST 注入 `db.execute`，确认两处均被门禁拒绝。
- `test_scored_selection_contract.py` 覆盖真实评分/选择/元数据端口、logger identity 与日志顺序，以及排序器/选择器普通异常和取消的传播。相同 selection/pipeline 契约在拆分前入口和拆分后入口均通过；本地行为测试不能替代真实 PostgreSQL、Redis、微信或外部模型验收。
- 本批只收敛 scored 服务入口，学习域内部的评分、顺序选题、知识总结和投影协调等模块仍有超过预算的函数，不能据此宣称学习域或阶段 0 已全部完成。

### 数值评分组成

- `calculate_smart_score` 保留原签名、原模块的 observed-weak 回调端口，以及配置归一化和阈值校验先于题目状态读取的顺序。`smart_score_history.py` 负责到期、薄弱、错题/新题和覆盖；`smart_score_path.py` 负责阻塞惩罚、前置候选奖励和路径就绪。
- due、weakness、wrong、new、diversity、path 六组按原顺序相加和应用权重，原因列表也按此顺序组合。阻塞路径质量沿用未裁剪的最大值，前置候选质量仍裁剪到 `[0, 1]`；空阻塞列表的键仍禁止路径就绪奖励。未知前置仍校验原有数值字段。
- 拆分前新增的 19 项行为刻画通过；拆分后补充端口、数值校验与奖励去重用例。`test_smart_score_boundaries.py` 约束两个数值模块无数据库/配置依赖、新函数不超过 50 行及原评分入口不超过 50 行。

### 推荐理由文案

- `_build_smart_recommendation_reason` 从 126 行收敛至 50 行，保留配置归一化顺序和原模块 observed-weak 动态回调。`smart_reason_text.py` 提供图谱前置、薄弱知识、观测薄弱、阻塞和覆盖文案规则；不读取配置或数据库。
- 优先级保持为图谱前置、到期复习、确认薄弱、观测薄弱、错题历史、阻塞、路径就绪、新题/长期未练/覆盖。图谱候选与知识点仍按原顺序取首项，中文文案逐字保留；observed-weak 名称仅在对应分支读取，不能提前触发数值校验或回调。
- 19 项文案与端口刻画先在原实现通过；拆分后与数值评分、scored selection/pipeline、自适应学习和架构检查合跑 151 项通过。现有评分架构检查扩展到文案模块，约束函数预算与中性依赖。学习域其余顺序预留、知识总结及投影协调仍有超预算内部函数。

## 7. weakness-vector 策略权重重排（2026-10-26）

- `strategy_weight_rerank.apply_strategy_weight_rerank` 保留配置守卫、异常边界与元数据写回；知识点 ID、用户掌握度分别由独立装载函数查询，题目知识点装载仍走原 `load_question_kps`。知识点 ID 与掌握度各至多查询一次，不因候选数量增加产生额外查询。
- `strategy_weight_scores.build_strategy_base_scores` 只计算相似度、知识重叠、难度匹配、掌握缺口与路径分量。知识重叠分子去重而分母保留原列表长度；未知掌握度使用 0.5，目标难度仍按全部已知掌握度均值和原 `round` 规则生成。
- 权重函数在一次重排中只绑定一次；随机数仍逐候选动态读取，即使探索比例为 0 也调用。探索比例不新增裁剪，最终分数用于稳定排序，元数据 `recommend_score` 仍记录四位小数的纯权重分数。
- 普通失败使用原模块 logger 和原 warning 返回原 questions/metadata 引用；取消继续传播。写回中途失败时已写入的元数据仍保留，不能在重构中改成回滚整个字典或返回副本。
- 新增 24 项契约在拆分前后均通过，相关推荐指标和 legacy weakness-vector 合跑 43 项通过。5,000 组确定性对照的结果、元数据身份、SQL/随机数/日志轨迹一致；架构检查固定函数预算、无事务提交、纯评分依赖及 fresh import 边界。

## 8. Leitner 查询与回退装配（2026-10-27）

- `_get_questions_with_leitner` 保留原调用签名，委托 `practice/leitner_selection.py` 组装查询请求与加载器；到期条件、SQL 构造、四层调度与 V1 回退仍使用原实现。本批没有新增选题模式或修改 `use_leitner` 的行为。
- 一次调用先读取时钟，再构造已答题排除子查询。排除条件用于前三层全部查询；`no_repeat_days` 有值时，即使 `exclude_answered=False` 也继续应用窗口。SQL 保留用户状态 outer join、原科目与激活条件、到期范围和最早作答排序。
- query request 在首次查询前绑定原条件列表、排除子查询、随机采样器和 DB 执行方法，不复制条件或在后续层重新捕获执行方法。查询与 V1 回退回调继续从原服务命名空间动态读取，保留等待期间替换回调的行为；logger 与到期条件函数仍在启动层次调度时绑定。
- 层次顺序继续为新题/到期、一天内到期、31 天内按最早作答排序、V1 回退。第二、三层按当前候选列表长度计算缺口；V1 按已选唯一 ID 数计算缺口。候选次序、列表内已有重复项、最终切片和日志沿用原调度器，不在装配模块新增去重或排序。
- 普通异常与取消原样传播，不隐式启动后续层或回退，不提交、回滚或创建后台任务。新模块不导入 ORM、运行时配置、数据库或原服务，保留单向依赖。
- `test_leitner_service_contract.py`、`test_leitner_service_queries.py` 与既有 `test_leitner_layers.py` 合计 56 项，在拆分前后均通过；新增 3 项架构检查约束函数/文件预算、服务入口与独立导入。查询测试只编译 SQLite/PostgreSQL SQL，实际任务取消使用本地 asyncio；这些证据不代表真实数据库、Redis、微信或完整 worker 验收。
