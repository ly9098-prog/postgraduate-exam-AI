# 学习计划与报告兼容基线

核对日期：2026-10-24，2026-10-29 增补第 8 节规则/完成度/视图拆分登记。对应重构计划阶段 0；范围仅限 `study_plan_service` 的阶段/分配/概览和 `study_report_service` 的报告生成，不表示学习域、OCR 导入或全栈阶段 0 完成。

## 1. 学习计划阶段划分

`_phase_for_days(days_remaining)` 按剩余天数返回 `(code, label)`：

| 剩余天数 | code | label |
| --- | --- | --- |
| ≤ 0 | target_day | 目标日 |
| 1–45 | sprint | 冲刺阶段 |
| 46–180 | steady | 强化阶段 |
| > 180 | foundation | 基础阶段 |

## 2. 整数分配

`_allocate_integer(total, weights)` 将 total 按权重分配到四类 `CATEGORIES = (review, weakness, new, exam)`：

- total ≤ 0 或权重全零 → 全零。
- 负权重视为零。
- 先 floor 分配，余数按最大小数部分（平局按 CATEGORIES 顺序）补 1。
- 结果键恰好为 CATEGORIES，值之和等于 total（当 total > 0 且有权重时）。

## 3. 计划 upsert

`upsert_study_plan(db, user_id, data)`：

- 目标日期不能早于今天，否则 `ValueError`。
- 存在计划 → 行锁序列化更新；字段变更时 revision+1。
- 不存在 → savepoint + 唯一约束竞态重载 winner；非唯一约束错误继续抛出。
- `deactivate_study_plan` → is_active=False、revision+1。

## 4. 概览与日快照

`get_study_plan_overview` 聚合日起始分钟、今日完成度、科目权重和动态剩余。`_ensure_day_snapshot` 用 savepoint claim 防止并发重复创建日快照。

## 5. 学习报告

`study_report_service`（722 行）：

- `safe_accuracy` 处理除零；`classify_mastery` 按正确率分类；`calc_priority` 计算优先级。
- 报告从练习记录、错题和知识状态聚合；空数据返回全零安全响应。

## 6. 可执行基线

- `backend/tests/test_services/test_study_plan_compatibility.py`：新增 20 项测试覆盖阶段边界（8 参数化）、整数分配（7 项：零/负/单类/等权/余数/键集）和 ceil_minutes（5 项）。
- `backend/tests/test_services/test_study_plan_concurrency.py`：日快照并发冲突保留外层计划变更。
- `backend/tests/test_services/test_study_plan_completion_contract.py`：5 项真实 SQLite 契约，覆盖 review 2 题/分钟取整、smart 练习计入 new、考试 5 分钟、非 smart 练习按 weak/new 计划 10:20 拆分（含 4 种退化分支）、番茄钟原始 30 分钟与补充 20 分钟、补充分钟按未完成目标封顶、`study_day_seconds` 跨 study-day 窗口，以及配置/未配置两种 overview 响应形状。
- `backend/tests/architecture/test_study_plan_boundaries.py`：5 项门禁，覆盖新模块行数与函数预算、依赖方向与纯函数/只读约束、overview 入口委托顺序、别名身份，以及模块增长/写操作泄漏/删除委托调用的负向变异。
- `backend/tests/test_services/test_study_report_service.py`：safe_accuracy、classify_mastery、calc_priority、空数据安全响应。
- 上述两个新测试路径已加入 `.github/workflows/ci.yml` 的 `Static architecture & non-GPU regression tests` 步骤，随 push/PR 静态清单执行（`deploy.yml` 的全量 `pytest tests/` 仅 `workflow_dispatch` 手动触发）。

## 7. 未完成和未验证

- 纯函数测试不覆盖 `upsert_study_plan` 的数据库竞态、行锁和 savepoint 行为；需 PostgreSQL 并发验收。
- `get_study_plan_overview` 的完成度口径、动态剩余、科目权重与委托顺序已由第 8 节的契约/门禁测试覆盖；`_load_activity_dates`、`_ensure_day_snapshot`、`upsert_study_plan` 的内部实现语义仍未登记。
- 真实多设备并发 upsert、日快照跨日切换和生产 PostgreSQL 行锁仍待环境可用后验收。
- 拆出后的完成度查询只在真实 SQLite 上验证过，未在 PostgreSQL 重放；本文档不据此声称生产数据库行为一致。

## 8. 规则 / 完成度 / 视图拆分（2026-10-29）

`study_plan_service`（812 行）的纯规则、今日完成度装载和视图装配已分别迁出，历史私有名在 service 内保留别名：

| 模块 | 行数 | 职责 | 依赖 |
| --- | ---: | --- | --- |
| `services/study_plan_rules.py` | 250 | `CATEGORIES`、`PRIORITY_LABELS`、阶段划分、整数分配、权重与可用性、动态剩余、`ceil_minutes`、`study_day_seconds`、`focus_duration_for_subject_scope`、补充分钟封顶、`completed_by_category` | 仅 `services/pomodoro_attribution`；门禁断言无 `db`/`execute` 等数据库调用 |
| `services/study_plan_completion.py` | 280 | `load_today_completion`：今日 review/practice/exam/pomodoro 的 study-day 窗口查询、活动区间与补充分钟装载 | `services/study_plan_rules`、models、`core/time_utils`；门禁断言无 `commit/rollback/flush/begin_nested/add/add_all/delete` |
| `services/study_plan_views.py` | 218 | 日快照 payload（阶段/权重/基础值）与四类分配视图（route/文案/状态/预计题数） | 仅 `services/study_plan_rules` |

- 依赖单向：`rules ← views`、`rules ← completion`，两者都不反向依赖 `study_plan_service`；service 只做编排，`get_study_plan_overview` 按 `_load_day_start_minute → _load_active_plan → _load_overview_inputs → _materialize_overview_day → _load_overview_facts → _overview_totals → _overview_response` 顺序委托，且入口不再直接 `select` 或调用 `_ensure_day_snapshot`/`_today_completion`。
- 行为等价核对：以 `HEAD` 版实现与拆分后函数做约 2000 组随机输入对拍（阶段、整数分配、权重、可用性、动态剩余、补充分钟、科目权重拆分、快照 payload、分配视图），差异为 0；`load_today_completion` 保留原查询顺序、`activity_spans` 装配顺序与 commit 时点，`_today_completion` 继续以同名瘦包装委托。
- 数据库级 overview 对照中唯一差异是 `created_at`/`updated_at` 时间戳与每次请求新签发的 `plan_token`，其余业务字段一致；改动不改变接口字段、事务边界或统计口径。
- 预算门禁固化：三个新模块上限 260/300/230 行、全部函数 ≤50 行、service 820 行，`_load_activity_dates` 150、`_ensure_day_snapshot` 80、`upsert_study_plan` 65 的 legacy ceiling，以及别名身份与委托顺序。
- 历史私有名 `_study_day_seconds`、`_task_by_type` 仍在 service 命名空间可导入（别名指向新模块定义）；`_load_activity_dates`、`_ensure_day_snapshot`、`upsert_study_plan` 本批未迁出。
