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
| questions | 正式题目库 | subject_id, content(JSON), options(JSON), question_hash, sync_uuid |
| question_knowledge_points | 题目-知识点关联（唯一事实源） | question_id, knowledge_point_id, role, weight, position |
| knowledge_points | 知识点主表（科目级规范化） | name, normalized_name, aliases, subject_id |
| question_versions | 题目编辑历史版本 | question_id + version 唯一约束 |
| question_imports | 导入暂存区 | batch_id, status(pending/approved/rejected), question_hash, duplicate_status, AI 辅助导题字段 |
| wrong_questions | 错题记录（不含 SM-2 字段，P2-2 已移除） | review_count, mastered |
| review_schedules | 复习调度（SM-2 独立表） | ease_factor, interval, next_review_at |
| review_records | 复习历史记录 | rating, interval_before/after |
| practice_records | 练习记录（每题一条） | subject_id, user_answer, is_correct, used_time |
| practice_sessions | 刷题会话（一组一次，幂等） | user_id + request_id 唯一, started_at/finished_at, duration_sec |
| answer_behaviors | 答题行为明细 | time_spent, switch_count, is_correct |
| ai_chats | AI 对话记录 | session_type, tokens_used, duration_ms |
| ai_generation_logs | AI 生成日志（OCR/标准化等） | action, model, tokens_used, parsed_result(JSON) |
| tags | 轻量标签（知识点体系已迁移至 knowledge_points） | name, subject_id, parent_id, sync_uuid |
| import_pipelines | PDF/图片导入 Pipeline | status, chunk_size, watermark_snapshot |
| import_pipeline_chunks | Pipeline 分片执行结果 | chunk_index, page_start/end, status |
| import_batch_jobs | 批量图片导入任务 | job_id, request_id(唯一索引), status |
| import_batch_job_items | 批量导入单图执行结果 | seq, ocr_raw_text, review_batch_id |
| batch_job_trace_events | 批量导入追踪事件日志 | seq (per-job monotonic), step, status |
| pomodoro_sessions | 番茄钟会话 | subject_id, preset, work_duration, status, total_paused_sec |
| pomodoro_pause_intervals | 番茄钟暂停区间 | session_id, started_at, ended_at |
| user_pomodoro_settings | 用户番茄钟设置 | user_id (PK), day_start_minute |
| watermark_rules | PDF 水印过滤规则 | pattern, rule_type, is_active |
| app_user_admin_bindings | 小程序用户-管理员绑定 | user_id (唯一), admin_user_id (唯一) |

> 2026-09 新增（408 学习体系与稳定性迁移，均已部署生产）：
>
> | 表名 | 用途 | 核心字段 |
> |------|------|----------|
> | exam_papers / exam_paper_questions | 408 选择题试卷域（真题/模拟） | public_id, paper_type, year, status, version, deleted_at, question_version_id 绑定 |
> | exam_attempts / exam_answers | 考试作答。进行中可改答案；交卷/超时/放弃后进入终态 | status, request_id, result_snapshot, answer_revision, paper_version |
> | wrong_question_error_diagnoses | 错因诊断（AI + 规则） | source_context, ai_status, ai_confidence, classification_version |
> | study_plans / study_plan_days | 学习计划 | daily_minutes, weekly_days, priority_mode, target |
> | syllabus_versions / syllabus_knowledge_points / syllabus_knowledge_point_mappings | 408 大纲版本化 | year, status, KP 映射 |
> | formula_cards（扩展） | 408 记忆卡片 | exam_scope, template_type, study_type |
> | sequential_reservations | 顺序刷题 reservation（幂等防并发） | user_id + question 唯一, request_id |
> | task_outbox | 异步任务 outbox（答案投影等） | payload(JSONB), status |
>
> 另：`admin_ai_model_configs` 新增 `deleted_at` 软删除（迁移 d5f6a7b8c9d0）；`question_embeddings` 改为 `model_id` FK 指向模型配置（迁移 b3d4e5f6a7b8 + c4e5f6a7b8c9，`embedding_model` 字符串列已删除）；`knowledge_points` 的 (subject_id, normalized_name) 唯一约束已放宽（迁移 r408kpunique20260912，允许同科目同名节点）。

