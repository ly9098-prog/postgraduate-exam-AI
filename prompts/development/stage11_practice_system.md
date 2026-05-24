# Stage 11: 刷题系统

## 1. 阶段目标

构建面向终端用户的刷题系统，支持顺序/随机/按科目/按章节/按知识点刷题，记录用户做题行为，自动管理错题本，提供完整的答题交互体验。

## 2. MVP 范围

### 能做

- 刷题模式：顺序刷题、随机刷题
- 按科目、按章节、按知识点筛选题目
- 用户答题提交 + 正误判定
- 答题记录持久化（practice_records）
- 错题自动加入错题本
- 错题重做
- 刷题统计（正确率、做题数、连续天数）
- 小程序刷题页面基础交互

### 禁止做

- 不做计时答题（MVP 阶段不限制单题用时）
- 不做竞赛模式
- 不做排行榜
- 不做社交分享
- 不做自定义刷题计划
- 不做题目收藏（延迟到后续迭代）

## 3. 非目标

- 不实现图片/公式渲染优化（使用现有组件）
- 不做离线刷题
- 不做答题草稿
- 不做题目举报反馈
- 不做用户间题目讨论

## 4. 目录结构修改

### 新增文件

| 文件 | 作用 |
|------|------|
| `backend/app/services/practice_service.py` | 刷题服务核心逻辑 |
| `backend/app/schemas/practice.py` | 刷题相关 Pydantic 模型 |
| `backend/tests/test_services/test_practice_service.py` | 刷题服务单元测试 |
| `miniprogram/pages/practice/` | 小程序刷题页面 |

### 修改文件

| 文件 | 修改内容 |
|------|---------|
| `backend/app/api/v1/practice.py` | 新增刷题 API 端点 |
| `backend/app/models/question.py` | 确保字段完备（可读即可） |
| `backend/app/models/practice_record.py` | 初始化已有或完善字段 |

### 不修改文件

- `app/models/user.py`
- `app/models/wrong_question.py`
- `app/features/` 下已有文件（不修改导入管线）
- `app/models/question_import.py`

## 5. 数据库变更

### 新增表：`practice_records`（已有模型，确认完备）

```python
class PracticeRecord(Base):
    """用户做题记录"""
    __tablename__ = "practice_records"

    id: int (PK, autoincrement)
    user_id: int (FK → users.id, indexed)
    question_id: int (FK → questions.id, indexed)
    subject: str (冗余字段，便于统计)
    question_type: str (冗余字段)
    user_answer: str (用户提交的答案)
    is_correct: bool (是否正确)
    used_time: int | None (用时，秒)
    answered_at: datetime (答题时间)
```

### 索引

- `(user_id, answered_at)` — 用户刷题历史查询
- `(user_id, is_correct)` — 正确率统计
- `(question_id, user_id)` — 用户是否做过某题

### 现有表：`wrong_questions`

```python
class WrongQuestion(Base):
    """错题本"""
    id, user_id (FK), question_id (FK),
    subject, question_type,
    wrong_answer, correct_answer,
    wrong_count, last_wrong_at,
    created_at, updated_at
```

### 新增字段

**WrongQuestion 暂不新增字段**，现有模型满足 MVP 需求。

## 6. API 设计

### 6.1 获取刷题列表

```
GET /api/v1/practice/questions
```

**Query Parameters:**
- `subject` (str, optional) — 科目过滤
- `chapter` (str, optional) — 章节过滤
- `knowledge_point` (str, optional) — 知识点过滤
- `mode` (str, default "random") — random / sequential
- `count` (int, default 20) — 一次获取题目数量
- `exclude_answered` (bool, default false) — 排除已做的题

**Response:**
```json
{
    "questions": [
        {
            "id": 1,
            "subject": "math2",
            "question_type": "single_choice",
            "stem": "题目内容...",
            "options": {"A": "选项A", "B": "选项B", "C": "选项C", "D": "选项D"},
            "knowledge_points": ["导数", "极限"]
        }
    ],
    "total": 100,
    "mode": "random"
}
```

**注意：不返回答案。**

