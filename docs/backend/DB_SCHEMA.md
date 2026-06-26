# Database Schema

> 22408AI 数据库表结构文档。所有表使用 SQLAlchemy 2.0 ORM 声明式映射。

---

## 总览

| 表名 | 用途 | 核心字段 |
|------|------|----------|
| users | 用户信息 | openid (唯一) |
| refresh_tokens | JWT 刷新令牌 | token_hash, expires_at |
| admin_users | 后台管理员 | username (唯一), 角色 RBAC |
| roles | 管理员角色 | name, display_name |
| permissions | 权限定义 | resource, action |
| role_permissions | 角色-权限多对多 | role_id, permission_id |
| audit_logs | 管理员操作审计 | operator_id, action, severity |
| subjects | 科目层级树 | code (唯一), path, level |
| admin_ai_settings | AI 解析总开关 & 月度限额 | monthly_call_limit |
| admin_ai_usage_monthly | AI 调用月度用量统计 | year_month (PK), call_count |
| admin_ai_model_configs | AI 模型配置（多 provider） | name, provider, features(JSON) |
| admin_ai_configs | AI key-value 配置 | config_key (PK), config_value |
| questions | 正式题目库 | subject, content(JSON), options(JSON), question_hash |
| question_versions | 题目编辑历史版本 | question_id + version 唯一约束 |
| question_imports | 导入暂存区 | batch_id, status(pending/approved/rejected), question_hash, duplicate_status, AI 辅助导题字段 |
| wrong_questions | 错题记录（不含 SM-2 字段，P2-2 已移除） | review_count, mastered |
| review_schedules | 复习调度（SM-2 独立表） | ease_factor, interval, next_review_at |
| review_records | 复习历史记录 | rating, interval_before/after |
| practice_records | 练习记录（每题一条） | user_answer, is_correct, used_time |
| answer_behaviors | 答题行为明细 | time_spent, switch_count, is_correct |
| ai_chats | AI 对话记录 | session_type, tokens_used, duration_ms |
| ai_generation_logs | AI 生成日志（OCR/标准化等） | action, model, tokens_used, parsed_result(JSON) |
| tags | 知识点标签 | name, subject, parent_id |
| import_pipelines | PDF/图片导入 Pipeline | status, chunk_size, watermark_snapshot |
| import_pipeline_chunks | Pipeline 分片执行结果 | chunk_index, page_start/end, status |
| import_batch_jobs | 批量图片导入任务 | job_id, request_id(唯一索引), status |
| import_batch_job_items | 批量导入单图执行结果 | seq, ocr_raw_text, review_batch_id |
| batch_job_trace_events | 批量导入追踪事件日志 | seq (per-job monotonic), step, status |
| pomodoro_sessions | 番茄钟会话 | preset, work_duration, status, notification 字段 |
| watermark_rules | PDF 水印过滤规则 | pattern, rule_type, is_active |
| app_user_admin_bindings | 小程序用户-管理员绑定 | user_id (唯一), admin_user_id (唯一) |

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
    is_banned: bool     # 是否封禁，默认 False
    banned_reason: str? # 封禁原因
    banned_at: datetime?
    banned_by: int?     # FK → admin_users.id
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
| is_banned | Boolean | NOT NULL, default=False |
| banned_reason | String(256) | NULLABLE |
| banned_at | DateTime | NULLABLE |
| banned_by | Integer | FK(admin_users.id), NULLABLE |
| created_at | DateTime | server_default=now() |
| updated_at | DateTime | server_default=now(), onupdate |

---

## refresh_tokens

```python
class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: int           # PK
    user_id: int      # FK → users.id（索引）
    token_hash: str   # 令牌哈希（唯一、索引）
    expires_at: datetime
    revoked_at: datetime?
    created_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| user_id | Integer | FK(users.id), NOT NULL, INDEX |
| token_hash | String(64) | UNIQUE, NOT NULL, INDEX |
| expires_at | DateTime | NOT NULL |
| revoked_at | DateTime | NULLABLE |
| created_at | DateTime | server_default=now() |

---

## admin_users / roles / permissions

### roles

```python
class Role(Base):
    __tablename__ = "roles"

    id: int           # PK
    name: str         # 角色名（唯一、索引）
    display_name: str
    description: str?
    is_system: bool   # 系统内置角色，默认 False
    created_at: datetime
    updated_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| name | String(64) | UNIQUE, NOT NULL, INDEX |
| display_name | String(64) | NOT NULL |
| description | Text | NULLABLE |
| is_system | Boolean | NOT NULL, default=False |
| created_at | DateTime | server_default=now() |
| updated_at | DateTime | server_default=now(), onupdate |