---


## 完整物理表注册表（2026-09-27）

SQLAlchemy 的规范注册入口是 `app.models`，当前共 **78 张 ORM 表**。下表补齐此前正文未展开的表；其余核心表继续见后续各节。生产 PostgreSQL 还包含 Alembic 自身的 `alembic_version`，以及下文说明的 SQL/pgvector 专用 `question_embeddings`。

| 表名 | 领域职责 | 关键约束或事实源 |
|------|----------|------------------|
| ai_feedback_logs | 小程序 AI 结果反馈 | 每次反馈一条；`user_id` 索引 |
| worker_credentials | OCR Worker API Key 摘要与轮换 | `id` PK；只保存 SHA-256，按 `worker_id` 查询 |
| export_tasks / export_snapshots | 异步导出任务与不可变快照 | 任务状态、用户维度索引；快照绑定任务 |
| ocr_jobs | 外部 OCR worker 控制面 | `request_id`、完成幂等键唯一；lease/重试索引 |
| formula_categories / formula_tags | 公式分类与标签 | 分类树、标签规范名 |
| formula_card_tags / formula_card_versions | 公式卡标签关联与版本快照 | card+tag、card+version 唯一 |
| formula_graph_assets / formula_graph_previews / formula_graph_specs | 公式图资产、临时预览与多图规格 | spec `id` PK；card+slug 唯一；reviewer FK |
| formula_import_jobs / formula_import_items | 公式批量导入 | job/item 归属和执行状态 |
| user_formula_favorites | 用户公式收藏 | user+card 唯一 |
| knowledge_edges | 知识图谱有向边 | source+target+relation 唯一 |
| question_version_knowledge_points | 题目版本知识点快照 | 版本发布后的不可变关联；不替代当前题关联 |
| recommendation_experiments / recommendation_experiment_assignments | 推荐 A/B 实验与稳定分桶 | 实验名唯一；用户实验分配唯一 |
| recommendation_strategy_configs | 推荐策略参数 | name 唯一 |
| recommendation_logs / recommendation_metrics_daily | 推荐事实日志与每日聚合 | 原始日志为事实源，daily 为聚合投影 |
| user_adaptive_profile | 用户级间隔倍率 | user 唯一 |
| user_knowledge_adaptive_state | 知识点级间隔倍率 | user+knowledge_point 唯一 |
| user_question_difficulty_state | 用户题目难度观测 | user+question 唯一 |
| user_recommend_preference | 用户推荐权重 | user 唯一 |
| user_knowledge_states | 知识点掌握度投影 | user+knowledge_point 唯一 |
| user_question_state | Leitner/题目复习调度投影 | user+question 唯一 |
| sequential_reservations | 顺序刷题并发 reservation | user+question 唯一；request_id 幂等 |
| study_plans / study_plan_days | 长期学习计划与每日快照 | user 唯一计划；plan+date 唯一 |
| syllabus_versions / syllabus_knowledge_points / syllabus_knowledge_point_mappings | 408 大纲版本、成员和跨版映射 | 版本 code、成员及映射唯一约束 |
| task_outbox | DB→Redis 事务 outbox | `task_id` 唯一；状态/类型索引 |
| wrong_question_error_diagnoses | 错答发生级错因诊断 | practice_record、exam_answer 各自唯一 |
| review_sessions | 今日复习分组时长事实 | user+request 唯一，按科目拆分 |

### PostgreSQL 专用 `question_embeddings`

`question_embeddings` 使用 pgvector 的 `vector` 物理类型，由专用 Alembic revisions 与 `vector_retrieval_service` 的 SQL 维护，不建立 SQLAlchemy ORM 映射。Alembic autogenerate 只排除这张表及其子对象，避免误删；其他表仍必须通过 `alembic check` 零漂移。核心约束为 `question_id`、`subject_id`、`model_id` 外键，当前模型配置引用使用 `model_id → admin_ai_model_configs.id`。

### 状态表语义边界