### 6.2 提交答案

```
POST /api/v1/practice/submit
```

**Request Body:**
```json
{
    "question_id": 1,
    "user_answer": "A",
    "used_time": 30
}
```

**Response:**
```json
{
    "question_id": 1,
    "is_correct": true,
    "correct_answer": "A",
    "analysis": "题目解析...",
    "knowledge_points": ["导数"],
    "is_wrong_added": false
}
```

### 6.3 批量提交（连续做题模式）

```
POST /api/v1/practice/batch-submit
```

**Request Body:**
```json
{
    "answers": [
        {"question_id": 1, "user_answer": "A", "used_time": 30},
        {"question_id": 2, "user_answer": "B", "used_time": 45}
    ]
}
```

**Response:**
```json
{
    "results": [
        {"question_id": 1, "is_correct": true, "correct_answer": "A", "analysis": "..."},
        {"question_id": 2, "is_correct": false, "correct_answer": "C", "analysis": "..."}
    ],
    "total_correct": 1,
    "total_wrong": 1
}
```

### 6.4 获取刷题统计

```
GET /api/v1/practice/stats
```

**Query Parameters:**
- `subject` (str, optional) — 按科目统计
- `days` (int, default 7) — 最近 N 天

**Response:**
```json
{
    "total_answered": 150,
    "total_correct": 120,
    "accuracy": 0.8,
    "by_subject": {
        "math2": {"answered": 100, "correct": 85, "accuracy": 0.85},
        "english": {"answered": 50, "correct": 35, "accuracy": 0.7}
    },
    "daily_stats": [
        {"date": "2025-05-18", "answered": 20, "correct": 16},
        {"date": "2025-05-19", "answered": 30, "correct": 25}
    ],
    "current_streak": 3
}
```

### 6.5 获取题目详情（含答案 — 用于查看解析/复习）

```
GET /api/v1/questions/{id}/detail
```

**Response:**
```json
{
    "id": 1,
    "subject": "math2",
    "question_type": "single_choice",
    "stem": "题目内容...",
    "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
    "answer": "A",
    "analysis": "解析...",
    "knowledge_points": ["导数"]
}
```

要求：该接口仅限已答过该题的用户访问（校验 practice_records 中存在记录）。

## 7. Service 设计

### 新增：`practice_service.py`

```python
# 核心函数

async def get_practice_questions(
    db: AsyncSession,
    user_id: int,
    subject: str | None = None,
    chapter: str | None = None,
    knowledge_point: str | None = None,
    mode: str = "random",
    count: int = 20,
    exclude_answered: bool = False,
) -> dict:
    """
    获取刷题列表。

    查询 questions 表，按条件过滤。
    random 模式使用 ORDER BY RANDOM()。
    sequential 模式按 id 排序。
    exclude_answered 时排除 practice_records 中已有记录。
    """

async def submit_answer(
    db: AsyncSession,
    user_id: int,
    question_id: int,
    user_answer: str,
    used_time: int | None = None,
) -> dict:
    """
    提交答案。

    1. 查询 question，获取正确答案
    2. 判断正误（字符串比对，大小写不敏感）
    3. 写入 practice_records
    4. 若答错 → 写入/更新 wrong_questions
    5. 返回结果（是否正确、正确答案、解析）
    """

async def batch_submit_answers(
    db: AsyncSession,
    user_id: int,
    answers: list[dict],
) -> dict:
    """
    批量提交答案。

    逐条调用 submit_answer，事务内一次性提交。
    """

async def get_practice_stats(
    db: AsyncSession,
    user_id: int,
    subject: str | None = None,
    days: int = 7,
) -> dict:
    """
    获取刷题统计。

    - 总答题数 / 正确数 / 正确率
    - 按科目拆分
    - 每日答题趋势
    - 连续刷题天数（streak）
    """
```

### 辅助函数