### permissions

```python
class Permission(Base):
    __tablename__ = "permissions"

    id: int           # PK
    name: str         # 完整权限名（唯一、索引）
    resource: str     # 资源类型（索引）
    action: str       # 操作：read / write / admin
    category: str     # 分类（索引）
    description: str?
    created_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| name | String(128) | UNIQUE, NOT NULL, INDEX |
| resource | String(64) | NOT NULL, INDEX |
| action | String(64) | NOT NULL |
| category | String(32) | NOT NULL, INDEX |
| description | String(256) | NULLABLE |
| created_at | DateTime | server_default=now() |

### role_permissions

```python
class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: int       # PK, FK → roles.id (CASCADE)
    permission_id: int # PK, FK → permissions.id (CASCADE)
    granted_at: datetime
    granted_by: int?   # FK → admin_users.id
```

| 字段 | 类型 | 约束 |
|------|------|------|
| role_id | Integer | PK, FK(roles.id, ondelete=CASCADE) |
| permission_id | Integer | PK, FK(permissions.id, ondelete=CASCADE), INDEX |
| granted_at | DateTime | server_default=now() |
| granted_by | Integer | FK(admin_users.id), NULLABLE |

### admin_users

```python
class AdminUser(Base):
    __tablename__ = "admin_users"

    id: int           # PK
    username: str     # 用户名（唯一、索引）
    password_hash: str
    display_name: str?
    email: str?       # 唯一
    is_active: bool   # 默认 True
    role_id: int      # FK → roles.id
    last_login_at: datetime?
    last_login_ip: str?
    created_at: datetime
    updated_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| username | String(64) | UNIQUE, NOT NULL, INDEX |
| password_hash | String(256) | NOT NULL |
| display_name | String(64) | NULLABLE |
| email | String(128) | UNIQUE, NULLABLE |
| is_active | Boolean | NOT NULL, default=True |
| role_id | Integer | FK(roles.id), NOT NULL, INDEX |
| last_login_at | DateTime | NULLABLE |
| last_login_ip | String(45) | NULLABLE |
| created_at | DateTime | server_default=now() |
| updated_at | DateTime | server_default=now(), onupdate |

### audit_logs

```python
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: int             # PK (BigInteger, SQLite 回退 Integer)
    operator_id: int?   # FK → admin_users.id（索引）
    operator_name: str? # 操作时快照
    action: str         # 操作名（索引）
    resource_type: str?
    resource_id: str?
    severity: str       # normal / warning / critical（索引）
    detail: dict?       # JSON
    ip: str?
    user_agent: str?
    status: str         # success / failure
    error_message: str?
    created_at: datetime（索引）
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | BigInteger(SQLite: Integer) | PK, autoincrement |
| operator_id | Integer | FK(admin_users.id), NULLABLE, INDEX |
| operator_name | String(64) | NULLABLE |
| action | String(128) | NOT NULL, INDEX |
| resource_type | String(64) | NULLABLE |
| resource_id | String(64) | NULLABLE |
| severity | String(16) | NOT NULL, default="normal", INDEX |
| detail | JSON | NULLABLE |
| ip | String(45) | NULLABLE |
| user_agent | String(256) | NULLABLE |
| status | String(16) | NOT NULL, default="success" |
| error_message | Text | NULLABLE |
| created_at | DateTime | server_default=now(), INDEX |

### subjects

```python
class Subject(Base):
    __tablename__ = "subjects"

    id: int           # PK
    parent_id: int?   # FK → subjects.id（自引用）
    code: str         # 科目代码（唯一、索引）
    name: str
    level: int        # 层级，默认 1
    path: str         # 路径（索引）
    sort_order: int
    is_active: bool   # 默认 True
    created_at: datetime
    updated_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| parent_id | Integer | FK(subjects.id), NULLABLE, INDEX |
| code | String(32) | UNIQUE, NOT NULL, INDEX |
| name | String(64) | NOT NULL |
| level | SmallInteger | NOT NULL, default=1 |
| path | String(128) | NOT NULL, INDEX |
| sort_order | Integer | NOT NULL, default=0 |
| is_active | Boolean | NOT NULL, default=True |
| created_at | DateTime | server_default=now() |
| updated_at | DateTime | server_default=now(), onupdate |

---

## Admin AI 配置

### admin_ai_settings

