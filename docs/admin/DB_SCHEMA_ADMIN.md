# 数据库设计规划

> 版本：v2.7（question_imports 答案状态与优先级字段登记） | 状态：核心 Admin schema 已实施 | 更新：2026-10-23
> ORM：SQLAlchemy | DB：PostgreSQL（生产共享实例）/ SQLite（开发兼容）
> 修订自审计报告 I1（新增 subjects）、C6（新增 question_versions）、C5（operation_logs → audit_log + severity）、O1（IP 字段）、C1（双身份系统说明）
>
> - **变更原因**：2026-05-30 同步 Phase 7 新增 `admin_ai_settings`、`admin_ai_usage_monthly` 与 Alembic migration `i0e1f2a3b4c5_add_admin_ai_settings.py`。
> - **变更原因**：2026-05-30 同步题库 Level 1 去重在既有 `questions` / `question_imports` 上新增的 hash 与重复标记字段。
> - **变更原因**：2026-06-10 同步 AI 解析设置配置接口新增 `admin_ai_model_configs`（模型配置表）和 `admin_ai_configs`（AI 配置键值表）。
> - **变更原因**：2026-08-10 同步 `question_knowledge_points` 关联表成为题目知识点唯一事实源（移除 `questions.knowledge_points` JSON 列），以及题目图片存储约定（question-assets，`{question_id}/{uuid}.{ext}`）。
> - **变更原因**：2026-08/09 同步系统运维权限与备份任务相关模型/配置，并明确当前迁移工具链为 Alembic，不再使用 Prisma 目录或命令。

---

## 一、设计原则

1. Admin 系统新增表使用独立命名空间前缀 `admin_`，避免与小程序 FastAPI 表冲突
2. 小程序已有表（`users`, `questions`, `question_imports`, 等）**默认只读**，新增字段必须经过评审走 migration
3. Python/SQLAlchemy 模型与数据库字段统一使用 `snake_case`；API 层字段别名按 Pydantic schema 约定
4. 每次 DB 变更必须创建新的 Alembic revision，**禁止修改已有 migration 文件**
5. 删除字段前先标记 deprecated 并保留 1 个 Phase 后再删除

---

## 二、新增表设计

> 本节中的 `prisma` 代码块是早期设计阶段的逻辑字段参考，不是当前仓库的 schema 文件，也不能直接执行。当前事实源是 `backend/app/models/` 下的 SQLAlchemy 模型及 `backend/alembic/versions/` 下的 Alembic revisions；字段与约束以它们为准。

### 2.1 admin_users（后台管理员账号）

> 与小程序 `users` 表完全分离。AdminUser 使用用户名+密码登录，不涉及微信 openid。

```prisma
model AdminUser {
  id            Int       @id @default(autoincrement())
  username      String    @unique @db.VarChar(64)
  passwordHash  String    @map("password_hash") @db.VarChar(256)
  displayName   String?   @map("display_name") @db.VarChar(64)
  email         String?   @unique @db.VarChar(128)        // 仅展示/预留，不用于登录；可为空，唯一约束仅约束非空值
  isActive      Boolean   @default(true) @map("is_active")
  roleId        Int       @map("role_id")
  lastLoginAt   DateTime? @map("last_login_at")
  lastLoginIp   String?   @map("last_login_ip") @db.VarChar(45)  // O1: IPv6 最长 39
  createdAt     DateTime  @default(now()) @map("created_at")
  updatedAt     DateTime  @updatedAt @map("updated_at")

  role          Role      @relation(fields: [roleId], references: [id])
  auditLogs     AuditLog[]
  bannedUsers   User[]    @relation("BannedByAdmin")

  @@index([username])
  @@index([roleId])
  @@map("admin_users")
}
```

**扩展预留**（不在当前 Phase 实现）：
- `tenantId` — 多租户
- `mfaEnabled` / `mfaSecret` — 双因子认证
- `passwordChangedAt` — 强制定期改密
- `failedLoginCount` — 与 Redis 双重防御

---

### 2.2 roles（角色表）

