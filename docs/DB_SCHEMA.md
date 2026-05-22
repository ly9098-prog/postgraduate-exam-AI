# Database Schema

> 2240AI 数据库表结构文档。所有表使用 SQLAlchemy 2.0 ORM 声明式映射。

---

## 总览

| 表名 | 用途 | 核心字段 |
|------|------|----------|
| users | 用户信息 | openid (唯一) |
| questions | 正式题目库 | subject, content(JSON), options(JSON) |
| question_imports | 导入暂存区 | batch_id, status(pending/approved/rejected) |
| wrong_questions | 错题记录 + SM-2 调度字段 | efactor, interval, repetitions, next_review_date |
| practice_records | 练习记录 | question_ids(JSON), answers(JSON) |
| answer_behaviors | 答题行为明细 | time_spent, switch_count, is_correct |
| review_plans | 复习计划（预留） | (表结构待创建) |
| ai_chats | AI 对话记录 | session_type, tokens_used, duration_ms |
| tags | 知识点标签 | name, subject, parent_id |

---

## users

```python
class User(Base):
    __tablename__ = "users"

    id: int             # PK
    openid: str         # 微信 openid（唯一、索引）
    session_key: str?   # 微信 session_key
    nickname: str?      # 微信昵称
    avatar_url: str?    # 微信头像 URL
    created_at: datetime
    updated_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| openid | String(64) | UNIQUE, NOT NULL, INDEX |
| session_key | String(256) | NULLABLE |
| nickname | String(64) | NULLABLE |
| avatar_url | String(256) | NULLABLE |
| created_at | DateTime | server_default=now() |
| updated_at | DateTime | server_default=now(), onupdate |

---

## questions

```python
class Question(Base):
    __tablename__ = "questions"

    id: int                    # PK
    subject: str               # math2 / exam408 / english（索引）
    question_type: str         # choice / fill / subjective
    content: dict              # JSON: {"text":"...", "images":["url"], "latex":"..."}
    options: dict?             # JSON: {"A":"...", "B":"..."}
    answer: str                # 标准答案（Text 类型，支持长答案）
    analysis: str?             # 解析
    knowledge_points: list?    # JSON 数组: ["导数", "求导公式"]
    difficulty: int            # 1-5，默认 3
    source: str?               # 来源
    source_type: str?          # excel / pdf / manual
    source_file: str?          # 源文件名
    import_batch_id: str?      # 导入批次 ID
    raw_content: str?          # 导入原始文本
    image_url: list?           # JSON: ["url1"]
    year: int?                 # 真题年份
    review_status: str         # 默认 "approved"
    is_active: bool            # 逻辑删除，默认 True
    created_at: datetime
    updated_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| subject | String(16) | NOT NULL, INDEX |
| question_type | String(32) | NOT NULL, default="choice" |
| content | JSON | NOT NULL |
| options | JSON | NULLABLE |
| answer | Text | NOT NULL |
| analysis | Text | NULLABLE |
| knowledge_points | JSON | NULLABLE |
| difficulty | SmallInteger | default=3 |
| source | String(64) | NULLABLE |
| source_type | String(16) | NULLABLE |
| source_file | String(256) | NULLABLE |
| import_batch_id | String(64) | NULLABLE |
| raw_content | Text | NULLABLE |
| image_url | JSON | NULLABLE |
| year | SmallInteger | NULLABLE |
| review_status | String(16) | default="approved" |
| is_active | Boolean | default=True |
| created_at | DateTime | server_default=now() |
| updated_at | DateTime | server_default=now(), onupdate |

---

## question_imports

