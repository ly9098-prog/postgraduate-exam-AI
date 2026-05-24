# Stage 12: SM-2 复习调度系统

## 1. 阶段目标

基于 SM-2 算法实现记忆曲线复习调度，为错题和已学题目提供科学的复习安排，提升长期学习效率。

## 2. MVP 范围

### 能做

- SM-2 算法核心实现（interval / ease factor / repetitions 计算）
- 复习队列生成（今日待复习题目）
- 复习结果提交（用户评分 0-5）
- 复习记录持久化（review_records）
- 错题自动进入复习调度
- 每日复习提醒（API 返回今日复习量）
- 复习统计

### 禁止做

- 不做自定义复习参数（使用标准 SM-2 参数）
- 不做多算法支持（仅 SM-2）
- 不做复习日历/热力图
- 不做推送通知（MVP 阶段仅 API）
- 不做群组/班级复习管理
- 不做间隔重复上限控制（不限制复习次数）

## 3. 非目标

- 不实现 FSRS 等现代算法
- 不做复习提醒的第三方集成（钉钉/微信推送）
- 不做复习计划自定义
- 不实现 Anki 导入/导出

## 4. 目录结构修改

### 新增文件

| 文件 | 作用 |
|------|------|
| `backend/app/services/review_scheduler.py` | SM-2 调度核心逻辑 |
| `backend/app/schemas/review_scheduler.py` | 复习调度相关模型 |
| `backend/tests/test_services/test_review_scheduler.py` | 单元测试 |

### 修改文件

| 文件 | 修改内容 |
|------|---------|
| `backend/app/api/v1/review.py` | 新增复习调度端点 |
| `backend/app/models/practice_record.py` | 确保字段完备 |

### 不修改文件

- `app/models/user.py`
- `app/models/question.py`
- `app/models/wrong_question.py`
- `app/features/` 下已有文件

## 5. 数据库变更

### 新增表：`review_schedules`

```sql
CREATE TABLE review_schedules (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id),
    question_id   INTEGER NOT NULL REFERENCES questions(id),
    subject       VARCHAR(16),          -- 冗余字段
    interval      INTEGER DEFAULT 0,    -- 当前复习间隔（天）
    ease_factor   REAL DEFAULT 2.5,     -- 简易因子
    repetitions   INTEGER DEFAULT 0,    -- 连续正确次数
    next_review_at DATETIME,            -- 下次复习时间
    last_reviewed_at DATETIME,          -- 上次复习时间
    created_at    DATETIME DEFAULT NOW(),
    updated_at    DATETIME DEFAULT NOW(),

    UNIQUE(user_id, question_id)
);
```

### 新增表：`review_records`

```sql
CREATE TABLE review_records (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id),
    question_id   INTEGER NOT NULL REFERENCES questions(id),
    schedule_id   INTEGER REFERENCES review_schedules(id),
    rating        INTEGER NOT NULL,     -- SM-2 评分 0-5
    interval_before INTEGER,            -- 复习前间隔
    interval_after  INTEGER,            -- 复习后间隔
    ease_factor_before REAL,
    ease_factor_after  REAL,
    reviewed_at   DATETIME DEFAULT NOW()
);
```

### 索引

- `review_schedules(user_id, next_review_at)` — 今日复习队列查询
- `review_schedules(user_id, subject)` — 按科目过滤复习
- `review_records(user_id, reviewed_at)` — 复习历史查询

### 错题联动

错题自动进入 review_schedules：
- 首次做错 → `next_review_at = now`（立即待复习）
- 以 rating=1 初始化（表示困难）

## 6. API 设计

### 6.1 获取今日复习

```
GET /api/v1/review/today
```

**Query Parameters:**
- `subject` (str, optional) — 按科目过滤
- `limit` (int, default 20) — 最多返回数量