```prisma
model Role {
  id          Int       @id @default(autoincrement())
  name        String    @unique @db.VarChar(64)   // super_admin / admin
  displayName String    @map("display_name") @db.VarChar(64)
  description String?   @db.Text
  isSystem    Boolean   @default(false) @map("is_system")  // 系统内置角色不可删除
  createdAt   DateTime  @default(now()) @map("created_at")
  updatedAt   DateTime  @updatedAt @map("updated_at")

  users       AdminUser[]
  permissions RolePermission[]

  @@map("roles")
}
```

**后台角色初始数据种子**（C1：不创建 `normal_user` 后台角色）：
```
name=super_admin, displayName="超级管理员", isSystem=true
name=admin,       displayName="普通管理员", isSystem=true
```

> 当前 bootstrap 还会保留 `user` 系统角色及应用侧只读权限；该角色不用于后台管理员账号，具体以 `admin_bootstrap_service.py` 为准。

**注意**：seed 阶段可尽力保证本地初始化顺序稳定，但业务代码不得依赖 `super_admin.id = 1`；所有判断必须按 `roles.name = 'super_admin'` 查询。super_admin 必须通过 `role_permissions` 表绑定**全部** permissions（C3 修订），CI 检查强制保证。

---

### 2.3 permissions（权限定义表）

```prisma
model Permission {
  id          Int       @id @default(autoincrement())
  name        String    @unique @db.VarChar(128)  // e.g. app_user:read
  resource    String    @db.VarChar(64)            // e.g. app_user
  action      String    @db.VarChar(64)            // e.g. read
  category    String    @db.VarChar(32)            // 用户/内容/系统等，便于前端 UI 分组
  description String?   @db.VarChar(256)
  createdAt   DateTime  @default(now()) @map("created_at")

  roles       RolePermission[]

  @@index([resource])
  @@index([category])
  @@map("permissions")
}
```

`category` 取值：`user` / `admin` / `content` / `system` / `audit` / `dashboard`（用于权限矩阵 UI 分组展示）。

---

### 2.4 role_permissions（角色-权限多对多）

```prisma
model RolePermission {
  roleId       Int      @map("role_id")
  permissionId Int      @map("permission_id")
  grantedAt    DateTime @default(now()) @map("granted_at")
  grantedBy    Int?     @map("granted_by")  // 操作者 admin_user.id（seed 时为 null）

  role         Role       @relation(fields: [roleId], references: [id], onDelete: Cascade)
  permission   Permission @relation(fields: [permissionId], references: [id], onDelete: Cascade)

  @@id([roleId, permissionId])
  @@index([permissionId])  // 反查"哪些角色拥有该权限"
  @@map("role_permissions")
}
```

---

### 2.5 audit_logs（审计日志，原 operation_logs 改名）

> C5 修订：改名 audit_log；新增 severity 字段；按月分区。

```prisma
model AuditLog {
  id           BigInt    @id @default(autoincrement())
  operatorId   Int?      @map("operator_id")        // null = 系统/脚本
  operatorName String?   @map("operator_name") @db.VarChar(64)  // 冗余字段，防止 admin 删除后无法显示
  action       String    @db.VarChar(128)            // e.g. question.approve
  resourceType String?   @map("resource_type") @db.VarChar(64)  // e.g. question
  resourceId   String?   @map("resource_id") @db.VarChar(64)    // 改 String 兼容 batch
  severity     String    @default("normal") @db.VarChar(16)     // critical | important | normal | low
  detail       Json?                                  // { before, after, extra }
  ip           String?   @db.VarChar(45)             // O1: IPv6 最长 39
  userAgent    String?   @map("user_agent") @db.VarChar(256)
  status       String    @default("success") @db.VarChar(16)    // success | failed
  errorMessage String?   @map("error_message") @db.Text
  createdAt    DateTime  @default(now()) @map("created_at")

  operator     AdminUser? @relation(fields: [operatorId], references: [id])

  @@index([operatorId])
  @@index([action])
  @@index([resourceType, resourceId])
  @@index([severity])
  @@index([createdAt])
  @@map("audit_logs")
}
```

**关键变更**：
- `id` 改为 `BigInt`（日志数据量大，Int 上限 21 亿不够长期使用）
- `resourceId` 改为 `String`（兼容批量操作，可存 `batch:[1,2,3]` 或单 ID）
- 新增 `severity` 枚举字段（critical / important / normal / low）
- 新增 `errorMessage` 字段（status=failed 时记录）
- 新增 `operatorName` 冗余字段（operator 被删除后仍能查阅）
- 请求追踪使用 `audit_logs.detail.extra.requestId`；`requestId` 即全链路 traceId，Phase 0/1 不新增 `trace_id` 列