```python
class AdminAISettings(Base):
    __tablename__ = "admin_ai_settings"

    id: int                # PK
    ai_parse_enabled: bool # 默认 True
    monthly_call_limit: int
    updated_by: int?       # FK → admin_users.id
    updated_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| ai_parse_enabled | Boolean | NOT NULL, default=True |
| monthly_call_limit | Integer | NOT NULL |
| updated_by | Integer | FK(admin_users.id), NULLABLE |
| updated_at | DateTime | server_default=now(), onupdate |

### admin_ai_usage_monthly

```python
class AdminAIUsageMonthly(Base):
    __tablename__ = "admin_ai_usage_monthly"

    year_month: str    # PK, 格式 "YYYY-MM"
    call_count: int
    limit_snapshot: int?
    created_at: datetime
    updated_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| year_month | String(7) | PK |
| call_count | Integer | NOT NULL, default=0 |
| limit_snapshot | Integer | NULLABLE |
| created_at | DateTime | server_default=now() |
| updated_at | DateTime | server_default=now(), onupdate |

### admin_ai_model_configs

```python
class AdminAiModelConfig(Base):
    __tablename__ = "admin_ai_model_configs"

    id: int              # PK
    name: str            # 标识名（唯一）
    display_name: str
    provider: str        # deepseek / openai / etc
    api_base_url: str?
    api_key_encrypted: str?  # Fernet 加密
    is_enabled: bool     # 默认 True
    is_default: bool     # 默认 False
    sort_order: int
    feature: str?        # 旧字段（单 feature，向后兼容）
    features: list?      # JSON 数组，多 feature 支持
    created_at: datetime
    updated_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| name | String(64) | UNIQUE, NOT NULL |
| display_name | String(64) | NOT NULL |
| provider | String(32) | NOT NULL |
| api_base_url | String(256) | NULLABLE |
| api_key_encrypted | String(512) | NULLABLE |
| is_enabled | Boolean | NOT NULL, default=True |
| is_default | Boolean | NOT NULL, default=False |
| sort_order | Integer | NOT NULL, default=0 |
| feature | String(32) | NULLABLE |
| features | JSON | NULLABLE |
| created_at | DateTime | server_default=now() |
| updated_at | DateTime | server_default=now(), onupdate |

### admin_ai_configs

```python
class AdminAiConfig(Base):
    __tablename__ = "admin_ai_configs"

    config_key: str   # PK
    config_value: str
    updated_by: int?
    updated_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| config_key | String(64) | PK |
| config_value | Text | NOT NULL, default="" |
| updated_by | Integer | NULLABLE |
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
    question_hash: str?        # Level 1 完全重复检测 hash（MD5，32 位）
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
    sync_uuid: str?            # 增量同步 UUID（唯一、索引）
    sync_version: int          # 增量同步版本号
    created_at: datetime
    updated_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| subject | String(32) | NOT NULL, INDEX |
| question_type | String(32) | NOT NULL, default="choice" |
| content | JSON | NOT NULL |
| options | JSON | NULLABLE |
| answer | Text | NOT NULL |
| question_hash | String(32) | NULLABLE, INDEX；subject + question_hash 用于发布/审核通过阶段完全重复拦截 |
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
| sync_uuid | String(36) | NULLABLE, UNIQUE, INDEX；增量同步用 |
| sync_version | Integer | NOT NULL, default=0 |
| created_at | DateTime | server_default=now() |
| updated_at | DateTime | server_default=now(), onupdate |

### question_versions

