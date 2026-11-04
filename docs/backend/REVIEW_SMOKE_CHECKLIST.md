# 复习系统 Smoke Test 检查清单

> 开发者手工验证步骤。每次修改复习调度相关逻辑后执行，确保核心流程不退化。最后更新：2026-10-23（接口按当前路由修正：`schedule-submit` / `grade-submit` 已移除，提交统一走 `grade-batch`）。

---

## 前置条件

- 后端服务运行中（`pytest` 全量用例通过）
- 数据库中有至少 1 个用户和若干题目
- 准备好 API 工具（curl / httpie / 小程序开发者工具）

---

## 检查项

### 1. 做错题 → 自动进入复习

```
POST /api/v1/practice/submit
{
  "question_id": 1,
  "user_answer": "B",   // 错误答案
  "used_time": 30
}
```

**验证：**
- [ ] Response 中 `is_wrong_added` = `true`
- [ ] `WrongQuestion` 表新增记录，`user_id`、`question_id` 正确
- [ ] `ReviewSchedule` 表新增记录（可通过 `auto_schedule_wrong_question` 触发结果查看）
- [ ] `WrongQuestion` 仅保存错题分析数据，复习参数只从 `ReviewSchedule` 读取

### 2. 今日待复习可查到

```
GET /api/v1/review/today?subject=&limit=20
```

**验证：**
- [ ] Response 包含刚做错的题目
- [ ] `total_today` > 0
- [ ] `questions[].schedule_id` 与 ReviewSchedule.id 对应
- [ ] 返回数据不含答案（仅为复习用途）

### 3. SM-2 评分规则（rating 直接行为）

API 已不支持自带 rating 的单条/批量提交（`schedule-submit` / `grade-submit` 均已移除）；各 rating 的 SM-2 行为由单元测试直接覆盖：

```
pytest backend/tests/test_services/test_sm2_service.py
```

**验证：**
- [ ] rating=0：`interval_after` = 1、`repetitions` = 0、`next_review_at` 当天重现、`ease_factor` 下降
- [ ] rating=4：`interval_after` > 1、`repetitions` 递增（+1）、`ease_factor` 上升、`next_review_at` 在未来的第 interval 天

### 4. 自动批改（grade-batch，单条）

```
POST /api/v1/review/grade-batch
{
  "reviews": [
    {
      "schedule_id": 1,
      "question_id": 1,
      "question_version_id": 555,
      "occurrence_seq": 0,
      "request_id": "smoke-single-0001",
      "user_answer": "A"
    }
  ]
}
```

**验证：**
- [ ] 答案匹配 → `is_correct=true`（服务端按 rating=4 推进）
- [ ] 答案不匹配 → `is_correct=false`（服务端按 rating=1 推进）
- [ ] `schedule_id` / `question_id` / `question_version_id` / `occurrence_seq` 须与 `/review/today` 返回的一致，否则该条返回 `success=false`
- [ ] ReviewSchedule 状态按 SM-2 推进，ReviewRecord 新增记录

### 6. 批量自动批改

```
POST /api/v1/review/grade-batch
{
  "reviews": [
    {"schedule_id": 1, "question_id": 1, "user_answer": "A"},
    {"schedule_id": 2, "question_id": 2, "user_answer": "B"}
  ]
}
```

**验证：**
- [ ] 全部成功处理，`total` = 提交数
- [ ] `correct_count` + `wrong_count` = `total`
- [ ] 单个题目不存在时自动跳过（不抛异常）

### 7. 标记已掌握

```
POST /api/v1/review/{schedule_id}/master
```

**验证：**
- [ ] Response `mastered` = `true`
- [ ] ReviewSchedule.mastered = True
- [ ] WrongQuestion.mastered = True（同步一致）
- [ ] `/review/today` 不再包含该题
- [ ] `/review/schedule-stats` 统计中该题的 scheduled 仍在，但 remaining 减少

### 8. 取消已掌握

```
POST /api/v1/review/{schedule_id}/unmaster
```

**验证：**
- [ ] Response `mastered` = `false`
- [ ] ReviewSchedule.mastered = False
- [ ] WrongQuestion.mastered = False（同步一致）
- [ ] `/review/today` 重新出现该题

### 9. 当前复习接口

```
GET /api/v1/review/today
```

**验证：**
- [ ] 返回题目均属于 `ReviewSchedule` 待复习范围
- [ ] 已确认旧 `/review/due`、`/review/submit`、`/review/stats` 不再作为当前接口调用

### 10. 复习统计合理

```
GET /api/v1/review/schedule-stats?days=7
```

**验证：**
- [ ] `total_scheduled` > 0
- [ ] `total_reviewed_today` + `remaining_today` ≈ `total_scheduled`（排除 mastered 后）
- [ ] `accuracy_last_7d` 在 0~1 之间
- [ ] `by_subject` 分类统计与各科目实际数据一致

---

## 回归边界

| 场景 | 关注点 |
|------|--------|
| rating=0 合法 | 不抛 ValueError，SM-2 正常计算 |
| rating=5 极限值 | 间隔不异常膨胀，efactor 上限合理 |
| 重复提交同题 | 第二次提交基于更新后的 schedule 参数 |
| 错题 → 做对 → 又做错 | SM-2 正确重置，不累加历史计数 |
| 数据库连接中断 | 503 正确返回，不产生脏数据 |

---

> 最后更新：2026-06-26

---

## 相关链接

- [[docs/backend/API_SPEC.md|API_SPEC]] — App API 合约
- [[docs/backend/DB_SCHEMA.md|DB_SCHEMA]] — App 数据模型
- [[docs/backend/STORAGE_DESIGN.md|STORAGE_DESIGN]] — 存储设计
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/architecture/REVIEW_SYSTEM_DESIGN.md|REVIEW_SYSTEM_DESIGN]] — 复习系统设计