**分区策略**（I7 修订，生产 PostgreSQL 专属）：
- 开发环境（尤其 SQLite）不启用分区，使用普通 `audit_logs` 表。
- 分区属于生产 PostgreSQL 部署脚本，不由 SQLAlchemy/Alembic core migration 直接表达；上方逻辑模型不替代生产 DDL，避免与 PostgreSQL 分区主键形成两套真相。
- 如启用分区，生产 DDL 必须统一主键口径：分区父表主键需包含分区键 `created_at`（如 `PRIMARY KEY (id, created_at)`），应用层仍以 `id` 作为展示与查询标识。
- `pg_partman` 是否启用、归档策略与维护任务需单独确认，不要求 Phase 0 直接落地。
- 6 个月前的日志自动归档至 `audit_logs_archive` 表（可后期迁 S3 / Parquet），仅在生产分区方案确认后启用。

**生产分区脚本示例（待确认，非 Alembic core migration 必选项）**：
```sql
CREATE TABLE audit_logs (
  ...
) PARTITION BY RANGE (created_at);

SELECT partman.create_parent(
  p_parent_table := 'public.audit_logs',
  p_control := 'created_at',
  p_type := 'range',
  p_interval := '1 month',
  p_premake := 4
);
```

---

### 2.6 subjects（科目树，I1 新增）

> 任务明确要求但 v1 漏掉的核心表。
> 
> **Phase 4 实现同步（2026-05-29）**：当前 FastAPI/SQLAlchemy 实现已由 Alembic revision `f6a7b8c9d0e1_add_admin_core_tables.py` 创建 `subjects` 表；`path` 按 `code` 拼接（如 `math/math_advanced`），不是 ID 形式 `/1/3/15`。

```prisma
model Subject {
  id        Int       @id @default(autoincrement())
  parentId  Int?      @map("parent_id")
  code      String    @unique @db.VarChar(32)   // 408_ds, math_advanced, english
  name      String    @db.VarChar(64)
  level     Int       @default(1)               // 1=主科目, 2=子科目, 当前实现最大 3 级
  path      String    @db.VarChar(128)          // O3: code 物化路径，如 math/math_advanced
  sortOrder Int       @default(0) @map("sort_order")
  isActive  Boolean   @default(true) @map("is_active")
  createdAt DateTime  @default(now()) @map("created_at")
  updatedAt DateTime  @updatedAt @map("updated_at")

  parent    Subject?  @relation("SubjectHierarchy", fields: [parentId], references: [id])
  children  Subject[] @relation("SubjectHierarchy")

  @@index([parentId])
  @@index([code])
  @@index([path])
  @@map("subjects")
}
```

**初始 Seed（示意，path 使用 code 拼接）**：
```
math (level=1, path=math)
  ├── math_advanced (level=2, path=math/math_advanced)
  └── math_linear   (level=2, path=math/math_linear)
408 (level=1, path=408)
  ├── 408_ds (path=408/408_ds)
  ├── 408_os (path=408/408_os)
  ├── 408_co (path=408/408_co)
  └── 408_cn (path=408/408_cn)
english (level=1, path=english)
```

**与 questions.subject 字段的关系**：
- 当前 `questions.subject` 是裸 String（"408_ds" 等）
- 保留为反范式 denormalize 字段（避免每次列表查询都 JOIN）
- 应用层负责保证 `questions.subject = subjects.code`
- 删除科目时：先校验是否有题目引用（`SELECT COUNT(*) FROM questions WHERE subject = ?`），有则拒绝

---

### 2.7 question_versions（题目历史版本，C6 新增）

> 编辑题目前的快照，保证审核流可追溯、支持回滚。

```prisma
model QuestionVersion {
  id          BigInt   @id @default(autoincrement())
  questionId  Int      @map("question_id")
  version     Int                                      // 版本号（从 1 起）
  content     Json
  options     Json?
  answer      String   @db.Text
  analysis    String?  @db.Text
  difficulty  Int      @db.SmallInt
  knowledgePoints Json? @map("knowledge_points")
  editedBy    Int      @map("edited_by")               // admin_user.id
  editReason  String?  @map("edit_reason") @db.Text
  createdAt   DateTime @default(now()) @map("created_at")

  editor      AdminUser @relation(fields: [editedBy], references: [id])

  @@unique([questionId, version])
  @@index([questionId])
  @@index([editedBy])
  @@map("question_versions")
}
```