```python
class QuestionVersion(Base):
    __tablename__ = "question_versions"

    id: int                # PK (BigInteger, SQLite 回退 Integer)
    question_id: int       # FK → questions.id（索引）
    version: int
    content: dict          # JSON
    options: dict?         # JSON
    answer: str
    analysis: str?
    difficulty: int
    knowledge_points: dict? # JSON
    edited_by: int         # FK → admin_users.id（索引）
    edit_reason: str?
    created_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | BigInteger(SQLite: Integer) | PK, autoincrement |
| question_id | Integer | NOT NULL, INDEX |
| version | Integer | NOT NULL |
| content | JSON | NOT NULL |
| options | JSON | NULLABLE |
| answer | Text | NOT NULL |
| analysis | Text | NULLABLE |
| difficulty | SmallInteger | NOT NULL |
| knowledge_points | JSON | NULLABLE |
| edited_by | Integer | FK(admin_users.id), NOT NULL, INDEX |
| edit_reason | Text | NULLABLE |
| created_at | DateTime | server_default=now() |

**唯一约束**: `(question_id, version)` — `uq_question_versions_question_version`

---

## question_imports

```python
class QuestionImport(Base):
    __tablename__ = "question_imports"

    id: int              # PK
    batch_id: str        # 批次 ID（索引）
    source_type: str     # excel / pdf / image / ai 等来源
    source_file: str?    # 源文件名
    subject: str?        # 解析结果
    question_type: str?
    raw_data: dict       # JSON: 原始行数据
    parsed_content: dict?    # JSON: 结构化内容
    parsed_options: dict?    # JSON: 结构化选项
    parsed_answer: str?      # 解析后答案
    parsed_analysis: str?    # 解析后解析
    question_hash: str?      # Level 1 去重 hash（MD5，32 位）
    duplicate_status: str    # normal / possible_duplicate
    duplicate_of_question_id: int?  # 命中的正式题目 ID
    duplicate_of_import_id: int?    # 命中的同批/暂存导入题 ID
    status: str          # pending / approved / rejected（索引）
    review_note: str?    # 审批备注
    question_id: int?    # 审批后关联的 question id
    reject_reason: str?
    reviewed_by: int?
    reviewed_at: datetime?
    # AI 辅助导题字段（仍需人工审核后才能入库）
    ai_generated: bool
    ai_source: str?
    ai_confidence: float?
    ai_metadata: dict?
    ai_raw_response: str?
    ai_reviewed_at: datetime?
    ai_answer_flag: bool
    # 数学公式图片化
    math_regions: dict?
    created_at: datetime
    updated_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| batch_id | String(64) | NOT NULL, INDEX |
| source_type | String(16) | NOT NULL；excel / pdf / image / ai 等来源 |
| source_file | String(256) | NULLABLE |
| subject | String(32) | NULLABLE |
| question_type | String(32) | NULLABLE |
| raw_data | JSON | NOT NULL |
| parsed_content | JSON | NULLABLE |
| parsed_options | JSON | NULLABLE |
| parsed_answer | Text | NULLABLE |
| parsed_analysis | Text | NULLABLE |
| question_hash | String(32) | NULLABLE, INDEX |
| duplicate_status | String(32) | NOT NULL, default="normal", INDEX；`normal` / `possible_duplicate` |
| duplicate_of_question_id | BigInteger | NULLABLE；命中的正式题目 ID |
| duplicate_of_import_id | BigInteger | NULLABLE；命中的暂存导入题 ID |
| status | String(16) | NOT NULL, default="pending", INDEX |
| review_note | Text | NULLABLE |
| question_id | BigInteger | NULLABLE |
| reject_reason | Text | NULLABLE |
| reviewed_by | Integer | NULLABLE |
| reviewed_at | DateTime | NULLABLE |
| ai_generated | Boolean | NOT NULL, default=False；AI 辅助生成/补全标记，仍需人工审核 |
| ai_source | String(32) | NULLABLE |
| ai_confidence | Float | NULLABLE |
| ai_metadata | JSON | NULLABLE |
| ai_raw_response | Text | NULLABLE |
| ai_reviewed_at | DateTime | NULLABLE |
| ai_answer_flag | Boolean | NOT NULL, default=False |
| math_regions | JSON | NULLABLE；数学公式图片化区域信息 |
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
    mastered: bool          # 是否已掌握
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
| created_at | DateTime | server_default=now() |
| updated_at | DateTime | server_default=now(), onupdate |

### 变更记录

> P2-2 已移除 SM-2 兼容字段（efactor / interval / repetitions / next_review_date / quality）。
> 复习调度参数仅由 ReviewSchedule 持有，不再冗余存储于 WrongQuestion。

---

## review_schedules / review_records

独立的复习调度表。**复习调度的唯一主数据源**。WrongQuestion 不再持有 SM-2 字段（P2-2 已移除）。

### review_schedules

```python
class ReviewSchedule(Base):
    __tablename__ = "review_schedules"

    id: int                # PK
    user_id: int           # FK → users.id（索引）
    question_id: int       # FK → questions.id
    subject: str?
    interval: int          # 当前间隔（天），默认 0
    ease_factor: float     # 难度因子，默认 2.5
    repetitions: int       # 连续正确次数，默认 0
    next_review_at: datetime?
    last_reviewed_at: datetime?
    mastered: bool         # 默认 False
    created_at: datetime
    updated_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| user_id | Integer | FK(users.id), NOT NULL, INDEX |
| question_id | Integer | FK(questions.id), NOT NULL |
| subject | String(16) | NULLABLE |
| interval | Integer | default=0 |
| ease_factor | Float | default=2.5 |
| repetitions | Integer | default=0 |
| next_review_at | DateTime | NULLABLE |
| last_reviewed_at | DateTime | NULLABLE |
| mastered | Boolean | default=False |
| created_at | DateTime | server_default=now() |
| updated_at | DateTime | server_default=now(), onupdate |

### review_records

```python
class ReviewRecord(Base):
    __tablename__ = "review_records"

    id: int                 # PK
    user_id: int            # FK → users.id（索引）
    question_id: int        # FK → questions.id
    schedule_id: int?       # FK → review_schedules.id
    rating: int             # 用户评分 0-5（0=完全不会，5=完美回忆）
    interval_before: int?   # 复习前间隔
    interval_after: int?    # 复习后间隔
    ease_factor_before: float?
    ease_factor_after: float?
    reviewed_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| user_id | Integer | FK(users.id), NOT NULL, INDEX |