- `user_question_state` 是 Leitner/复习调度投影；`user_question_difficulty_state` 是个人难度观测。两表的计数口径服务于各自算法，不得跨表覆盖或把任一表当作另一表的替代品。
- `user_knowledge_states` 保存掌握度；`user_knowledge_adaptive_state` 保存遗忘间隔倍率。
- `question_knowledge_points` 是当前题目关联事实源；`question_version_knowledge_points` 是历史版本快照。
- `practice_sessions` 记录刷题会话，`review_sessions` 记录今日复习分组时长；两者都进入学习时长统计，但保持独立来源和幂等键。

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
    provider: str        # openai-compatible 供应商别名：qwen / glm / deepseek / openai 等
    api_base_url: str?
    api_key_encrypted: str?  # Fernet 加密
    is_enabled: bool     # 默认 True
    is_default: bool     # 默认 False
    sort_order: int
    feature: str?        # 旧字段（单 feature，向后兼容）
    features: list?      # JSON 数组，多 feature 支持
    deleted_at: datetime? # 软删除（迁移 d5f6a7b8c9d0，删除后模型 ID 保持稳定）
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
| deleted_at | DateTime | NULLABLE（软删除标记） |
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
    subject_id: int            # FK → subjects.id（NOT NULL、索引）
    question_type: str         # choice / fill / subjective / multi_blank_choice / multi_blank_multiple_choice / true_false
    content: dict              # JSON: {"text":"...", "images":["url"], "latex":"..."}
    options: dict?             # JSON: {"A":"...", "B":"..."}（支持富格式 {key: {"text":..., "segments":[...]}}）
    answer: str                # 标准答案（Text 类型，支持长答案）
    question_hash: str?        # Level 1 完全重复检测 hash（MD5，32 位）
    analysis: str?             # 解析
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

    # 知识点关联（关联表 question_knowledge_points 为唯一事实源，questions.knowledge_points JSON 列已移除）：
    #   knowledge_point_links → QuestionKnowledgePoint 关联行，保留 role/weight/source/position 元数据
    #   kp_links             → viewonly secondary 关系，按 (position, id) 排序
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| subject_id | Integer | FK(subjects.id), NOT NULL, INDEX |
| question_type | String(32) | NOT NULL, default="choice" |
| content | JSON | NOT NULL |
| options | JSON | NULLABLE |
| answer | Text | NOT NULL |
| question_hash | String(32) | NULLABLE, INDEX；subject_id + question_hash 用于发布/审核通过阶段完全重复拦截 |
| analysis | Text | NULLABLE |
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
    knowledge_points: list? # JSON 快照（历史版本保留）
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

## question_knowledge_points

题目-知识点映射关联表（**知识点关联的唯一事实源**）。`questions.knowledge_points` JSON 列已移除（e791c979），所有题目知识点关系均存于此表。

```python
class QuestionKnowledgePoint(Base):
    __tablename__ = "question_knowledge_points"

    id: int                # PK
    question_id: int       # FK → questions.id（ON DELETE CASCADE，索引）
    knowledge_point_id: int# FK → knowledge_points.id（索引）
    role: str              # main 等，默认 "main"
    weight: float          # 权重，默认 1.0
    source: str            # imported / sync 等，默认 "imported"
    position: int          # 原 JSON 数组内下标（0 基），保留展示顺序，默认 0
    created_at: datetime
    updated_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| question_id | Integer | FK(questions.id, ondelete=CASCADE), NOT NULL, INDEX |
| knowledge_point_id | Integer | FK(knowledge_points.id), NOT NULL, INDEX |
| role | String(16) | NOT NULL, default="main" |
| weight | Float | NOT NULL, default=1.0 |
| source | String(16) | NOT NULL, default="imported" |
| position | Integer | NOT NULL, default=0 |
| created_at | DateTime | server_default=now() |
| updated_at | DateTime | server_default=now(), onupdate |

**唯一约束**: `(question_id, knowledge_point_id)` — `uq_qkp_question_kp`

---

## knowledge_points

知识点主表 —— 科目级别的规范化知识点定义。

```python
class KnowledgePoint(Base):
    __tablename__ = "knowledge_points"

    id: int                # PK
    subject_id: int        # FK → subjects.id（NOT NULL、索引）
    name: str              # 展示名（索引）
    normalized_name: str   # 规范化名（英文小写、全角→半角、去空格）（索引）
    aliases: list?         # JSON: 别名数组
    description: str?      # 描述
    difficulty_level: int  # 难度，默认 3
    is_active: bool        # 默认 True
    created_at: datetime
    updated_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| subject_id | Integer | FK(subjects.id), NOT NULL, INDEX |