**写入时机**：
- 每次编辑 `questions` 表前，先把当前 questions 的字段快照写入 `question_versions`
- 版本号从 1 开始递增（同一 questionId 自增）

### 2.8 admin_ai_settings（后台 AI 解析设置，Phase 7 新增）

> **Phase 7 实现同步（2026-05-30）**：由 Alembic revision `i0e1f2a3b4c5_add_admin_ai_settings.py` 创建，用于保存全局 AI 解析开关与月度调用额度。

核心字段：
- `id`
- `ai_parse_enabled`：全局 AI 解析开关。
- `monthly_call_limit`：月度全局 API 调用额度；`0` 表示不限。
- `updated_by`：最近更新管理员。
- `updated_at`

业务约束：
- 全局关闭优先级最高，`super_admin` 也不能绕过。
- 月度额度只限制普通管理员；`super_admin` 可绕过额度但仍受全局关闭限制。

---

### 2.9 admin_ai_usage_monthly（后台 AI 月度用量，Phase 7 新增）

> **Phase 7 实现同步（2026-05-30）**：由 Alembic revision `i0e1f2a3b4c5_add_admin_ai_settings.py` 创建，用于按月聚合 AI 解析调用次数。

核心字段：
- `year_month`：统计月份，主键，格式如 `2026-05`。
- `call_count`：已创建 AI 解析调用次数。
- `limit_snapshot`：创建该月用量记录时的额度快照。
- `created_at` / `updated_at`

用法：
- `GET /api/admin/v1/ai-settings/usage` 读取当前或指定月份用量。
- `ensure_ai_parse_allowed` 在导入 enrich 前读取设置与用量，执行全局关闭和额度拦截。

---
### 2.10 admin_ai_model_configs（AI 模型配置表，2026-06-10 新增）

> 保存可配置的 AI 模型列表及其 API 密钥（Fernet 加密）。Seed 默认包含 DeepSeek V4 Flash、GPT-4o、Claude 3.5 Sonnet。

核心字段：
- `id`：主键，自增。
- `name`：模型内部标识（唯一），如 `deepseek-v4-flash`。
- `display_name`：展示名称，如 `DeepSeek V4 Flash`。
- `provider`：供应商，如 `deepseek` / `openai` / `anthropic`。
- `api_base_url`：可选的 API 基地址。
- `api_key_encrypted`：Fernet 加密后的 API key（`cryptography.fernet.Fernet`）；依赖环境变量 `AI_CONFIG_ENCRYPT_KEY` 作为加密密钥；该变量未配置时以明文存储并记录启动警告。
- `is_enabled`：是否启用。
- `is_default`：是否为默认模型（全局唯一，`PATCH /ai-models/{id}` 设 default 时自动清除其他 default）。
- `sort_order`：排序号。
- `deleted_at`：软删除时间（2026-09-12 迁移 d5f6a7b8c9d0 新增）。删除模型走软删除以保持模型 ID 稳定（外部引用如 `question_embeddings.model_id` 不悬空）。
- `created_at` / `updated_at`。

业务约束：
- API key 响应时不返回，仅通过 `api_configured` 布尔字段指示是否已配置。
- `api_key="****"` 在 PATCH 请求中视为"不修改"。

---
### 2.11 admin_ai_configs（AI 配置键值表，2026-06-10 新增）

> 键值对表，存储 AI Prompts 文本、OCR 策略开关、补全策略开关等 17 个配置项。默认值同步自 `app/ai/prompts.py`。

核心字段：
- `config_key`：主键，字符串（如 `ocr_correction_prompt`、`ocr_strategy_math_formula`）。
- `config_value`：配置值文本（prompt 字段 max_length=5000 校验）。
- `updated_by`：最近更新管理员 ID。
- `updated_at`。

