# 复习系统 Smoke Test 检查清单

> 开发者手工验证步骤。每次修改复习调度相关逻辑后执行，确保核心流程不退化。

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
- [ ] WrongQuestion 兼容字段（efactor/interval/repetitions）与 ReviewSchedule 一致

### 2. 今日待复习可查到

```
GET /api/v1/review/today?subject=&limit=20
```

**验证：**
- [ ] Response 包含刚做错的题目
- [ ] `total_today` > 0
- [ ] `questions[].schedule_id` 与 ReviewSchedule.id 对应
- [ ] 返回数据不含答案（仅为复习用途）

### 3. 提交 rating=0（完全不会）

```
POST /api/v1/review/schedule-submit
{
  "schedule_id": 1,
  "question_id": 1,
  "rating": 0
}
```

**验证：**
- [ ] Response `interval_after` = 1
- [ ] `repetitions` = 0（连续正确计数归零）
- [ ] `next_review_at` ≈ 今天（当天立即重现）
- [ ] `ease_factor` 略低于之前的值
- [ ] ReviewRecord 表新增记录，rating=0

### 4. 提交 rating=4（正确但有犹豫）

```
POST /api/v1/review/schedule-submit
{
  "schedule_id": 1,
  "question_id": 1,
  "rating": 4
}
```

**验证：**
- [ ] `interval_after` > 1（间隔按 SM-2 推进）
- [ ] `repetitions` 递增（+1）
- [ ] `ease_factor` 略高于之前的值
- [ ] `next_review_at` 在未来的第 interval 天

### 5. 自动批改

```
POST /api/v1/review/grade-submit
{
  "schedule_id": 1,
  "question_id": 1,
  "user_answer": "A"
}
```

**验证：**
- [ ] 答案匹配 → `is_correct=True`, `rating=4`
- [ ] 答案不匹配 → `is_correct=False`, `rating=1`
- [ ] 未提供 rating 时按默认映射，不抛异常
- [ ] ReviewSchedule 状态按 SM-2 推进

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

### 9. 旧接口与新接口不矛盾

```
GET /api/v1/review/due
GET /api/v1/review/today
```

**验证：**
- [ ] 两个接口返回的题目均属于待复习范围
- [ ] 对同一用户，两个接口的统计趋势无明显矛盾
- [ ] （已知技术债：`/review/due` 基于 WrongQuestion，`/review/today` 基于 ReviewSchedule，完全一致不保证）

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