**Response:**
```json
{
    "total_today": 15,
    "questions": [
        {
            "schedule_id": 1,
            "question_id": 10,
            "subject": "math2",
            "question_type": "single_choice",
            "stem": "题目内容...",
            "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
            "interval": 5,
            "repetitions": 2,
            "ease_factor": 2.5
        }
    ]
}
```

**注意：不返回答案。**

### 6.2 提交复习结果

```
POST /api/v1/review/submit
```

**Request Body:**
```json
{
    "schedule_id": 1,
    "question_id": 10,
    "rating": 4
}
```

**Rating 标准（SM-2）：**
- 0: 完全忘记（blackout）
- 1: 看到答案才想起
- 2: 想起来了但很困难
- 3: 有些困难但答对了
- 4: 一次就答对
- 5: 非常轻松

**Response:**
```json
{
    "schedule_id": 1,
    "question_id": 10,
    "rating": 4,
    "interval_after": 6,
    "ease_factor_after": 2.6,
    "next_review_at": "2025-05-30T00:00:00",
    "is_correct": true
}
```

### 6.3 获取复习统计

```
GET /api/v1/review/stats
```

**Query Parameters:**
- `days` (int, default 7)

**Response:**
```json
{
    "total_scheduled": 50,
    "total_reviewed_today": 5,
    "remaining_today": 10,
    "overdue": 3,
    "accuracy_last_7d": 0.8,
    "by_subject": {
        "math2": {"scheduled": 30, "reviewed": 3, "remaining": 8}
    }
}
```

### 6.4 批量提交复习结果

```
POST /api/v1/review/batch-submit
```

**Request Body:**
```json
{
    "reviews": [
        {"schedule_id": 1, "question_id": 10, "rating": 4},
        {"schedule_id": 2, "question_id": 15, "rating": 3}
    ]
}
```

**Response:**
```json
{
    "results": [
        {"schedule_id": 1, "question_id": 10, "next_review_at": "2025-05-30", "is_correct": true},
        {"schedule_id": 2, "question_id": 15, "next_review_at": "2025-05-27", "is_correct": true}
    ],
    "total": 2
}
```

### 6.5 获取复习历史

```
GET /api/v1/review/history
```

**Query Parameters:**
- `page` (int, default 1)
- `page_size` (int, default 20)

**Response:**
```json
{
    "items": [
        {
            "question_id": 10,
            "rating": 4,
            "interval_after": 6,
            "reviewed_at": "2025-05-24T10:00:00"
        }
    ],
    "total": 100,
    "page": 1,
    "page_size": 20
}
```

## 7. Service 设计

### 新增：`review_scheduler.py`

#### SM-2 算法实现

```python
from dataclasses import dataclass


@dataclass
class SM2Result:
    interval: int          # 新的复习间隔（天）
    ease_factor: float     # 新的简易因子
    repetitions: int       # 新的连续正确次数
    next_review_at: datetime
    is_correct: bool


def compute_sm2(
    rating: int,
    current_interval: int = 0,
    current_ef: float = 2.5,
    current_repetitions: int = 0,
) -> SM2Result:
    """
    SM-2 算法核心计算。

    Args:
        rating: 用户评分 0-5
        current_interval: 当前间隔（天）
        current_ef: 当前简易因子
        current_repetitions: 当前连续正确次数

    Returns:
        SM2Result 包含新 interval / ef / repetitions / next_review_at
    """
    # 1. 计算新的 ease factor
    new_ef = current_ef + (0.1 - (5 - rating) * (0.08 + (5 - rating) * 0.02))
    if new_ef < 1.3:
        new_ef = 1.3

    # 2. 判断是否达标（rating >= 3 视为正确）
    is_correct = rating >= 3

    # 3. 根据是否达标计算间隔
    if not is_correct:
        # 答错 → 重置
        new_interval = 1
        new_repetitions = 0
    else:
        # 答对 → SM-2 间隔计算
        new_repetitions = current_repetitions + 1
        if new_repetitions == 1:
            new_interval = 1
        elif new_repetitions == 2:
            new_interval = 6
        else:
            new_interval = round(current_interval * current_ef)

    next_review_at = datetime.now() + timedelta(days=new_interval)

    return SM2Result(
        interval=new_interval,
        ease_factor=round(new_ef, 2),
        repetitions=new_repetitions,
        next_review_at=next_review_at,
        is_correct=is_correct,
    )
```