默认 config_key 清单（17 个）：
```
OCR 管线相关：   ocr_correction_prompt, ocr_strategy_math_formula,
                ocr_strategy_punctuation, ocr_strategy_digit_letter,
                ocr_strategy_space_newline, ocr_structure_question_type,
                ocr_structure_options, ocr_structure_answer,
                ocr_structure_analysis, ocr_filter_max_chars,
                ocr_filter_max_tokens, ocr_filter_sensitive

题目补全相关：   completion_prompt, completion_auto_stem,
                completion_auto_options, completion_auto_answer_reasoning,
                completion_auto_knowledge_tags
```

---
### 2.12 question_knowledge_points（题目-知识点关联表，2026-08-10 同步）

> 题目知识点唯一事实源。`questions.knowledge_points` JSON 列已移除，映射统一落到本关联表。

核心字段：
- `id`：主键自增。
- `question_id`：FK `questions.id`，`ondelete=CASCADE`，带索引。
- `knowledge_point_id`：FK `knowledge_points.id`，带索引。
- `role`：默认 `main`。
- `weight`：默认 `1.0`。
- `source`：来源标记（`imported` / `admin` 等）。
- `position`：保留原 `questions.knowledge_points` JSON 数组下标（0 基），用于展示顺序。
- `created_at` / `updated_at`。

约束与语义：
- 唯一约束 `(question_id, knowledge_point_id)`（`uq_qkp_question_kp`）。
- `normalized_name` 仍按科目规范化，但 `(subject_id, normalized_name)` 已不是唯一约束（迁移 `r408kpunique20260912`，索引 `ix_kp_subject_normalized_name`）。同科目允许同名节点，节点以 `id` 区分。
- 硬删题目由 DB `ON DELETE CASCADE` 清理关联行。
- 读：`load_question_kps` 一次查询按 `position,id` 批量加载展示名；写：`sync_question_knowledge_points`（additive / replace 语义），`replace=True` 时先删后 flush 再两阶段更新 position 避免唯一约束瞬时冲突。

## 三、复用已有表（需变更字段）

### 3.1 users（小程序用户）— 新增封禁字段

当前结构（FastAPI 管理）：
```
id, openid, session_key, nickname, avatar_url, created_at, updated_at
```

**Phase 2 新增字段**（必须先与 FastAPI 端确认兼容性）：
```sql
ALTER TABLE users
  ADD COLUMN is_banned BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN banned_reason VARCHAR(256),
  ADD COLUMN banned_at TIMESTAMP,
  ADD COLUMN banned_by INTEGER REFERENCES admin_users(id);   -- 关联封禁操作者
```

历史 ORM 映射参考（当前实现以 SQLAlchemy 模型为准）：
```prisma
model User {
  id            Int       @id @default(autoincrement())
  openid        String    @unique @db.VarChar(64)
  // ... 其他既有字段（来自 FastAPI）
  isBanned      Boolean   @default(false) @map("is_banned")
  bannedReason  String?   @map("banned_reason") @db.VarChar(256)
  bannedAt      DateTime? @map("banned_at")
  bannedBy      Int?      @map("banned_by")

  bannedByAdmin AdminUser? @relation("BannedByAdmin", fields: [bannedBy], references: [id])

  @@map("users")
}
```

**说明**：
- AppUser 不参与 RBAC，没有 role 字段
- 封禁状态由 Admin Backend 写入，FastAPI 只读判断（在 JWT 签发时检查 isBanned）

---

### 3.2 questions（题目表）— 新增字段

**Level 1 去重字段（2026-05-30 已实现）**：

由 Alembic revision `j1f2a3b4c5d6_add_duplicate_question_hash_fields.py` 添加：

```sql
ALTER TABLE questions
  ADD COLUMN question_hash VARCHAR(32);
CREATE INDEX ix_questions_question_hash ON questions (question_hash);
```

用途：发布 / 审核通过阶段按 `subject + question_hash` 查询正式题库，命中完全相同 hash 时阻止重复发布。`question_hash` 可为空以兼容历史数据，不执行历史题自动删除。

**实施前确认项**：
- 必须先确认生产/开发库中 `questions.review_status` 字段是否真实存在、默认值是否为 `approved`。
- 必须确认 FastAPI 刷题池查询是否过滤 `review_status = 'approved' AND is_active = true`；若未过滤，Admin 审核流不得上线。
- 若字段不存在，必须单独列 migration 与 FastAPI 兼容策略，不能只靠文档约定。

