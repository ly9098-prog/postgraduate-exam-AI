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
- `questions.review_status = re_pending`、已入库题目重审/版本回滚仍是设计预留。
- `practice_service.use_leitner` 的 TODO(V3) 仍未实现；向量/path 结果后的到期过滤与 Leitner fallback 会改变选题行为，需单独立项。