| name | String(128) | NOT NULL, INDEX |
| normalized_name | String(128) | NOT NULL, INDEX |
| aliases | JSON | NULLABLE |
| description | Text | NULLABLE |
| difficulty_level | SmallInteger | NOT NULL, default=3 |
| is_active | Boolean | NOT NULL, default=True |
| created_at | DateTime | server_default=now() |
| updated_at | DateTime | server_default=now(), onupdate |

**索引（非唯一）**: `(subject_id, normalized_name)` — `ix_kp_subject_normalized_name`。迁移 `r408kpunique20260912` 已去掉这份唯一约束。同科目同名节点合法，节点用 `id` 区分。

---

## question_imports

```python
class QuestionImport(Base):
    __tablename__ = "question_imports"

    id: int              # PK
    batch_id: str        # 批次 ID（索引）
    source_type: str     # excel / pdf / image / ai 等来源
    source_file: str?    # 源文件名
    subject_id: int?     # FK → subjects.id（索引）
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
| subject_id | Integer | FK(subjects.id), NULLABLE, INDEX |
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
    mastered_at: datetime?  # 掌握时间
    is_active: bool         # 逻辑删除，默认 True
    removed_at: datetime?   # 移除时间
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
| mastered_at | DateTime | NULLABLE |
| is_active | Boolean | default=True |
| removed_at | DateTime | NULLABLE |
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
    subject_id: int?       # FK → subjects.id (ondelete=SET NULL)
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
| subject_id | Integer | FK(subjects.id, ondelete=SET NULL), NULLABLE |
| interval | Integer | default=0 |
| ease_factor | Float | default=2.5 |
| repetitions | Integer | default=0 |
| next_review_at | DateTime | NULLABLE |
| last_reviewed_at | DateTime | NULLABLE |
| mastered | Boolean | default=False |
| created_at | DateTime | server_default=now() |
| updated_at | DateTime | server_default=now(), onupdate |

### 索引

- `ix_review_schedules_user_subject_id` — `(user_id, subject_id)`
- `user_id` 单独索引

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
    subject_id: int         # FK → subjects.id
    question_type: str      # choice / fill / subjective / multi_blank_choice / multi_blank_multiple_choice
    user_answer: str        # 用户提交的答案（Text）
    is_correct: bool        # 是否正确
    used_time: int?         # 耗时（秒），可为空
    answered_at: datetime   # 答题时间
    created_at: datetime

    # Legacy session 列（为阻止 Alembic autogenerate DROP COLUMN 而保留在 ORM）：
    # mode / question_ids / answers / correct_count / wrong_count / duration_sec / started_at / finished_at
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| user_id | Integer | FK(users.id), NOT NULL, INDEX |
| question_id | Integer | FK(questions.id), NOT NULL, INDEX |
| subject_id | Integer | FK(subjects.id), NOT NULL |
| question_type | String(32) | NOT NULL, default="choice" |
| user_answer | Text | NOT NULL |
| is_correct | Boolean | NOT NULL |
| used_time | Integer | NULLABLE |
| answered_at | DateTime | server_default=now() |
| created_at | DateTime | server_default=now() |

### 索引

- `idx_practice_records_user_subject_id` — `(user_id, subject_id)`
- `idx_practice_records_user_answered_question` — `(user_id, answered_at, question_id)`（覆盖"最近 N 天做题"统计窗口）
- `question_id` 单独索引

### 设计说明

每条记录对应一道题的**一次作答**。用户对同一道题多次作答会产生多条记录（如错题重做），
通过 `question_id + user_id` 可查询用户对该题的全部作答历史。

---

## practice_sessions

一次完整刷题会话 —— 用户从开始一组练习到成功交卷的一条记录（commit 7b79ca2a）。与 `PracticeRecord`（每道题一条）语义分离：

- `PracticeRecord.used_time` → 单题行为分析（平均答题时间 / mastery 等）
- `PracticeSession.duration_sec` → 学习统计（番茄钟统计页的 duration 指标）

一次刷题会话只对应一条记录；由 `(user_id, request_id)` 幂等去重，网络重试不会重复插入 session 导致学习时长翻倍。session 元数据在 batch-submit 时可选上报（旧客户端不携带，不影响答题）。

```python
class PracticeSession(Base):
    __tablename__ = "practice_sessions"

    id: int                # PK
    user_id: int           # FK → users.id（索引）
    subject_id: int        # FK → subjects.id（NOT NULL、索引）
    request_id: str?       # 幂等 key（string 上限内原样；超长由 service 稳定 hash）
    mode: str              # random 等，默认 "random"
    started_at: datetime
    finished_at: datetime
    duration_sec: int
    question_count: int    # 默认 0
    answered_count: int    # 默认 0
    correct_count: int     # 默认 0
    wrong_count: int       # 默认 0
    status: str            # 恒为 "completed"（只在成功交卷时创建）
    created_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| user_id | Integer | FK(users.id), NOT NULL, INDEX |