```python
class QuestionImport(Base):
    __tablename__ = "question_imports"

    id: int              # PK
    batch_id: str        # 批次 ID（索引）
    source_type: str     # excel / pdf
    source_file: str?    # 源文件名
    subject: str?        # 解析结果
    question_type: str?
    raw_data: dict       # JSON: 原始行数据
    parsed_content: dict?    # JSON: 结构化内容
    parsed_options: dict?    # JSON: 结构化选项
    parsed_answer: str?      # 解析后答案
    parsed_analysis: str?    # 解析后解析
    status: str          # pending / approved / rejected（索引）
    review_note: str?    # 审批备注
    question_id: int?    # 审批后关联的 question id
    created_at: datetime
    updated_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| batch_id | String(64) | NOT NULL, INDEX |
| source_type | String(16) | NOT NULL |
| source_file | String(256) | NULLABLE |
| subject | String(16) | NULLABLE |
| question_type | String(32) | NULLABLE |
| raw_data | JSON | NOT NULL |
| parsed_content | JSON | NULLABLE |
| parsed_options | JSON | NULLABLE |
| parsed_answer | Text | NULLABLE |
| parsed_analysis | Text | NULLABLE |
| status | String(16) | NOT NULL, default="pending", INDEX |
| review_note | Text | NULLABLE |
| question_id | BigInteger | NULLABLE |
| created_at | DateTime | server_default=now() |
| updated_at | DateTime | server_default=now(), onupdate |

---

## wrong_questions

```python
class WrongQuestion(Base):
    __tablename__ = "wrong_questions"

    id: int                 # PK
    user_id: int            # FK → users.id（索引）
    question_id: int        # FK → questions.id
    wrong_answer: str?      # 用户错误答案
    error_type: str         # concept / calculation / careless / other
    ai_analysis: dict?      # JSON: AI 分析结果缓存
    review_count: int       # 总复习次数
    last_review_at: datetime?
    mastered: bool          # 是否已掌握，默认 False
    # SM-2 字段
    efactor: float          # 难度因子，默认 2.5
    interval: int           # 当前间隔（天），默认 0
    repetitions: int        # 连续正确次数，默认 0
    next_review_date: date? # 下次复习日期
    quality: int?           # 最近质量评分 0-5
    created_at: datetime
    updated_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| user_id | Integer | FK(users.id), NOT NULL, INDEX |
| question_id | Integer | FK(questions.id), NOT NULL |
| wrong_answer | Text | NULLABLE |
| error_type | String(32) | default="other" |
| ai_analysis | JSON | NULLABLE |
| review_count | SmallInteger | default=0 |
| last_review_at | DateTime | NULLABLE |
| mastered | Boolean | default=False |
| efactor | Float | default=2.5 |
| interval | Integer | default=0 |
| repetitions | Integer | default=0 |
| next_review_date | Date | NULLABLE |
| quality | SmallInteger | NULLABLE |
| created_at | DateTime | server_default=now() |
| updated_at | DateTime | server_default=now(), onupdate |

### SM-2 字段说明

- `efactor`：SuperMemo EF，下限 1.3
- `interval`：距下次复习天数
- `repetitions`：连续回答正确次数（quality >= 3 时递增，< 3 时归零）
- `next_review_date`：通过 `calc_sm2()` 计算的下次复习日期
- `mastered`：当 `quality >= 4` 且 `repetitions >= 3` 时自动标记

---

## practice_records