| question_id | Integer | FK(questions.id), NOT NULL |
| schedule_id | Integer | FK(review_schedules.id), NULLABLE |
| rating | Integer | NOT NULL |
| interval_before | Integer | NULLABLE |
| interval_after | Integer | NULLABLE |
| ease_factor_before | Float | NULLABLE |
| ease_factor_after | Float | NULLABLE |
| reviewed_at | DateTime | server_default=now() |

---

## practice_records

```python
class PracticeRecord(Base):
    __tablename__ = "practice_records"

    id: int                 # PK
    user_id: int            # FK → users.id（索引）
    question_id: int        # FK → questions.id（索引）
    subject: str            # math2 / exam408 / english
    question_type: str      # choice / fill / subjective
    user_answer: str        # 用户提交的答案（Text）
    is_correct: bool        # 是否正确
    used_time: int?         # 耗时（秒），可为空
    answered_at: datetime   # 答题时间
    created_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| user_id | Integer | FK(users.id), NOT NULL, INDEX |
| question_id | Integer | FK(questions.id), NOT NULL, INDEX |
| subject | String(32) | NOT NULL |
| question_type | String(32) | NOT NULL, default="choice" |
| user_answer | Text | NOT NULL |
| is_correct | Boolean | NOT NULL |
| used_time | Integer | NULLABLE |
| answered_at | DateTime | server_default=now() |
| created_at | DateTime | server_default=now() |

### 索引

- `(user_id, answered_at)` — 用户刷题历史查询（`user_id` 单独索引 + `answered_at` 排序）
- `(user_id, is_correct)` — 正确率统计（`is_correct` 参与 `CASE WHEN` 聚合）
- `(question_id, user_id)` — 查询用户是否做过某题

### 设计说明

每条记录对应一道题的**一次作答**。用户对同一道题多次作答会产生多条记录（如错题重做），
通过 `question_id + user_id` 可查询用户对该题的全部作答历史。

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

## ai_generation_logs

```python
class AiGenerationLog(Base):
    __tablename__ = "ai_generation_logs"

    id: int             # PK
    user_id: int        # 用户 ID（索引）
    action: str         # 操作类型（索引）
    target_type: str?   # 目标类型
    target_id: int?     # 目标 ID
    batch_id: str?      # 批次 ID（索引）
    prompt_text: str?   # 请求 Prompt
    raw_response: str?  # AI 原始响应
    parsed_result: dict? # JSON: 解析后结果
    confidence: float?  # AI 置信度
    model: str          # 模型名
    tokens_used: int
    duration_ms: int
    success: int        # 0/1
    error_message: str?
    created_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| user_id | Integer | NOT NULL, INDEX |
| action | String(32) | NOT NULL, INDEX |
| target_type | String(32) | NULLABLE |
| target_id | Integer | NULLABLE |
| batch_id | String(64) | NULLABLE, INDEX |
| prompt_text | Text | NULLABLE |
| raw_response | Text | NULLABLE |
| parsed_result | JSON | NULLABLE |
| confidence | Float | NULLABLE |
| model | String(64) | default="deepseek-chat" |
| tokens_used | Integer | default=0 |
| duration_ms | Integer | default=0 |
| success | Integer | default=1 |
| error_message | Text | NULLABLE |
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
    sync_uuid: str?      # 增量同步 UUID（唯一、索引）
    created_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| name | String(64) | NOT NULL |
| subject | String(16) | NOT NULL, INDEX |
| parent_id | Integer | NULLABLE, default=None |
| sort_order | Integer | default=0 |
| sync_uuid | String(36) | NULLABLE, UNIQUE, INDEX |
| created_at | DateTime | server_default=now() |

---

## import_pipelines / import_pipeline_chunks

PDF/图片导入 Pipeline checkpoint 表（P2-1）。进程重启/内存清理后仍可查询历史 pipeline，
中途失败时按 chunk 粒度断点恢复。

### import_pipelines