```python
async def _get_question_for_practice(db, question_id) -> Question | None:
    """获取题目（不含答案，用于刷题展示）。"""

async def _get_question_with_answer(db, question_id) -> Question | None:
    """获取题目（含答案，用于查看解析）。"""

async def _record_practice(db, user_id, question_id, user_answer, is_correct, used_time):
    """写入 practice_records。"""

async def _update_wrong_question(db, user_id, question_id, correct_answer, user_answer):
    """更新错题本（有则增加次数，无则新建）。"""

async def _calculate_streak(db, user_id) -> int:
    """计算连续刷题天数。"""
```

### 错题管理（现有 WrongQuestion 模型使用）

```python
async def get_wrong_questions(
    db: AsyncSession,
    user_id: int,
    subject: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """
    获取错题列表，按最新犯错时间倒序。
    """

async def review_wrong_question(
    db: AsyncSession,
    user_id: int,
    question_id: int,
    is_correct: bool,
) -> dict:
    """
    错题重做。

    - 正确：减少 wrong_count 或标记已掌握
    - 错误：更新 last_wrong_at，增加 wrong_count
    """
```

## 8. Schema 设计

### 新增：`schemas/practice.py`

```python
class PracticeQuestion(BaseModel):
    """刷题用题目（不含答案）。"""
    id: int
    subject: str
    question_type: str
    stem: str
    options: dict = {}
    knowledge_points: list[str] = []


class PracticeQuestionsResponse(BaseModel):
    questions: list[PracticeQuestion]
    total: int
    mode: str


class AnswerSubmit(BaseModel):
    question_id: int
    user_answer: str
    used_time: int | None = None


class AnswerResult(BaseModel):
    question_id: int
    is_correct: bool
    correct_answer: str
    analysis: str = ""
    knowledge_points: list[str] = []
    is_wrong_added: bool = False


class AnswerSubmitResponse(BaseModel):
    question_id: int
    is_correct: bool
    correct_answer: str
    analysis: str = ""
    knowledge_points: list[str] = []
    is_wrong_added: bool = False


class BatchSubmitRequest(BaseModel):
    answers: list[AnswerSubmit]


class BatchSubmitResponse(BaseModel):
    results: list[AnswerResult]
    total_correct: int
    total_wrong: int


class DailyStats(BaseModel):
    date: str
    answered: int
    correct: int


class SubjectStats(BaseModel):
    answered: int
    correct: int
    accuracy: float


class PracticeStatsResponse(BaseModel):
    total_answered: int
    total_correct: int
    accuracy: float
    by_subject: dict[str, SubjectStats] = {}
    daily_stats: list[DailyStats] = []
    current_streak: int = 0


class QuestionDetailResponse(BaseModel):
    """含答案的题目详情（仅已答用户可访问）。"""
    id: int
    subject: str
    question_type: str
    stem: str
    options: dict = {}
    answer: str
    analysis: str = ""
    knowledge_points: list[str] = []
```

## 9. 测试计划

### 新增测试文件

`backend/tests/test_services/test_practice_service.py`

### 测试用例

| 类别 | 测试用例 | 描述 |
|------|---------|------|
| **刷题获取** | `test_get_random_questions` | 随机获取题目 |
| | `test_get_sequential_questions` | 顺序获取题目 |
| | `test_get_questions_by_subject` | 按科目过滤 |
| | `test_get_questions_by_chapter` | 按章节过滤 |
| | `test_get_questions_by_knowledge_point` | 按知识点过滤 |
| | `test_exclude_answered` | 排除已做题目 |
| | `test_empty_result` | 无符合条件的题目 |
| **答题提交** | `test_submit_correct_answer` | 正确答案 |
| | `test_submit_wrong_answer` | 错误答案 |
| | `test_submit_creates_practice_record` | 答题记录创建 |
| | `test_submit_case_insensitive` | 答案大小写不敏感 |
| | `test_used_time_optional` | 用时可选 |
| | `test_question_not_found` | 题目不存在 |
| **错题本** | `test_wrong_answer_adds_to_wrong` | 答错自动入错题本 |
| | `test_correct_answer_no_wrong` | 正确不加入错题本 |
| | `test_wrong_question_count_increment` | 同一错题计数递增 |
| | `test_wrong_question_review_correct` | 错题重做正确 |
| | `test_wrong_question_review_wrong_again` | 错题再次做错 |
| **批量提交** | `test_batch_submit` | 批量提交 |
| | `test_batch_submit_mixed` | 混合对错 |
| | `test_batch_submit_empty` | 空列表 |
| **统计** | `test_practice_stats` | 刷题统计 |
| | `test_practice_stats_by_subject` | 分科目统计 |
| | `test_practice_stats_empty` | 无数据统计 |
| | `test_streak_calculation` | 连续天数计算 |
| **题目详情** | `test_get_detail_answered_user` | 已答用户获取详情 |
| | `test_get_detail_unanswered_user` | 未答用户被拒绝 |
| **边界** | `test_concurrent_submit` | 并发提交 |
| | `test_submit_nonexistent_question` | 提交不存在的题目 |