#### 核心函数

```python
async def get_today_review(
    db: AsyncSession,
    user_id: int,
    subject: str | None = None,
    limit: int = 20,
) -> dict:
    """
    获取今日待复习题目。

    查询 review_schedules 中 next_review_at <= now 且未完成的记录。
    按 next_review_at ASC 排序（越久未复习越优先）。
    """

async def submit_review(
    db: AsyncSession,
    user_id: int,
    schedule_id: int,
    question_id: int,
    rating: int,
) -> dict:
    """
    提交复习结果。

    1. 校验 schedule 归属当前用户
    2. 调用 compute_sm2 计算新参数
    3. 更新 review_schedules
    4. 写入 review_records
    5. 若 rating < 3 且该题在错题本 → 更新错题本
    """

async def get_review_stats(
    db: AsyncSession,
    user_id: int,
    days: int = 7,
) -> dict:
    """
    复习统计。
    """

async def auto_schedule_wrong_question(
    db: AsyncSession,
    user_id: int,
    question_id: int,
) -> dict:
    """
    错题自动进入复习调度。

    在 Stage 11 答错时调用此函数。
    用 rating=1（困难）初始化 SM-2 参数。
    """
```

#### 与 Stage 11 的联动

在 `practice_service.py` 的 `submit_answer` 中，当用户答错时：

```python
# 答错 → 错题本 + 复习调度
await _update_wrong_question(db, user_id, question_id, correct_answer, user_answer)
await auto_schedule_wrong_question(db, user_id, question_id)
```

## 8. Schema 设计

### 新增：`schemas/review_scheduler.py`

```python
class ReviewQuestion(BaseModel):
    """复习用题目（不含答案）。"""
    schedule_id: int
    question_id: int
    subject: str
    question_type: str
    stem: str
    options: dict = {}
    interval: int
    repetitions: int
    ease_factor: float


class TodayReviewResponse(BaseModel):
    total_today: int
    questions: list[ReviewQuestion]


class ReviewSubmit(BaseModel):
    schedule_id: int
    question_id: int
    rating: int  # 0-5


class ReviewSubmitResponse(BaseModel):
    schedule_id: int
    question_id: int
    rating: int
    interval_after: int
    ease_factor_after: float
    next_review_at: datetime
    is_correct: bool


class BatchReviewRequest(BaseModel):
    reviews: list[ReviewSubmit]


class BatchReviewResponse(BaseModel):
    results: list[ReviewSubmitResponse]
    total: int


class SubjectReviewStats(BaseModel):
    scheduled: int
    reviewed: int
    remaining: int


class ReviewStatsResponse(BaseModel):
    total_scheduled: int
    total_reviewed_today: int
    remaining_today: int
    overdue: int
    accuracy_last_7d: float
    by_subject: dict[str, SubjectReviewStats] = {}


class ReviewHistoryItem(BaseModel):
    question_id: int
    rating: int
    interval_after: int
    reviewed_at: datetime


class ReviewHistoryResponse(BaseModel):
    items: list[ReviewHistoryItem]
    total: int
    page: int
    page_size: int
```

## 9. 测试计划

### 新增测试文件

`backend/tests/test_services/test_review_scheduler.py`

### 测试用例

