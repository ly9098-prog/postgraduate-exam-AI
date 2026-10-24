# 学习计划与报告兼容基线

核对日期：2026-10-24。对应重构计划阶段 0；范围仅限 `study_plan_service` 的阶段/分配/概览和 `study_report_service` 的报告生成，不表示学习域、OCR 导入或全栈阶段 0 完成。

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
- `backend/tests/test_services/test_study_report_service.py`：safe_accuracy、classify_mastery、calc_priority、空数据安全响应。

## 7. 未完成和未验证

- 纯函数测试不覆盖 `upsert_study_plan` 的数据库竞态、行锁和 savepoint 行为；需 PostgreSQL 并发验收。
- `get_study_plan_overview` 的完整聚合、动态剩余和科目权重计算未在本文档登记完整语义。
- 真实多设备并发 upsert、日快照跨日切换和生产 PostgreSQL 行锁仍待环境可用后验收。