```python
class ImportPipeline(Base):
    __tablename__ = "import_pipelines"

    pipeline_id: str        # PK
    source_type: str        # pdf / image
    source_file: str?
    total_pages: int?
    chunk_size: int         # 默认 40
    status: str             # running / paused / completed / failed（索引）
    created_by: str?        # 创建者 openid（索引），用于 resume 校验
    source_sha256: str?     # 源文件哈希，用于 resume 校验
    watermark_snapshot: list|dict?  # JSON: 导入时水印规则快照
    error_message: str?
    started_at: datetime
    updated_at: datetime
    finished_at: datetime?
```

| 字段 | 类型 | 约束 |
|------|------|------|
| pipeline_id | String(64) | PK |
| source_type | String(16) | NOT NULL |
| source_file | String(256) | NULLABLE |
| total_pages | Integer | NULLABLE |
| chunk_size | Integer | NOT NULL, default=40 |
| status | String(16) | NOT NULL, default="running", INDEX |
| created_by | String(64) | NULLABLE, INDEX |
| source_sha256 | String(64) | NULLABLE |
| watermark_snapshot | JSON | NULLABLE |
| error_message | Text | NULLABLE |
| started_at | DateTime | NOT NULL, server_default=now() |
| updated_at | DateTime | NOT NULL, server_default=now(), onupdate |
| finished_at | DateTime | NULLABLE |

### import_pipeline_chunks

```python
class ImportPipelineChunk(Base):
    __tablename__ = "import_pipeline_chunks"

    id: int               # PK
    pipeline_id: str      # FK → import_pipelines.pipeline_id（索引）
    chunk_index: int
    page_start: int
    page_end: int
    status: str           # pending / processing / completed / failed（索引）
    batch_id: str?        # 子导入批次 ID
    question_count: int
    error_message: str?
    started_at: datetime?
    finished_at: datetime?
    created_at: datetime
    updated_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| pipeline_id | String(64) | FK(import_pipelines.pipeline_id), NOT NULL, INDEX |
| chunk_index | Integer | NOT NULL |
| page_start | Integer | NOT NULL |
| page_end | Integer | NOT NULL |
| status | String(16) | NOT NULL, default="pending", INDEX |
| batch_id | String(64) | NULLABLE |
| question_count | Integer | NOT NULL, default=0 |
| error_message | Text | NULLABLE |
| started_at | DateTime | NULLABLE |
| finished_at | DateTime | NULLABLE |
| created_at | DateTime | NOT NULL, server_default=now() |
| updated_at | DateTime | NOT NULL, server_default=now(), onupdate |

**唯一约束**: `(pipeline_id, chunk_index)` — `uq_pipeline_chunks_pipeline_index`

---

## import_batch_jobs / import_batch_job_items / batch_job_trace_events

多图片批量导入任务模型。每张图片独立走完整流水线，共享同一 `ImportBatchJob` 任务状态。

### import_batch_jobs

```python
class ImportBatchJob(Base):
    __tablename__ = "import_batch_jobs"
    __table_args__ = (
        Index("ix_import_batch_jobs_request_id", "request_id", unique=True),
    )

    job_id: str           # PK
    request_id: str?      # 请求幂等 ID（唯一索引，并发重复保护）
    source_type: str      # image（预留 pdf）
    subject: str?
    total: int            # 图片总数
    concurrency: int      # 并发数，默认 2
    status: str           # queued / running / completed / failed（索引）
    created_by: str?      # 创建者 openid（索引）
    error_message: str?
    started_at: datetime
    updated_at: datetime
    finished_at: datetime?
    next_event_seq: int   # 原子事件序号计数器，默认 1
```

| 字段 | 类型 | 约束 |
|------|------|------|
| job_id | String(64) | PK |
| request_id | String(64) | NULLABLE, UNIQUE INDEX（ix_import_batch_jobs_request_id） |
| source_type | String(16) | NOT NULL, default="image" |
| subject | String(32) | NULLABLE |
| total | Integer | NOT NULL, default=0 |
| concurrency | Integer | NOT NULL, default=2 |
| status | String(16) | NOT NULL, default="queued", INDEX |
| created_by | String(64) | NULLABLE, INDEX |
| error_message | Text | NULLABLE |
| started_at | DateTime | NOT NULL, server_default=now() |
| updated_at | DateTime | NOT NULL, server_default=now(), onupdate |
| finished_at | DateTime | NULLABLE |
| next_event_seq | Integer | NOT NULL, default=1 |

### import_batch_job_items

```python
class ImportBatchJobItem(Base):
    __tablename__ = "import_batch_job_items"

    id: int               # PK
    job_id: str           # FK → import_batch_jobs.job_id（索引）
    seq: int              # 序号
    source_file: str?
    batch_import_id: str? # 幂等/追踪标识
    image_import_id: str?
    request_id: str?
    status: str           # pending / processing / succeeded / failed（索引）
    ocr_raw_text: str?    # OCR 原始文本缓存
    ocr_cleaned_text: str?# OCR 清洗后文本
    review_batch_id: str? # 对应 review batch ID
    pipeline_id: str?
    question_count: int
    error_message: str?
    started_at: datetime?
    finished_at: datetime?
    created_at: datetime
    updated_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| job_id | String(64) | FK(import_batch_jobs.job_id), NOT NULL, INDEX |