**当前阶段不修改 questions 表本体**（避免影响 FastAPI），但在字段已存在时需要 review_status 增加新枚举值：

```
review_status 枚举扩展：
  pending     # 待审核
  approved    # 审核通过
  rejected    # 审核拒绝
  re_pending  # 编辑后待重新审核（新增）
  archived    # 归档（替代 is_active=false 的语义，可选）
```

由于 `review_status` 预期为 String 字段，字段已存在时无需 migration，仅需在文档与代码层约定取值；若字段不存在或类型不兼容，必须补 migration 方案并先确认 FastAPI 兼容。

**知识点关联（2026-08-10 同步，关联表为唯一事实源）**：
- `questions.knowledge_points` JSON 列已移除，题目知识点改由 `question_knowledge_points` 关联表承载（见 3.12）。
- `Question` ORM 保留 `knowledge_point_links`（association metadata：role/weight/source/position）与 `kp_links`（viewonly 便捷关系）。
- Admin 侧读题目知识点统一走 `load_question_kps`（按 position,id 排序）；保存统一走 `sync_question_knowledge_points` / `replace_question_knowledge_points`（replace 语义，关联表写完删）。
- subject 变更时按新 `question.subject_id` 重建知识点映射；`kp_names=None` 表示不改动、`=[]` 且 replace 表示显式清空。

**编辑流程**（C6）：
- 持有 `question:write` + `question:review` 的 admin 编辑：保持 `approved` 状态，但写 question_versions
- 仅持有 `question:write` 的 admin 编辑：`approved → re_pending`，写 question_versions，等待 reviewer 重审

**题目图片存储约定（2026-08-10 同步）**：
- 题干 / 选项图片上传后压缩并存入 **question-assets** 存储后端（`get_question_assets_storage`），`storage_key` 形如 `{question_id}/{uuid}.{png|webp|jpg}`（按文件魔数判定后缀），通过 `/static/question-assets/...` 挂载对外访问。
- 题干图存储在 `content.segments` 的 image segment（`semantic_role: "content_image"`）；选项图存储在 `options[key]` 的 image segment（`semantic_role: "option_image"`），`questions.image_url` 作为冗余展示字段由 `extract_image_urls_from_content` 同步维护。
- 删除/替换后走 `AssetReferenceService` 引用检查，`reference_count == 0` 才物理删文件；`question_versions` 故意不参与引用计数（历史快照保留旧 URL）。

---

### 3.3 question_imports（导入批次）— 新增字段

**Level 1 去重字段（2026-05-30 已实现）**：

由 Alembic revision `j1f2a3b4c5d6_add_duplicate_question_hash_fields.py` 添加：

```sql
ALTER TABLE question_imports
  ADD COLUMN question_hash VARCHAR(32),
  ADD COLUMN duplicate_status VARCHAR(32) NOT NULL DEFAULT 'normal',
  ADD COLUMN duplicate_of_question_id BIGINT,
  ADD COLUMN duplicate_of_import_id BIGINT;
CREATE INDEX ix_question_imports_question_hash ON question_imports (question_hash);
CREATE INDEX ix_question_imports_duplicate_status ON question_imports (duplicate_status);
```

用途：导入阶段只标记 `normal` / `possible_duplicate`，并记录命中的正式题目或暂存导入题；不删除、不拒绝导入，仍需人工审核。

**Phase 3 新增**（审核操作记录）：
```sql
ALTER TABLE question_imports
  ADD COLUMN reject_reason TEXT,
  ADD COLUMN reviewed_by INTEGER REFERENCES admin_users(id),
  ADD COLUMN reviewed_at TIMESTAMP;
```