```python
class PracticeRecord(Base):
    __tablename__ = "practice_records"

    id: int                 # PK
    user_id: int            # FK → users.id（索引）
    subject: str            # math2 / exam408 / english
    mode: str               # random / review / exam
    question_ids: list      # JSON: [1, 2, 3]
    answers: dict           # JSON: {"1": "A", "2": "B"}
    correct_count: int      # 正确数
    wrong_count: int        # 错误数
    duration_sec: int       # 总耗时（秒）
    started_at: datetime    # 开始时间
    finished_at: datetime?  # 结束时间
    created_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| user_id | Integer | FK(users.id), NOT NULL, INDEX |
| subject | String(16) | NOT NULL |
| mode | String(16) | default="random" |
| question_ids | JSON | NOT NULL |
| answers | JSON | NOT NULL |
| correct_count | SmallInteger | default=0 |
| wrong_count | SmallInteger | default=0 |
| duration_sec | Integer | default=0 |
| started_at | DateTime | server_default=now() |
| finished_at | DateTime | NULLABLE |
| created_at | DateTime | server_default=now() |

---

## answer_behaviors

```python
class AnswerBehavior(Base):
    __tablename__ = "answer_behaviors"

    id: int                    # PK
    user_id: int               # FK → users.id（索引）
    question_id: int           # FK → questions.id
    practice_record_id: int?   # FK → practice_records.id

    # 答题行为
    time_spent_sec: int        # 耗时（秒），默认 0
    is_first_correct: bool?    # 首次是否答对
    is_final_correct: bool?    # 最终是否答对
    view_answer_count: int     # 查看答案次数
    switch_count: int          # 切换选项次数
    is_abandoned: bool         # 是否放弃

    # 答案
    user_answer: str?          # 用户答案
    correct_answer: str?       # 正确答案

    # 元信息
    subject: str?              # 科目
    session_type: str          # random / review / exam
    created_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| user_id | Integer | FK(users.id), NOT NULL, INDEX |
| question_id | Integer | FK(questions.id), NOT NULL |
| practice_record_id | Integer | FK(practice_records.id), NULLABLE |
| time_spent_sec | Integer | default=0 |
| is_first_correct | Boolean | NULLABLE |
| is_final_correct | Boolean | NULLABLE |
| view_answer_count | SmallInteger | default=0 |
| switch_count | SmallInteger | default=0 |
| is_abandoned | Boolean | default=False |
| user_answer | Text | NULLABLE |
| correct_answer | Text | NULLABLE |
| subject | String(16) | NULLABLE |
| session_type | String(32) | default="random" |
| created_at | DateTime | server_default=now() |

---

## ai_chats

```python
class AiChat(Base):
    __tablename__ = "ai_chats"

    id: int                   # PK
    user_id: int              # 用户 ID（索引）
    session_type: str         # error_analysis / study_advice / summary
    user_message: str         # 请求消息（Text）
    ai_response: str          # AI 响应（Text）
    context_snapshot: dict?   # JSON: 调用时上下文快照
    tokens_used: int          # token 消耗数
    model: str                # 模型名，默认 "deepseek-chat"
    duration_ms: int          # 耗时（毫秒）
    created_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| user_id | Integer | NOT NULL, INDEX |
| session_type | String(32) | NOT NULL |
| user_message | Text | NOT NULL |
| ai_response | Text | NOT NULL |
| context_snapshot | JSON | NULLABLE |
| tokens_used | Integer | default=0 |
| model | String(64) | default="deepseek-chat" |
| duration_ms | Integer | default=0 |
| created_at | DateTime | server_default=now() |

---

## tags (knowledge_points)

```python
class Tag(Base):
    __tablename__ = "tags"

    id: int              # PK
    name: str            # 标签名
    subject: str         # 科目（索引）
    parent_id: int?      # 父标签 ID（预留层级扩展，MVP 暂不使用）
    sort_order: int      # 排序，默认 0
    created_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| name | String(64) | NOT NULL |
| subject | String(16) | NOT NULL, INDEX |
| parent_id | Integer | NULLABLE, default=None |
| sort_order | Integer | default=0 |
| created_at | DateTime | server_default=now() |

---

## 设计原则

- **用户唯一标识**：微信 openid（不使用 email/username/password）
- **系统不保存密码**，不存在密码字段
- `content` 为 JSON：`{"text":"...", "images":["url"], "latex":"..."}`
- `knowledge_points` 用 JSON 数组（PG 中可建 GIN 索引）
- 不拆选择题/填空题子表，用 `question_type` 区分
- `source_type` + `source_file` + `import_batch_id` 三位一体追溯来源
- `raw_content` 保留导入原始文本
- SM-2 字段直接挂在 `WrongQuestion` 表上，不拆独立调度表
- 每次练习一条记录（`practice_records`），不拆到每题一条
- `session_type` 区分 AI 对话场景