| subject_id | Integer | FK(subjects.id), NOT NULL, INDEX |
| request_id | String(256) | NULLABLE |
| mode | String(16) | NOT NULL, default="random" |
| started_at | DateTime | NOT NULL |
| finished_at | DateTime | NOT NULL |
| duration_sec | Integer | NOT NULL |
| question_count | Integer | NOT NULL, default=0 |
| answered_count | Integer | NOT NULL, default=0 |
| correct_count | Integer | NOT NULL, default=0 |
| wrong_count | Integer | NOT NULL, default=0 |
| status | String(16) | NOT NULL, default="completed" |
| created_at | DateTime | server_default=now() |

### 索引 / 约束

- `ix_practice_sessions_user_started` — `(user_id, started_at)`
- `ix_practice_sessions_user_finished` — `(user_id, finished_at)`
- `ux_practice_sessions_user_request` — `(user_id, request_id)` **部分唯一索引**（request_id IS NOT NULL；兼容不携带 session 的旧客户端）
- `ck_practice_sessions_duration_sec` — `duration_sec >= 0`
- `ck_practice_sessions_finished_at` — `finished_at >= started_at`

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
    subject_id: int?           # FK → subjects.id (ondelete=SET NULL)
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
| subject_id | Integer | FK(subjects.id, ondelete=SET NULL), NULLABLE, INDEX |
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
    model: str                # 模型名，默认 "openai-compatible"
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
| model | String(64) | default="openai-compatible" |
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
| model | String(64) | default="openai-compatible" |
| tokens_used | Integer | default=0 |
| duration_ms | Integer | default=0 |
| success | Integer | default=1 |
| error_message | Text | NULLABLE |
| created_at | DateTime | server_default=now() |

---

## tags（轻量标签，知识点体系已迁移至 knowledge_points）

> 保留的轻量标签表（含 sync_uuid 增量同步）。知识点主数据源为 `knowledge_points`，题目映射走 `question_knowledge_points`。

