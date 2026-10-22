# Review Algorithm (SM-2)

> 当前复习调度实现说明。最后更新：2026-10-23（API 清单按 `backend/app/api/v1/review.py` 实际路由修正）。

## 实现入口

算法唯一实现：`backend/app/services/sm2_service.py` 的 `calc_sm2()`。

```text
输入：quality (0-5), ease_factor, interval, repetitions, review_date
输出：ease_factor, interval, repetitions, next_review_at
```

核心规则：

- `quality < 3`：连续正确次数归零，间隔重置为 1 天。
- `quality >= 3`：第 1 次间隔 1 天，第 2 次间隔 6 天，之后按 `interval × ease_factor` 计算并稳定四舍五入。
- ease factor 下限为 1.3，评分 0 是合法值。
- 复习日期按 Asia/Shanghai 日历日计算（`shanghai_today()`）；`next_review_at` 存储为该上海日历日起点的 naive UTC 瞬时（`shanghai_date_utc_range()`）。

## 数据职责

`review_schedules` 是唯一的当前调度状态：

```text
review_schedules
├── user_id / question_id
├── interval
├── ease_factor
├── repetitions
├── next_review_at
├── last_reviewed_at
└── mastered
```

`wrong_questions` 只保存错题答案、错误类型、AI 分析、复习次数和状态，不保存 SM-2 参数。`review_records` 保存每次提交的 rating、算法前后快照，是追加型历史表。

## 复习流程

```text
做错题
  → review_scheduler.auto_schedule_wrong_question()
  → 创建或更新 ReviewSchedule

提交复习评分
  → review_scheduler.submit_review()
  → calc_sm2()
  → 更新 ReviewSchedule
  → 写入 ReviewRecord
```

自动批改未提供 rating 时使用：正确题 `4`，错误题 `1`。

## 当前 API

| 接口 | 用途 |
|---|---|
| `GET /api/v1/review/today` | 今日待复习列表 |
| `GET /api/v1/review/today/overview` | 今日复习任务流概览 |
| `POST /api/v1/review/today/next-batch` | 获取下一批待复习 |
| `GET /api/v1/review/today/result` | 今日复习完成结果汇总 |
| `GET /api/v1/review/schedule-stats` | 复习统计 |
| `GET /api/v1/review/history` | 复习历史 |
| `POST /api/v1/review/grade-batch` | 批量自动批改 + 提交（上限 40 条） |
| `POST /api/v1/review/{schedule_id}/master` | 标记已掌握 |
| `POST /api/v1/review/{schedule_id}/unmaster` | 取消已掌握 |

旧 `/review/due`、`/review/submit`、`/review/stats`、`/review/schedule-submit`、`/review/batch-submit`、`/review/grade-submit` 端点均已移除，不应再接入新客户端；自评 rating 的单条/批量提交入口已不存在，评分提交统一走 `grade-batch`（按作答对错映射 4/1）。

## 设计约束

- 所有入口必须复用 `calc_sm2()`，不得在 API 或前端复制算法。
- 不允许从 `WrongQuestion` 反向推导或覆盖 `ReviewSchedule` 的复习参数。
- `mastered` 是调度状态的一部分；错题再次提交后由调度服务按当前规则更新。
- 任何调度变更都应同步写入 `review_records` 或相应审计/诊断记录，便于追溯。

## 相关测试

- `backend/tests/test_services/test_review_scheduler.py`
- `backend/tests/test_services/test_sm2_service.py`
- `backend/tests/test_api/test_review_api.py`
- `docs/backend/REVIEW_SMOKE_CHECKLIST.md`