**答案状态与优先级字段（2026-07 起已实现，ORM `backend/app/models/question_import.py`）**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `answer_status` | String(24) | 答案状态：`missing` / `imported` / `ai_filled` / `manual_filled` / `manual_verified` / `abnormal`；审核队列过滤参数（`admin_imports.py` review-queue `answer_status`） |
| `answer_source` | String(16) | 答案来源：`ocr` / `parser` / `ai` / `manual` / `unknown` |
| `answer_confidence` | Float | 答案识别或 AI 补全置信度 |
| `review_priority` | Integer, indexed | 审核优先级，越高越优先；参与审核队列排序 |
| `ai_answer_flag` | Boolean | AI 答案待确认标记（阶段七） |
| `superseded_by_batch_id` / `superseded_at` | String(64) / DateTime | 批次被合并取代时的来源批次与时间（P0-4） |
| `source_question_no` / `source_question_label` | String(32) | 原始题号 / 完整标签（如 `12`、`12.`） |
| `source_image_seq` / `source_image_name` | Integer / String(256) | 批量图片导入的来源图序号 / 文件名 |
| `source_page_start` / `source_page_end` | Integer | PDF/文档起始/结束页码 |
| `source_order_index` | Integer | 批次内稳定顺序索引 |
| `raw_text_preview` | Text | 原始题目文本预览（保留题号） |

> 2026-10-23 同步：本节只登记与审核队列直接相关的答案状态/优先级字段；完整字段以 ORM 模型为准（文档自声明模型为事实源）。

历史 ORM 映射参考（当前实现以 SQLAlchemy 模型为准）：
```prisma
model QuestionImport {
  // ... 既有字段 ...
  rejectReason String?   @map("reject_reason") @db.Text
  reviewedBy   Int?      @map("reviewed_by")
  reviewedAt   DateTime? @map("reviewed_at")
  reviewer     AdminUser? @relation("ImportReviewer", fields: [reviewedBy], references: [id])
}
```

---

## 四、索引规划汇总

| 表 | 索引 | 原因 |
|----|------|------|
| admin_users | `username`, `email` (unique), `role_id` | 登录、按角色过滤 |
| roles | `name` (unique) | 按角色名称查询 |
| permissions | `name` (unique), `resource`, `category` | 按资源 / 分类过滤 |
| role_permissions | PK(role_id, permission_id), `permission_id` | 反查角色 |
| audit_logs | `operator_id`, `action`, `(resource_type, resource_id)`, `severity`, `created_at` | 多维查询 + 分区裁剪 |
| subjects | `parent_id`, `code` (unique), `path` | 树形查询、物化路径 |
| question_versions | `(question_id, version)` (unique), `question_id`, `edited_by` | 版本查询、按编辑者过滤 |
| question_knowledge_points | `question_id`, `knowledge_point_id`, 唯一 `(question_id, knowledge_point_id)` | 题目知识点关联查询 |
| questions | 既有索引 + `question_hash` + `(subject, review_status, is_active, created_at)` 复合索引 | 去重查询、审核列表高频查询 |
| users | 既有 `openid` + `is_banned`（部分索引）| 过滤封禁用户 |
| question_imports | 既有 + `question_hash` + `duplicate_status` + `reviewed_by` | 导入去重标记、反查审核人 |
| admin_ai_settings | `updated_by` | 设置页读取与审计追溯 |
| admin_ai_usage_monthly | `month` (unique) | 按月查询与额度校验 |
| admin_ai_model_configs | `name` (unique), `is_default`, `sort_order` | 模型列表查询与排序 |
| admin_ai_configs | PK(`config_key`) | 键值对查询与更新 |


**部分索引示例**（PostgreSQL 特性）：
```sql
CREATE INDEX idx_users_banned ON users (created_at) WHERE is_banned = TRUE;
CREATE INDEX idx_questions_pending ON questions (created_at) WHERE review_status = 'pending';
```

---

## 五、SQLAlchemy / Alembic 使用规范

```
backend/
├── app/models/               # SQLAlchemy ORM 模型
├── app/services/             # 事务边界与业务逻辑
├── app/cli/                  # 运维 CLI
└── alembic/versions/         # 版本化迁移
```

**规范要求**：
1. 每次 DB 变更必须创建新 migration（禁止修改已有文件）
2. 所有 migration 必须可回滚（提供 `down` 备注或方案）
3. Python 模型使用 SQLAlchemy 2.0，数据库字段保持 `snake_case`
4. 所有结构变更必须新增 Alembic revision，禁止修改已应用 migration
5. 外键、唯一约束和索引必须在模型与 migration 中保持一致
6. migration 提交前执行 `alembic upgrade head` 与测试数据库迁移校验
7. 生产启动前校验数据库 revision 与仓库 Alembic head 一致

---

## 六、事务边界规范（I3 修订）

### 6.1 单条操作