```python
class Tag(Base):
    __tablename__ = "tags"

    id: int              # PK
    name: str            # 标签名
    subject_id: int      # FK → subjects.id（索引）
    parent_id: int?      # 父标签 ID（预留层级扩展，MVP 暂不使用）
    sort_order: int      # 排序，默认 0
    sync_uuid: str?      # 增量同步 UUID（唯一、索引）
    created_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| name | String(64) | NOT NULL |
| subject_id | Integer | FK(subjects.id), NOT NULL, INDEX |
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

## pomodoro_sessions / pomodoro_subject_allocations / pomodoro_pause_intervals / user_pomodoro_settings

### pomodoro_sessions

```python
class PomodoroSession(Base):
    __tablename__ = "pomodoro_sessions"

    id: int                 # PK
    user_id: int            # FK → users.id（索引）
    subject_id: int?        # FK → subjects.id（索引）
    chapter_id: str?
    preset: str             # standard / custom / long / debug / free
    work_duration: int      # 工作时长（分钟），默认 25
    break_duration: int     # 休息时长（分钟），默认 5
    start_time: datetime
    end_time: datetime?
    expected_end_time: datetime? # 索引
    actual_duration: int?   # 实际工作时长（秒），服务端权威计算
    status: str             # running / paused / completed / interrupted
    notification_enabled: bool  # 是否启用订阅通知
    notification_sent: bool
    notification_sent_at: datetime?
    notification_error: str?
    openid_snapshot: str?   # 通知发送时用的 openid
    paused_at: datetime?    # 暂停时间
    total_paused_sec: int   # 暂停总秒数（派生缓存，真相源为 pause_intervals）
    created_at: datetime
```

`pomodoro_sessions.subject_id` 保留用户选择的归属入口。每个新会话在
`pomodoro_subject_allocations` 保存统计归属：单科会话写一条 10000 基点记录；
408 四科均分会话保留父级 `subject_id`，并写四条各 2500 基点的叶子快照。
历史旧记录没有明细时，统计按原 `subject_id` 单科解释，不回填历史。

### pomodoro_subject_allocations

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| session_id | Integer | FK(pomodoro_sessions.id, ondelete=CASCADE), NOT NULL |
| subject_id | Integer | FK(subjects.id, ondelete=SET NULL), NULLABLE |
| weight_basis_points | Integer | NOT NULL, > 0 |
| subject_code_snapshot | String(32) | NOT NULL, 非空 |
| subject_name_snapshot | String(64) | NOT NULL, 非空 |

- `ux_pomodoro_subject_allocations_session_subject` — `(session_id, subject_id)` 唯一
- `ux_pomodoro_subject_allocations_session_code` — `(session_id, subject_code_snapshot)` 唯一，科目删除后仍保护快照唯一性
- `ix_pomodoro_subject_allocations_subject` — `(subject_id)`

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| user_id | Integer | FK(users.id), NOT NULL, INDEX |
| subject_id | Integer | FK(subjects.id), NULLABLE, INDEX |
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
| total_paused_sec | Integer | NOT NULL, default=0 |
| created_at | DateTime | server_default=now() |

### 索引

- `ix_pomodoro_sessions_user_status_start` — `(user_id, status, start_time)`
- `ix_pomodoro_sessions_user_status_end` — `(user_id, status, end_time)`

### pomodoro_pause_intervals

暂停区间（暂停时长唯一真相源）。

```python
class PomodoroPauseInterval(Base):
    __tablename__ = "pomodoro_pause_intervals"

    id: int               # PK
    session_id: int       # FK → pomodoro_sessions.id (ondelete=CASCADE)
    started_at: datetime
    ended_at: datetime?   # None = 进行中暂停
    created_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| id | Integer | PK, autoincrement |
| session_id | Integer | FK(pomodoro_sessions.id, ondelete=CASCADE), NOT NULL |
| started_at | DateTime | NOT NULL |
| ended_at | DateTime | NULLABLE |
| created_at | DateTime | server_default=now() |

### 索引 / 约束

- `ix_pomodoro_pause_intervals_session_started` — `(session_id, started_at)`
- `ux_pomodoro_pause_intervals_one_open` — `(session_id)` 部分唯一（ended_at IS NULL；同一会话至多一个进行中暂停）
- `ck_pomodoro_pause_intervals_ended_at` — `ended_at IS NULL OR ended_at > started_at`

### user_pomodoro_settings

```python
class UserPomodoroSettings(Base):
    __tablename__ = "user_pomodoro_settings"

    user_id: int          # PK, FK → users.id (ondelete=CASCADE)
    day_start_minute: int # 学习日起点分钟（0-1439），默认 0
    created_at: datetime
    updated_at: datetime
```