| 类别 | 测试用例 | 描述 |
|------|---------|------|
| **SM-2 算法** | `test_sm2_rating_5` | rating=5 最大间隔增长 |
| | `test_sm2_rating_4` | rating=4 |
| | `test_sm2_rating_3` | rating=3 及格线 |
| | `test_sm2_rating_2` | rating=2 答错 |
| | `test_sm2_rating_0` | rating=0 完全忘记 |
| | `test_sm2_ef_minimum` | EF 不低于 1.3 |
| | `test_sm2_first_review` | 首次复习间隔=1 |
| | `test_sm2_second_review` | 第二次间隔=6 |
| | `test_sm2_third_review` | 第三次依赖 EF |
| | `test_sm2_repetitions_reset` | 答错重复计数归零 |
| | `test_sm2_ef_decrease` | 低 rating 导致 EF 下降 |
| **今日复习** | `test_get_today_review` | 获取今日复习 |
| | `test_get_today_review_empty` | 无待复习题目 |
| | `test_get_today_review_subject_filter` | 按科目过滤 |
| | `test_get_today_review_limit` | 数量限制 |
| **提交复习** | `test_submit_review_success` | 提交成功 |
| | `test_submit_review_schedule_updated` | schedule 参数更新 |
| | `test_submit_review_record_created` | review_record 创建 |
| | `test_submit_review_wrong_schedule` | schedule 不属于用户 |
| | `test_submit_review_out_of_range` | rating 0-5 校验 |
| | `test_submit_review_nonexistent` | schedule 不存在 |
| **错题联动** | `test_wrong_question_auto_schedule` | 答错自动创建 schedule |
| | `test_wrong_question_auto_schedule_existing` | 已有 schedule 不重复 |
| **批量** | `test_batch_submit_review` | 批量提交 |
| | `test_batch_submit_empty` | 空列表 |
| **统计** | `test_review_stats` | 复习统计 |
| | `test_review_stats_empty` | 无数据统计 |
| **历史** | `test_review_history` | 复习历史 |
| | `test_review_history_pagination` | 分页 |
| **边界** | `test_schedule_no_questions_available` | 题库空时 |

### 测试策略

- SM-2 算法：纯函数测试，无 DB 依赖
- Service 函数：Style B（mock AsyncSession）
- 错题联动测试：需要 mock practice_service 的调用

## 10. UI 影响范围

### 新增/修改小程序页面

- `miniprogram/pages/review/` — 复习首页（今日待复习）
- `miniprogram/pages/quiz/` — 复用刷题答题页 UI
- 刷题结果页增加"加入复习调度"提示

### 复习页交互

- 显示今日待复习数量
- 开始复习 → 逐题展示（同答题页 UI）
- 提交答案后弹出评分（rating 选择：0-5）
- 显示下次复习时间
- 复习进度条

## 11. 风险与兼容性

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| SM-2 EF 衰退过快 | 高频复习 | EF 下限 1.3 保证最小间隔增长 |
| 错题大量涌入 | 复习队列堆积 | 按 next_review_at 排序，控制每日上限 |
| rating 主观性 | 复习效果偏差 | 提供清晰评分标准说明 |
| 时间戳时区 | 复习日期偏移 | 统一 UTC 存储，前端转换 |

## 12. 开发顺序

### Step 1: SM-2 算法实现

- 纯函数 `compute_sm2`
- 完整单元测试

### Step 2: 新增模型

- review_schedules 表
- review_records 表

### Step 3: 创建 review_scheduler.py

- get_today_review
- submit_review
- auto_schedule_wrong_question
- get_review_stats

### Step 4: 创建 API 端点

### Step 5: Stage 11 联动集成

- practice_service 答错时调用 auto_schedule_wrong_question

### Step 6: 测试 + 文档

## 13. 验收标准

- [ ] SM-2 算法实现正确（所有评分等级覆盖）
- [ ] 今日复习队列返回待复习题目
- [ ] 复习提交后 schedule 参数正确更新
- [ ] review_records 完整记录每次复习
- [ ] 错题自动进入复习调度
- [ ] EF 不低于 1.3
- [ ] 复习统计准确
- [ ] 新测试全部通过
- [ ] 全量测试零回归