| seq | Integer | NOT NULL |
| source_file | String(256) | NULLABLE |
| batch_import_id | String(64) | NULLABLE |
| image_import_id | String(64) | NULLABLE |
| request_id | String(64) | NULLABLE |
| status | String(16) | NOT NULL, default="pending", INDEX |
| ocr_raw_text | Text | NULLABLE |
| ocr_cleaned_text | Text | NULLABLE |
| review_batch_id | String(64) | NULLABLE |
| pipeline_id | String(64) | NULLABLE |
| question_count | Integer | NOT NULL, default=0 |
| error_message | Text | NULLABLE |
| started_at | DateTime | NULLABLE |
| finished_at | DateTime | NULLABLE |
| created_at | DateTime | NOT NULL, server_default=now() |
| updated_at | DateTime | NOT NULL, server_default=now(), onupdate |

**唯一约束**: `(job_id, seq)` — `uq_batch_job_items_job_seq`；`(batch_import_id, image_import_id)` — `uq_batch_import_id_image`

### batch_job_trace_events

Append-only trace event log。增量读取使用 `id`（auto-increment PK），
`seq` 是向后兼容字段（job 级事件仍依赖 `next_event_seq` 递增）。

```python
class BatchJobTraceEvent(Base):
    __tablename__ = "batch_job_trace_events"

    id: int               # PK（增量读取依据）
    job_id: str           # FK → import_batch_jobs.job_id（索引）
    item_seq: int?        # None = job 级事件
    request_id: str?
    image_import_id: str?
    batch_import_id: str?
    seq: int              # 向后兼容字段（job 级事件使用）
    step: str             # upload / ocr / pipeline / merge / done / error
    status: str           # running / success / failed
    message: str
    duration_ms: int?
    created_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement（增量读取依据） |
| job_id | String(64) | FK(import_batch_jobs.job_id), NOT NULL, INDEX |
| item_seq | Integer | NULLABLE |
| request_id | String(64) | NULLABLE |
| image_import_id | String(64) | NULLABLE |
| batch_import_id | String(64) | NULLABLE |
| seq | Integer | NOT NULL（向后兼容字段；job 级事件使用） |
| step | String(32) | NOT NULL |
| status | String(16) | NOT NULL |
| message | String(512) | NOT NULL, default="" |
| duration_ms | Integer | NULLABLE |
| created_at | DateTime | NOT NULL, server_default=now() |

**唯一约束**: `(job_id, seq)` — `uq_trace_events_job_seq`

---

## pomodoro_sessions

```python
class PomodoroSession(Base):
    __tablename__ = "pomodoro_sessions"

    id: int                 # PK
    user_id: int            # FK → users.id（索引）
    subject: str
    chapter_id: str?
    preset: str             # standard / custom
    work_duration: int      # 工作时长（分钟），默认 25
    break_duration: int     # 休息时长（分钟），默认 5
    start_time: datetime
    end_time: datetime?
    expected_end_time: datetime? # 索引
    actual_duration: int?   # 实际工作时长（秒）
    status: str             # running / paused / completed / interrupted
    notification_enabled: bool  # 是否启用订阅通知
    notification_sent: bool
    notification_sent_at: datetime?
    notification_error: str?
    openid_snapshot: str?   # 通知发送时用的 openid
    paused_at: datetime?    # 暂停时间
    created_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| user_id | Integer | FK(users.id), NOT NULL, INDEX |