| 字段 | 类型 | 约束 |
|------|------|------|
| user_id | Integer | PK, FK(users.id, ondelete=CASCADE) |
| day_start_minute | Integer | NOT NULL, default=0 |
| created_at | DateTime | server_default=now() |
| updated_at | DateTime | server_default=now(), onupdate |

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

### 多空（单选）选择题（`multi_blank_choice`）与多空（多选）选择题（`multi_blank_multiple_choice`）

当 `question_type = "multi_blank_choice"`（每空恰好一个选项）或 `question_type = "multi_blank_multiple_choice"`（每空可选多个选项）时：

- `options` / `parsed_options` = `null`
- `answer` 存储 canonical 格式：`"①:B;②:D"`（`slot:value` 对，英文分号分隔）；
  多空（多选）的空内多值用英文逗号连接：`"①:A,C;②:B"`
- `content` / `parsed_content` 包含 `blank_option_groups`：

```json
{
  "text": "入度是（ ）；出度是（ ）。",
  "blank_option_groups": [
    {"id": "①", "options": [{"key": "A", "text": "a"}, {"key": "B", "text": "b"}]},
    {"id": "②", "options": [{"key": "A", "text": "a"}, {"key": "B", "text": "b"}]}
  ]
}
```

- 即使原题只展示一次公共选项，每个 `blank_option_groups` 条目都包含完整选项副本
- 后端判题：所有槽位必须覆盖，多余槽位拒绝，槽位顺序无关；
  `multi_blank_choice` 每空单值精确匹配，`multi_blank_multiple_choice` 每空按选项集合比较（顺序无关）
- 提交格式：`user_answer: "①:B;②:D"`，多空（多选）为 `user_answer: "①:A,C;②:B"`
- 导入管线自动从 2+ 空 + 共享选项 + 多槽答案检测
- 历史口径：`multi_blank_choice` 原名“多空选择题”；拆分后存量数据保持 `multi_blank_choice`
  （每空单选语义），迁移 `v13_multi_blank_multiple_choice` 会把答案中含多字母槽位的
  存量记录重分类为 `multi_blank_multiple_choice`，并刷新三张表的 `question_type` CHECK 约束

---

## exam_papers / exam_paper_questions / exam_attempts / exam_answers

408 选择题考试。模型：`backend/app/models/exam.py`。

### exam_papers

| 字段 | 约束 |
|------|------|
| id | PK |
| public_id | String(32)，唯一，默认 `uuid4().hex` |
| title | String(128)，NOT NULL |
| paper_type | `past_exam_choice` / `mock_choice` |
| year | SmallInteger，可空 |
| source | String(128)，可空 |
| duration_sec | 可空；非空则必须 > 0。用户端用它判断 `expired` |
| version | Integer ≥ 1，默认 1 |
| status | `draft` / `published` / `archived` |
| is_active | Boolean，默认 true。软删除时置 false |
| published_at | 可空 |
| deleted_at | 可空，有索引。非空表示已软删除 |
| created_by / updated_by | FK → admin_users.id，可空 |
| created_at / updated_at | DateTime |

### exam_paper_questions

| 字段 | 约束 |
|------|------|
| paper_id | FK → exam_papers.id，ON DELETE CASCADE |
| question_id | FK → questions.id，ON DELETE RESTRICT |
| question_version_id | FK → question_versions.id，ON DELETE RESTRICT |
| position | > 0。与 paper_id 联合唯一 |
| score | Numeric(8,2) > 0 |
| section_subject_id | FK → subjects.id |

同一试卷内 `question_id` 唯一。

### exam_attempts

| 字段 | 约束 |
|------|------|
| paper_id / paper_version | 开考时绑定的试卷版本，version ≥ 1 |
| user_id | FK → users.id，ON DELETE CASCADE |
| status | `in_progress` / `submitted` / `expired` / `abandoned` |
| request_id | String(128)。与 user_id 联合唯一，用于开始作答幂等 |
| started_at / submitted_at | submitted_at 可空 |
| duration_sec / answered_count / correct_count | ≥ 0 |
| score | Numeric(8,2) ≥ 0 |
| result_snapshot | JSON，可空。终态成绩快照 |