### 测试策略

- Style B（mock AsyncSession）：逻辑测试
- Style A（真实 SQLite + SQLAlchemy）：数据完整性测试
- 错题本逻辑需 mock 或使用真实 WrongQuestion 模型

## 10. UI 影响范围

### 新增小程序页面

```
miniprogram/pages/practice/
├── index/           # 刷题首页（选择科目/模式）
├── quiz/            # 答题页
├── result/          # 答题结果页
└── stats/           # 刷题统计页
```

### 页面交互

**刷题首页：**
- 科目选择（数学二 / 408 / 英语）
- 刷题模式（随机/顺序）
- 题目数量选择
- 开始刷题按钮

**答题页：**
- 题目展示（题干 + 选项）
- 选项点击选中
- 提交答案
- 答题反馈（对/错 + 显示正确答案和解析）
- 下一题按钮
- 进度指示（第 3/20 题）

**结果页：**
- 本次刷题统计（正确率、用时等）
- 查看错题
- 再来一轮

**统计页：**
- 总做题数 / 正确率
- 每日趋势图
- 科目分布
- 连续天数

## 11. 风险与兼容性

### 风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 大量刷题导致 practice_records 膨胀 | 查询性能下降 | 按月分表（MVP 阶段不做），建好索引 |
| RANDOM() 性能 | 大表随机排序慢 | 限制随机范围 + 加缓存（MVP 后优化） |
| 错题本重复 | 同题多次做错多条记录 | 按 question_id 去重，累加 wrong_count |
| 不含答案返回 | 前端额外请求 | 题库 API 和含答案 API 分离设计 |

### 向后兼容

- 现有 questions 表不变
- 现有 wrong_questions 模型不变
- 新增 API 不影响现有端点
- 仅新增表，不修改已有表

## 12. 开发顺序

### Step 1: 确认模型完备

- 检查 Question 模型字段是否满足刷题展示需求
- 检查 WrongQuestion 模型字段
- 确认 practice_records 模型（或新增）

### Step 2: 创建 practice_service.py

- 基础函数：获取刷题题目列表
- 核心函数：提交答案 + 判正误
- 错题本同步逻辑
- 统计函数

### Step 3: 创建 schemas/practice.py

- 定义所有请求/响应模型

### Step 4: 新增 API 端点

- 注册路由到 `app/api/v1/practice.py`
- 实现 5 个端点

### Step 5: 测试

- 编写全部测试用例
- 全量回归测试

### Step 6: 小程序刷题页面

- 刷题首页
- 答题页
- 结果页
- 统计页

### Step 7: 文档更新

- 更新 `/docs/api/`
- 更新 `/docs/database/`
- 更新 `/docs/frontend/`
- 更新 changelog

## 13. 验收标准

- [ ] 随机/顺序刷题可用
- [ ] 按科目/章节/知识点过滤正常
- [ ] 答题提交后正确记录 practice_records
- [ ] 答案判断正确（大小写不敏感）
- [ ] 答错自动加入错题本（不重复）
- [ ] 错题重做功能正常
- [ ] 刷题统计返回正确
- [ ] 连续天数计算准确
- [ ] 含答案接口仅限已答用户访问
- [ ] 新测试全部通过
- [ ] 全量测试零回归
- [ ] 小程序刷题页可流畅交互
