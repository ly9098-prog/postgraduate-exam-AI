# 数据库设计规划

> 版本：v2.1（FastAPI 方案确认版） | 状态：可启动开发 | 更新：2026-05-29
> ORM：SQLAlchemy | DB：PostgreSQL（生产共享实例）/ SQLite（开发兼容）
> 修订自审计报告 I1（新增 subjects）、C6（新增 question_versions）、C5（operation_logs → audit_log + severity）、O1（IP 字段）、C1（双身份系统说明）
>
> - **变更原因**：2026-05-29 同步 Admin Backend 已并入 FastAPI + SQLAlchemy + Alembic 的实际实现，并补充 Phase 4 科目树/导入管理对应的 Alembic migration 归属说明。

---

## 一、设计原则

1. Admin 系统新增表使用独立命名空间前缀 `admin_`，避免与小程序 FastAPI 表冲突
2. 小程序已有表（`users`, `questions`, `question_imports`, 等）**默认只读**，新增字段必须经过评审走 migration
3. 字段命名：Prisma 层 `camelCase`，DB 层 `snake_case`（通过 `@map`）
4. 每次 DB 变更必须创建新 migration，**禁止修改已有 migration 文件**
5. 删除字段前先标记 `@deprecated` 并保留 1 个 Phase 后再删除

---

## 二、新增表设计

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

**初始数据种子**（C1 修订：移除 normal_user）：
```
name=super_admin, displayName="超级管理员", isSystem=true
name=admin,       displayName="普通管理员", isSystem=true
```

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
- 分区属于生产 PostgreSQL 部署脚本，不由 Prisma schema 直接表达；Prisma model 仅表达逻辑字段，避免与 PostgreSQL 分区主键形成两套真相。
- 如启用分区，生产 DDL 必须统一主键口径：分区父表主键需包含分区键 `created_at`（如 `PRIMARY KEY (id, created_at)`），应用层仍以 `id` 作为展示与查询标识。
- `pg_partman` 是否启用、归档策略与维护任务需单独确认，不要求 Phase 0 直接落地。
- 6 个月前的日志自动归档至 `audit_logs_archive` 表（可后期迁 S3 / Parquet），仅在生产分区方案确认后启用。

**生产分区脚本示例（待确认，非 Prisma migration 必选项）**：
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

---

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

Prisma 映射：
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

**编辑流程**（C6）：
- 持有 `question:write` + `question:review` 的 admin 编辑：保持 `approved` 状态，但写 question_versions
- 仅持有 `question:write` 的 admin 编辑：`approved → re_pending`，写 question_versions，等待 reviewer 重审

---

### 3.3 question_imports（导入批次）— 新增字段

**Phase 3 新增**（审核操作记录）：
```sql
ALTER TABLE question_imports
  ADD COLUMN reject_reason TEXT,
  ADD COLUMN reviewed_by INTEGER REFERENCES admin_users(id),
  ADD COLUMN reviewed_at TIMESTAMP;
```

Prisma 映射：
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
| questions | 既有索引 + `(subject, review_status, is_active, created_at)` 复合索引 | 审核列表高频查询 |
| users | 既有 `openid` + `is_banned`（部分索引）| 过滤封禁用户 |
| question_imports | 既有 + `reviewed_by` | 反查审核人 |

**部分索引示例**（PostgreSQL 特性）：
```sql
CREATE INDEX idx_users_banned ON users (created_at) WHERE is_banned = TRUE;
CREATE INDEX idx_questions_pending ON questions (created_at) WHERE review_status = 'pending';
```

---

## 五、Prisma 使用规范

```
admin-backend/
├── prisma/
│   ├── schema.prisma         # 完整 schema
│   ├── migrations/           # 版本化 migration 文件（NNNN_describe）
│   └── seed.ts               # 调用 src/scripts/seed-*.ts
└── src/
    ├── infrastructure/prisma/
    │   └── prisma.service.ts # NestJS 可注入封装
    └── scripts/
        ├── init-super-admin.ts
        ├── seed-permissions.ts
        ├── seed-roles.ts
        ├── seed-subjects.ts
        └── hash-password.ts
```

**规范要求**：
1. 每次 DB 变更必须创建新 migration（禁止修改已有文件）
2. 所有 migration 必须可回滚（提供 `down` 备注或方案）
3. Prisma 字段 `camelCase`，DB 层 `snake_case`（`@map`）
4. 表名 `@@map("snake_case")`
5. 删除字段前先标记 `@deprecated`，保留 1 个 Phase 再删
6. 禁止 `@@ignore`
7. 外键关系必须显式定义，禁止裸 `Int` 代替 relation
8. 任何 migration 提交前必须本地 `prisma migrate diff` 检查
9. CI 中跑 `prisma db pull` diff 检查，发现 schema drift 阻止合并（O5）

---

## 六、事务边界规范（I3 修订）

### 6.1 单条操作

```typescript
// 会修改核心数据的 important 操作优先与 audit_log 放在同一 DB 事务内
await prisma.$transaction(async (tx) => {
  const updated = await tx.question.update({ where: { id }, data: { ... } });
  await tx.questionVersion.create({ data: snapshot });
  await tx.auditLog.create({ data: { action: 'question.edit', severity: 'important', ... } });
  return updated;
});
```

若因兼容原因必须采用“业务更新后事务外写 important audit_log”，补偿回滚不得无条件覆盖当前行，必须带 `updated_at` / version 条件；补偿失败必须告警并追加一条 failed audit，避免并发编辑被旧快照覆盖。

### 6.2 批量操作（默认：单条独立事务）

```typescript
// batch-approve 不使用大事务，每条独立处理
async batchApprove(ids: number[], operator: AdminUser) {
  const results = { success: [], failed: [] };
  for (const id of ids) {
    try {
      await this.approve(id, operator); // 内部事务
      results.success.push(id);
    } catch (e) {
      results.failed.push({ id, reason: e.message });
    }
  }
  // 整体写一条 audit_log（severity: critical，含 success / failed 明细）
  await this.auditLog.write({
    action: 'question.batch_approve',
    severity: 'critical',
    detail: { extra: { successIds: results.success, failedItems: results.failed } },
  });
  return results;
}
```

### 6.3 角色权限变更（必须事务）

```typescript
await prisma.$transaction(async (tx) => {
  await tx.rolePermission.deleteMany({ where: { roleId } });
  await tx.rolePermission.createMany({ data: ... });
  await tx.auditLog.create({ data: { action: 'role.update_permissions', severity: 'critical', ... } });
});
// 事务外刷新 role version
await redis.set(`admin:role:version:${roleId}`, uuid());
```

---

## 七、Migration 列表（按 Phase 规划）

| Migration | Phase | 内容 |
|-----------|-------|------|
| f6a7b8c9d0e1_add_admin_core_tables.py | Phase 0-4 已实现 | Alembic revision `f6a7b8c9d0e1`，一次性创建 roles / permissions / subjects / admin_users / role_permissions / audit_logs / question_versions |
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