同一用户同一试卷在 `status='in_progress'` 时唯一（部分唯一索引 `uq_exam_attempts_user_paper_in_progress`）。

### exam_answers

| 字段 | 约束 |
|------|------|
| attempt_id + exam_paper_question_id | 联合唯一 |
| question_id / question_version_id | 与试卷题目绑定的版本 |
| selected_answer | String(32)，可空 |
| answer_revision | Integer，默认 0 |
| is_correct / score | 交卷前可空；score 非空则 ≥ 0 |
| used_time | ≥ 0 |
| marked_for_review | Boolean，默认 false |
| practice_record_id | FK → practice_records.id，唯一，可空 |

---

## 设计原则

- **用户唯一标识**：微信 openid（不使用 email/username/password）
- **系统不保存密码**，不存在密码字段（管理员表除外，存 password_hash）
- `content` 为 JSON：`{"text":"...", "images":["url"], "latex":"..."}`
- 题目知识点关系以 `question_knowledge_points` 关联表为唯一事实源（`questions.knowledge_points` JSON 列已移除）。`normalized_name` 只做非唯一索引，同科目允许同名节点（迁移 `r408kpunique20260912`）
- 不拆选择题/填空题子表，用 `question_type` 区分
- `source_type` + `source_file` + `import_batch_id` 三位一体追溯来源
- Level 1 题库去重使用 `question_hash`：导入阶段只标记 `question_imports.duplicate_status`，发布/审核通过阶段按 `subject + question_hash` 完全匹配拦截，不自动删除历史题目
- AI 辅助导题/补全只写入 `question_imports` 的 AI 元数据字段，仍必须经过人工审核，不直接进入 `questions`
- `raw_content` 保留导入原始文本
- SM-2 复习调度以 `review_schedules` 为唯一数据源；`WrongQuestion` 不再持有 efactor/interval/repetitions/next_review_date/quality 等旧字段，仅保留错题分析相关状态
- SM-2 rating 合法范围是 0-5，其中 0 是合法评分（完全不会，重置 repetitions=0），不应抛出异常
- 自动批改未提供用户自评 rating 时默认映射：is_correct=True → rating=4，is_correct=False → rating=1
- 复习日期统一使用 `utcnow().date()`，避免服务器本地时区导致日期偏移
- 复习 API 使用 `/review/today`、`/review/schedule-submit`、`/review/schedule-stats` 等当前端点；旧 `/review/due`、`/review/submit`、`/review/stats` 已移除
- 每次答题一条记录（`practice_records`），每题一条，支持多次作答
- `session_type` 区分 AI 对话场景
- **RBAC 权限系统**：`admin_users` → `roles` ↔ `permissions`（多对多），所有管理操作记入 `audit_logs`
- **批量导入**：`import_batch_jobs` 管理多图片任务，`import_pipeline` 管理 PDF 分片任务，各自独立
- **番茄钟**：`pomodoro_sessions` 单表记录完整生命周期，`pomodoro_pause_intervals` 为暂停时长唯一真相源，支持微信订阅通知；学习时长统计合并 `practice_sessions.duration_sec` 与 `review_sessions.duration_sec`
- **增量同步**：`questions.sync_uuid/sync_version`、`tags.sync_uuid` 支持本地-云端增量同步

> 上次更新：2026-09-27 — 补齐完整 ORM 表注册表、review_sessions、pgvector 专用表边界与状态表事实源；完成 Schema 一致性修复。
>
> 历史更新：2026-09-23 — 补齐 408 考试四表（public_id、deleted_at、attempt 状态）；知识点 (subject_id, normalized_name) 改为非唯一索引。2026-09-19 的多空题型拆分仍然有效。
>
> 历史更新：2026-08-10 — 知识点重构为关联表唯一事实源（移除 questions.knowledge_points JSON）；新增 knowledge_points/question_knowledge_points/practice_sessions/pomodoro_pause_intervals/user_pomodoro_settings 表；module 重构全部改为 subject_id