```python
# 事务不变式示意；实际实现使用 SQLAlchemy AsyncSession。
# 会修改核心数据的 important 操作与 audit_log 放在同一 DB 事务内。
async with db.begin():
    question = await load_question(db, question_id)
    apply_question_patch(question, patch)
    db.add(build_question_version(question, snapshot))
    db.add(build_audit_log(action="question.edit", severity="important"))
```

若因兼容原因必须采用“业务更新后事务外写 important audit_log”，补偿回滚不得无条件覆盖当前行，必须带 `updated_at` / version 条件；补偿失败必须告警并追加一条 failed audit，避免并发编辑被旧快照覆盖。

### 6.2 批量操作（默认：单条独立事务）

```python
# batch-approve 不使用大事务，每条记录独立处理；最后追加整体审计记录。
async def batch_approve(question_ids, operator, db):
    success_ids, failed_items = [], []
    for question_id in question_ids:
        try:
            await approve_one(question_id, operator, db)  # 内部事务
            success_ids.append(question_id)
        except Exception as exc:
            failed_items.append({"id": question_id, "reason": str(exc)})
    await write_admin_audit(
        db,
        action="question.batch_approve",
        severity="critical",
        detail={"extra": {"successIds": success_ids, "failedItems": failed_items}},
    )
    return {"successIds": success_ids, "failedItems": failed_items}
```

### 6.3 角色权限变更（必须事务）

```python
async with db.begin():
    await replace_role_permissions(db, role_id, permission_ids)
    db.add(build_audit_log(action="role.update_permissions", severity="critical"))
# 提交成功后刷新 role version，令权限缓存失效。
await redis_set_role_version(role_id)
```

---

## 七、Migration 列表（按 Phase 规划）

| Migration | Phase | 内容 |
|-----------|-------|------|
| f6a7b8c9d0e1_add_admin_core_tables.py | Phase 0-4 已实现 | Alembic revision `f6a7b8c9d0e1`，一次性创建 roles / permissions / subjects / admin_users / role_permissions / audit_logs / question_versions |
| i0e1f2a3b4c5_add_admin_ai_settings.py | Phase 7 已实现 | 创建 admin_ai_settings / admin_ai_usage_monthly，并 seed `ai_setting:read`、`ai_setting:write` 权限 |
| 2f5e1aae7d6c_add_admin_ai_configs_and_admin_ai_model_configs.py | Phase 7+ 扩展 2026-06-10 | 创建 admin_ai_model_configs / admin_ai_configs，包含默认模型 seed 与 17 个默认配置键值 |
| j1f2a3b4c5d6_add_duplicate_question_hash_fields.py | 题库去重已实现 | 为 questions 添加 `question_hash`；为 question_imports 添加 `question_hash`、`duplicate_status`、`duplicate_of_question_id`、`duplicate_of_import_id` 及索引 |
| 0004_audit_log_partition | 生产部署（待确认） | PostgreSQL audit_logs 按月分区；开发/SQLite 不启用，当前 Alembic core migration 未启用 pg_partman |
| 0005_users_add_banned | Phase 2 | users 表新增 is_banned / banned_reason / banned_at / banned_by |
| 0006_question_imports_review | Phase 3 | question_imports 表新增 reject_reason / reviewed_by / reviewed_at |
| 0007_questions_add_index | Phase 3 | questions 表新增复合索引（按需）|

---

## 八、明确不实现（避免 DeepSeek 误加）

- ❌ `question_banks` 表 — 任务范围外，Phase 7+ 再议
- ❌ `tags` 表（`tags` 已有，但当前 Phase 不引入 Admin 端管理）
- ❌ 多租户字段 `tenant_id`
- ❌ MFA 字段 `mfa_secret`
- ❌ `notifications` / `messages` 表

---

## 相关链接

- [[docs/admin/ADMIN_ARCHITECTURE.md|ADMIN_ARCHITECTURE]] — 管理端架构
- [[docs/admin/ADMIN_API_SPEC.md|ADMIN_API_SPEC]] — 管理 API 合约
- [[docs/admin/RBAC_RULES.md|RBAC_RULES]] — RBAC 与身份域
- [[docs/admin/AUDIT_LOG.md|AUDIT_LOG]] — 审计记录
- [[docs/backend/DB_SCHEMA.md|DB_SCHEMA]] — App 数据模型
