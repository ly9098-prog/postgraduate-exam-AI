# Review Algorithm (SM-2)

> 基于 SuperMemo SM-2 算法的间隔重复复习系统，用于错题复习调度。

---

## 当前实现

### 算法实现

**`app/services/sm2_service.py` — `calc_sm2()`**

```
入参: quality (0-5), efactor (2.5), interval (0), repetitions (0), review_date
出参: {efactor, interval, repetitions, next_review_date}
```

核心逻辑：
- `quality < 3`：repetitions 重置为 0，interval = 1
- `quality >= 3`：
  - 第 1 次复习（repetitions=0）：interval = 1
  - 第 2 次复习（repetitions=1）：interval = 6
  - 第 3+ 次复习：interval = round(interval * EF)
- EF 更新公式：`EF' = EF + (0.1 - (5-q) * (0.08 + (5-q) * 0.02))`，下限 1.3

### SM-2 字段位置

挂在 `WrongQuestion` 表上（`app/models/wrong_question.py`）：

```
wrong_questions
├── efactor: float = 2.5        # 难度因子
├── interval: int = 0            # 当前间隔（天）
├── repetitions: int = 0         # 连续正确次数
├── next_review_date: date       # 下次复习日期
├── quality: int | None          # 最近一次质量评分
├── review_count: int            # 总复习次数
├── last_review_at: datetime     # 最近一次复习时间
└── mastered: bool = False       # 是否已掌握
```

### 自动掌握

当 `update_quality()` 中：
- `quality >= 4` 且 `repetitions >= 3` → `mastered = True`

> 注意：这里用的是 SM-2 计算后**更新后**的 repetitions 值，即连续正确 3 次后标记掌握。

### 首次错题记录

`wrong_question_service.record_wrong()`：
- 首次记录：`efactor=2.5`, `interval=1`, `repetitions=0`, `next_review_date=today+1`
- 重复记录：`review_count+1`，mastered 重置为 False

### API

| 接口 | 功能 |
|---|---|
| `GET /api/v1/review/due` | 今日待复习列表（分页，可选 subject 筛选） |
| `POST /api/v1/review/submit` | 批量提交质量评分（items: [{wrong_question_id, quality}]） |
| `GET /api/v1/review/stats` | 复习统计（total / due / reviewed / mastered / avg_ef / by_subject） |

---

## 存在问题

1. **无每日复习计划** — `get_due_reviews` 返回所有到期待复习的题，没有上限控制。遇到大量错题时用户可能一天要复习几百道
2. **无优先级排序** — 到期待复习的题按 `next_review_date` 排序返回，没有考虑错题次数、EF、最近掌握率等因素
3. **mastered 重置过于简单** — 任何一次新错都会把 mastered 设为 False，已掌握的题可能会反复"已掌握→又错了→再次掌握"
4. **无质量评分校准** — 用户的 `quality` 评分可能不准确（比如凭感觉给分），系统没有校准或归一化逻辑
5. **批处理原子性** — `submit_batch_review` 循环内单条失败不会滚，可能导致部分提交部分丢失
6. **review_plan.py 模型不存在** — 无按天聚合的复习计划表，无法做每日复习量规划

---

## 下一阶段扩展方案

### Phase 1 — 基础增强（1 天）

**复习上限控制**
- `get_due_reviews` 增加 `max_daily` 配置（默认 30）
- 超限题目延迟到次日

**优先级排序**
- 排序公式：`priority = EF × review_count × (1 - avg_accuracy_30d)`
- 历史正确率从 `AnswerBehavior` 表取最近 30 天数据

### Phase 2 — 复习计划模型（1 天）

新增 `review_plans` 表：

```sql
review_plans
├── id
├── user_id
├── plan_date: date          # 计划日期
├── subject: string
├── total_count: int         # 计划复习数
├── completed_count: int     # 已完成数
├── status: string           # pending / in_progress / completed
└── created_at / updated_at
```

逻辑：
- 用户访问复习页时自动生成或检查今天的 plan
- 每天每人每科一条 plan 记录
- `GET /api/v1/review/due` 支持返回今天是否需要复习

### Phase 3 — 质量评分简化（1 天）

**二值模式降级**
- 当用户不愿做 0-5 精细评分时，支持 "简单 / 困难" 二值模式
- 映射：`简单→quality=4`，`困难→quality=2`
- 前端可配置默认使用二值还是 0-5 评分

### 明确不做的

- ❌ 多模型 SM-2（不拆 choice/fill/subjective 不同参数）
- ❌ 自定义 SM-2 参数暴露给用户（EF、interval 上限等不开放配置）
- ❌ 群体统计 / 群体 EF 共享
- ❌ 复习提醒推送（小程序不做主动推送）
- ❌ 复习日历 / 热力图