| subject | String(32) | NOT NULL, default="" |
| chapter_id | String(64) | NULLABLE |
| preset | String(16) | NOT NULL, default="standard" |
| work_duration | Integer | NOT NULL, default=25 |
| break_duration | Integer | NOT NULL, default=5 |
| start_time | DateTime | NOT NULL |
| end_time | DateTime | NULLABLE |
| expected_end_time | DateTime | NULLABLE, INDEX |
| actual_duration | Integer | NULLABLE |
| status | String(16) | NOT NULL, default="running" |
| notification_enabled | Boolean | NOT NULL, default=False |
| notification_sent | Boolean | NOT NULL, default=False |
| notification_sent_at | DateTime | NULLABLE |
| notification_error | Text | NULLABLE |
| openid_snapshot | String(64) | NULLABLE |
| paused_at | DateTime | NULLABLE |
| created_at | DateTime | server_default=now() |

---

## watermark_rules

```python
class WatermarkRule(Base):
    __tablename__ = "watermark_rules"

    id: int           # PK
    pattern: str      # 水印正则模式
    rule_type: str    # regex / string
    description: str?
    is_active: bool   # 默认 True
    created_at: datetime
    updated_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| pattern | Text | NOT NULL |
| rule_type | String(16) | NOT NULL, default="regex" |
| description | String(128) | NULLABLE |
| is_active | Boolean | NOT NULL, default=True |
| created_at | DateTime | NOT NULL, server_default=now() |
| updated_at | DateTime | NOT NULL, server_default=now(), onupdate |

---

## app_user_admin_bindings

```python
class AppUserAdminBinding(Base):
    __tablename__ = "app_user_admin_bindings"

    id: int           # PK
    user_id: int      # FK → users.id（唯一、索引）
    admin_user_id: int# FK → admin_users.id（唯一、索引）
    created_by: int?  # FK → admin_users.id
    created_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| user_id | Integer | FK(users.id, ondelete=CASCADE), UNIQUE, NOT NULL, INDEX |
| admin_user_id | Integer | FK(admin_users.id, ondelete=CASCADE), UNIQUE, NOT NULL, INDEX |
| created_by | Integer | FK(admin_users.id, ondelete=SET NULL), NULLABLE |
| created_at | DateTime | server_default=now() |

**唯一约束**: `user_id` (`uq_app_user_admin_bindings_user_id`)、`admin_user_id` (`uq_app_user_admin_bindings_admin_user_id`)

---

## 设计原则

- **用户唯一标识**：微信 openid（不使用 email/username/password）
- **系统不保存密码**，不存在密码字段（管理员表除外，存 password_hash）
- `content` 为 JSON：`{"text":"...", "images":["url"], "latex":"..."}`
- `knowledge_points` 用 JSON 数组（PG 中可建 GIN 索引）
- 不拆选择题/填空题子表，用 `question_type` 区分
- `source_type` + `source_file` + `import_batch_id` 三位一体追溯来源
- Level 1 题库去重使用 `question_hash`：导入阶段只标记 `question_imports.duplicate_status`，发布/审核通过阶段按 `subject + question_hash` 完全匹配拦截，不自动删除历史题目
- AI 辅助导题/补全只写入 `question_imports` 的 AI 元数据字段，仍必须经过人工审核，不直接进入 `questions`
- `raw_content` 保留导入原始文本
- SM-2 复习调度以 `review_schedules` 为主数据源，WrongQuestion 上的 efactor/interval/repetitions/next_review_date/mastered 字段仅为历史兼容字段，不参与新版调度计算
- 每次 ReviewSchedule 更新后通过 `_sync_schedule_to_wq()` 自动回写 WrongQuestion 兼容字段
- SM-2 rating 合法范围是 0-5，其中 0 是合法评分（完全不会，重置 repetitions=0），不应抛出异常
- 自动批改未提供用户自评 rating 时默认映射：is_correct=True → rating=4，is_correct=False → rating=1
- 复习日期统一使用 `utcnow().date()`，避免服务器本地时区导致日期偏移
- 当前技术债：/review/due、/review/submit、/review/stats 等旧接口仍基于 WrongQuestion 兼容字段；后续建议迁移为统一读取 ReviewSchedule
- 每次答题一条记录（`practice_records`），每题一条，支持多次作答
- `session_type` 区分 AI 对话场景
- **RBAC 权限系统**：`admin_users` → `roles` ↔ `permissions`（多对多），所有管理操作记入 `audit_logs`
- **批量导入**：`import_batch_jobs` 管理多图片任务，`import_pipeline` 管理 PDF 分片任务，各自独立
- **番茄钟**：`pomodoro_sessions` 单表记录完整生命周期，支持微信订阅通知
- **增量同步**：`questions.sync_uuid/sync_version`、`tags.sync_uuid` 支持本地-云端增量同步

> 上次更新：2026-06-26 — review_schedules 明确为主调度数据源；补充同步机制、rating 规范、自动批改映射默认值、时区策略、技术债说明
