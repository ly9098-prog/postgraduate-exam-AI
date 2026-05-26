# 分阶段开发计划

> 版本：v2.0（审计修订版） | 状态：可启动开发 | 更新：2026-05-26
> 修订自审计报告 I1（subjects）、I2（明确不实现 question_banks）、C6（question_versions）、C5（audit_log 分级）

---

## 总览

| 阶段 | 名称 | 周期估算 | 核心产出 |
|------|------|---------|---------|
| Phase 0 | 基础设施 + 全表初始化 | 2-3天 | 项目骨架、全部新表（含 subjects/audit_logs/question_versions）、Redis/BullMQ 连接 |
| Phase 1 | RBAC 权限体系 | 3-4天 | JWT/Guards/Decorators/Seed/超管脚本 |
| Phase 2 | 用户管理系统 | 2天 | app-users + admin-users 两个独立模块 |
| Phase 3 | 题库管理系统 | 3-4天 | 题目审核、编辑（+ 版本快照）、批量操作、re_pending 状态机 |
| Phase 4 | 科目与导入管理 | 2天 | 科目树 CRUD、导入批次查看、AI 任务监控 |
| Phase 5 | 审计日志与统计 | 2天 | audit-logs 查询、Dashboard 统计（含缓存防穿透） |
| Phase 6 | 前端 Admin Dashboard | 4-6天 | Next.js 完整 UI |

---

## Phase 0：基础设施 + 全表初始化

### 目标
搭建 NestJS 骨架，**一次性完成所有新表的 migration**（避免后期跨 Phase 加表），建立基础设施（DB / Redis / BullMQ / 全局拦截器 / 健康检查）。

### DeepSeek 应完成

1. **创建 NestJS 项目**
   ```bash
   nest new admin-backend
   cd admin-backend
   npm install @nestjs/config @nestjs/jwt @nestjs/passport @nestjs/bullmq
   npm install prisma @prisma/client ioredis bullmq bcryptjs uuid
   npm install class-validator class-transformer
   npm install --save-dev @types/bcryptjs @types/uuid
   ```

2. **Prisma 初始化与 schema**
   - 配置 `prisma/schema.prisma`（连接现有 PostgreSQL）
   - 创建所有新表 model：
     - admin_users / roles / permissions / role_permissions / audit_logs
     - subjects / question_versions
   - 映射已有表（users / questions / question_imports）只读
   - 执行 `prisma migrate dev --name 0001_init_admin_tables`
   - 执行 `prisma migrate dev --name 0002_init_subjects`
   - 执行 `prisma migrate dev --name 0003_init_question_versions`
   - 执行 `prisma migrate dev --name 0004_audit_log_partition`（启用 pg_partman 分区）

3. **目录结构**
   ```
   src/
   ├── main.ts
   ├── app.module.ts
   ├── modules/
   │   └── health/
   ├── common/
   │   ├── guards/
   │   ├── decorators/
   │   ├── interceptors/  # ResponseInterceptor / AuditLogInterceptor
   │   ├── filters/       # GlobalExceptionFilter
   │   ├── dto/
   │   └── utils/
   ├── infrastructure/
   │   ├── prisma/
   │   ├── redis/         # RedisService + jitter / tryLock / releaseLock
   │   └── queue/         # BullMQ Module（audit-log queue）
   └── scripts/
   ```

4. **PrismaService**（NestJS 可注入）

5. **RedisService**（见 REDIS_PLAN.md，含 jitter / 防穿透锁 / role version 工具）
   - 连接失败时静默降级，不阻塞启动

6. **BullMQ 配置**
   - 注册 `audit-log` queue
   - DLQ（dead-letter queue）配置
   - 启动 worker（同进程或独立 worker 均可）

7. **全局拦截器与过滤器**
   - `ResponseInterceptor`：统一包装为 Stripe 风格（`{ data, meta }`）
   - `GlobalExceptionFilter`：统一错误响应（`{ error: { type, message, hint, field } }`）
   - `ValidationPipe`：全局参数校验，pageSize 上限 100
   - `RequestIdInterceptor`：注入 `meta.requestId`

8. **环境变量**
   ```env
   DATABASE_URL=
   REDIS_URL=
   JWT_ACCESS_SECRET=
   JWT_REFRESH_SECRET=
   JWT_ACCESS_EXPIRES=2h
   JWT_REFRESH_EXPIRES=7d
   BCRYPT_ROUNDS=12
   NODE_ENV=development
   PORT=4000
   CORS_ORIGINS=http://localhost:3001
   ```

9. **健康检查（I10）**
   - `GET /health/live`
   - `GET /health/ready`
   - `GET /health`

10. **Seed 入口**
    - `prisma/seed.ts` 调用 `src/scripts/seed-permissions.ts` + `src/scripts/seed-roles.ts` + `src/scripts/seed-subjects.ts`

### 验收标准
- `prisma migrate deploy` 在干净 DB 上一次性成功
- `GET /health/ready` 返回 `{ status: "ok", db: "ok", redis: "ok" }`
- `GET /health/live` 在 DB/Redis 挂掉时仍返回 200
- BullMQ queue 启动成功，可见 worker 日志
- 错误响应格式符合 `{ error: { type, message } }`
- 项目可启动，无报错

### 禁止修改
- 现有 FastAPI 后端任何文件
- 已有数据库表结构（除本 Phase 创建新表外）

### 本阶段完成后更新文档
- `docs/admin/ADMIN_ARCHITECTURE.md`（补充实际端口、目录结构）
- `docs/admin/DB_SCHEMA_ADMIN.md`（补充 migration 文件 hash）

---

## Phase 1：RBAC 权限体系

### 目标
完整的认证 + 授权体系：JWT 登录/刷新/登出 + 三层权限控制 + Super Admin 初始化脚本 + Seed 完整权限/角色数据。

### DeepSeek 应完成

1. **AuthModule**
   - `POST /auth/login`：双维度限流（IP + 用户名），统一错误信息防枚举
   - `POST /auth/logout`：jti 写入 Redis 黑名单
   - `POST /auth/refresh`：refresh token in HttpOnly cookie
   - `GET /auth/me`：返回 user + role + permissions
   - `POST /auth/change-password`：更新 nbf，强制全员重新登录

2. **JWT Strategy**
   - Payload 仅含 `{ sub, type, roleId, jti, iat, exp }`
   - **严禁**在 Payload 携带 permissions
   - 校验 type === "admin"

3. **Guards**
   - `JwtAuthGuard`：签名 + 黑名单 + nbf 检查
   - `RolesGuard`：检查 @Roles()
   - `PermissionsGuard`：读 Redis（含 role-version 比对）→ Miss 查 DB → 回写

4. **Decorators**
   - `@CurrentUser()` / `@Roles(...)` / `@Permissions(...)` / `@Public()`
   - `@AuditLog({ action, severity })`（仅用于 normal/low 自动日志）

5. **RolesModule**
   - `GET /roles` / `GET /roles/:id`
   - `POST /roles`（不允许 name=super_admin）
   - `PATCH /roles/:id`（不可改 isSystem）
   - `PUT /roles/:id/permissions`（事务内更新 + bump version + 写 audit critical）
   - `DELETE /roles/:id`（isSystem 拒绝）

6. **PermissionsModule**
   - `GET /permissions` / `GET /permissions/by-category`

7. **Seed 脚本**
   - `seed-permissions.ts`：写入完整权限清单（见 RBAC_RULES.md §二）
   - `seed-roles.ts`：创建 super_admin（绑定全部 permissions） + admin（绑定运营权限）
   - `init-super-admin.ts`：从 stdin 读密码 → bcrypt(12) → 创建 → 写 audit critical
   - `hash-password.ts`：CLI 工具，stdin 输入密码 → 输出 bcrypt hash

8. **CI 校验**
   - `npm run check:super-admin-coverage`：校验 super_admin 拥有全部权限

9. **AuditLogService**（同步事务内 + 同步重试 + 异步队列 + fire-forget）

### 验收标准
- 登录失败 5 次（同用户名）→ 锁定，但响应仍为"用户名或密码错误"
- 登录失败 10 次（同 IP）→ 锁定
- token 携带 type=app 访问 → 401
- 登出后立即失效
- super_admin 拥有所有权限（DB 查询验证，非代码硬编码）
- 任何 API 创建 role.name=super_admin → 403
- 修改 admin 用户的 role 为 super_admin → 403
- 修改角色权限后，相关用户的下次请求获得新权限（无需登出）
- `init-super-admin.ts` 重复执行不会创建第二个 super_admin（幂等）
- 修改密码后，旧 token 立即失效

### 禁止修改
- Phase 0 建立的 PrismaService / RedisService / 全局拦截器
- audit_logs 表结构

### 本阶段完成后更新文档
- `docs/admin/RBAC_RULES.md`（补充实际代码路径）
- `docs/admin/ADMIN_API_SPEC.md`（补充 auth 接口请求/响应示例）

---

## Phase 2：用户管理系统

### 目标
拆分**两个独立模块**：app-users（小程序用户）+ admin-users（后台账号）。

### DeepSeek 应完成

1. **AppUsersModule**（小程序用户，C1）
   - `GET /app-users`：分页 + 过滤（keyword/isBanned/created时间范围）
   - `GET /app-users/:id`：详情（练题数 / 错题数 / 最近活跃）
   - `PATCH /app-users/:id`：编辑 nickname（important 审计）
   - `POST /app-users/:id/ban`：封禁（important 审计 + 同步重试）
   - `POST /app-users/:id/unban`：解封

2. **DB Migration**
   - `0005_users_add_banned`：users 表新增 is_banned / banned_reason / banned_at / banned_by
   - **执行前确认 FastAPI 端不会因此报错**（FastAPI 当前 ORM 模型仅映射部分字段，新增列向前兼容）

3. **AdminUsersModule**（后台管理员，C1）
   - `GET /admin-users` / `GET /admin-users/:id`
   - `POST /admin-users`：创建（roleId 不能为 super_admin）
   - `PATCH /admin-users/:id`：更新（不可改 super_admin / 不可改自己的 role）
   - `DELETE /admin-users/:id`：删除（不可删 super_admin / 不可删自己）→ critical 审计 + 事务内
   - `POST /admin-users/:id/force-logout`：更新 nbf
   - `POST /admin-users/:id/reset-password`：管理员重置他人密码

4. **关键代码约束**
   - 任何角色变更操作前调用 `assertNotSuperAdmin(targetUser)`
   - 任何 admin 操作其他 admin 前调用 `assertNotSelf(operator, targetId)`

### 验收标准
- 用户列表分页 / 过滤正常
- 封禁后 audit_log 包含 banned_by 关联
- 创建 admin 时角色不能 = super_admin
- 删除自己 → 422
- 删除 super_admin → 403
- 重置密码后，目标 admin_user 的 nbf 已更新
- 修改 users 表后 FastAPI 端依然正常运行（兼容性验证）

### 禁止修改
- Phase 1 建立的 Guards / Decorators
- questions 表结构

### 本阶段完成后更新文档
- `docs/admin/DB_SCHEMA_ADMIN.md`（补充 0005 migration 记录）
- `docs/admin/RBAC_RULES.md`（补充实际 super_admin 保护代码位置）

---

## Phase 3：题库管理系统

### 目标
完整审核工作流（含 re_pending 状态机）+ 版本快照 + 批量操作。

### DeepSeek 应完成

1. **QuestionsModule**
   - `GET /questions`：多维过滤
   - `GET /questions/:id`：详情（含原始 question_import）
   - `PATCH /questions/:id`：编辑
     - 事务内：写 question_versions → update questions → 根据权限决定 review_status
     - important 审计
   - `DELETE /questions/:id`：软删（is_active=false）→ critical 审计
   - `POST /questions/:id/approve` / `reject`：important 审计
   - `POST /questions/batch-approve` / `batch-reject`：每条独立事务 + 整体 critical 审计
   - `PATCH /questions/:id/toggle-active`：important 审计

2. **QuestionVersionsModule**
   - `GET /questions/:id/versions`：版本列表
   - `GET /questions/:id/versions/:version`：单版本详情

3. **DB Migration**
   - `0006_question_imports_review`：reject_reason / reviewed_by / reviewed_at
   - `0007_questions_add_index`：复合索引（按需）

4. **核心实现要点**
   - 编辑时区分操作者权限：
     - 持有 question:review → 保持 approved
     - 仅持有 question:write → 进入 re_pending
   - 版本号自增：`SELECT MAX(version) + 1 FROM question_versions WHERE question_id = ?`
   - 批量接口必须返回 `successIds + failedItems` 明细

### 验收标准
- 单条 approve 响应 < 500ms
- 批量 50 条响应 < 3s
- 编辑后 question_versions 表新增一条
- 仅有 write 权限的 admin 编辑后题目 → re_pending
- audit_log.detail 包含完整 `{ before, after }`
- 批量返回 failedItems 明细
- 审核拒绝必须有 reason（empty 返回 422）

### 禁止修改
- question_imports 表结构（仅追加 Phase 3 列）
- users 表
- Phase 0/1/2 已完成模块

### 本阶段完成后更新文档
- `docs/admin/ADMIN_API_SPEC.md`（补充实际响应示例）
- `docs/admin/REVIEW_FLOW.md`（补充实际代码路径与权限矩阵）

---

## Phase 4：科目与导入管理

### 目标
科目树 CRUD + 导入批次查看 + AI 任务状态监控。

### DeepSeek 应完成

1. **SubjectsModule**
   - `GET /subjects`：树形结构（依据 path 字段构建）
   - `GET /subjects/:id`
   - `POST /subjects`：创建（自动计算 path）
   - `PATCH /subjects/:id`：编辑
   - `DELETE /subjects/:id`：有题目 → 422

2. **ImportsModule**
   - `GET /imports`：批次列表
   - `GET /imports/:batchId`：详情（题目分页）
   - `POST /imports/:batchId/enrich`：触发 AI 任务
     - 写 Redis `admin:ai:task:{taskId}`
     - 触发实际 AI 服务（调用 FastAPI 的 enrich API 或内置 worker）
   - `GET /imports/:batchId/status`：读 Redis 任务状态

### 验收标准
- 科目树正确返回层级（最大深度 3）
- 删除有题目的科目 → 422 + business_rule_violation
- path 字段在创建/移动时自动更新
- AI 任务状态可轮询

### 禁止修改
- Phase 0/1/2/3 已完成模块
- 现有 question_imports 表结构（除 Phase 3 已加字段）

### 本阶段完成后更新文档
- `docs/admin/ADMIN_ARCHITECTURE.md`（补充科目模块数据流）

---

## Phase 5：审计日志与统计

### 目标
audit-logs 查询接口 + Dashboard 统计（含缓存防穿透）。

### DeepSeek 应完成

1. **AuditLogModule**
   - `GET /audit-logs`：多维过滤（含 severity 过滤）
   - `GET /audit-logs/:id`：详情

2. **DashboardModule**
   - `GET /dashboard/overview`：缓存 5min ± 抖动 + 防穿透锁
   - `GET /dashboard/daily?from=&to=`
   - `GET /dashboard/questions-stats`
   - 主动刷新：BullMQ cron 每 5min 触发刷新（Phase 5 实现）

3. **审计查询保护**
   - 查询跨度 > 1 年 → 422
   - 默认仅返回近 6 个月（明确指定 from 才查更早）

### 验收标准
- Overview 缓存命中下响应 < 200ms
- 并发 100 请求 cache miss 时，DB 仅被查询一次（防穿透锁验证）
- 查询 1 个月前的日志正常
- Redis 不可用时降级为直接查 DB（无 500）

### 禁止修改
- Phase 0/1/2/3/4 已完成模块

### 本阶段完成后更新文档
- `docs/admin/AUDIT_LOG.md`（补充分区维护脚本）

---

## Phase 6：前端 Admin Dashboard

### 目标
Next.js 完整后台 UI。

### DeepSeek 应完成

1. **项目初始化**
   ```bash
   npx create-next-app@latest admin-frontend --typescript --tailwind --app
   cd admin-frontend
   npx shadcn-ui@latest init
   npm install @tanstack/react-table @tanstack/react-query zustand axios
   ```

2. **登录页 `/login`**
   - 用户名+密码表单
   - 显示锁定状态（仅在响应中明确返回时）
   - access in memory，refresh in HttpOnly cookie

3. **Layout**（权限菜单）
   - 侧边栏按 permissions 动态显示
   - 顶部栏：用户信息 / 登出 / 切换密码

4. **app-users 页面**
   - TanStack Table
   - 封禁/解封按钮（PermissionGuard）

5. **admin-users 页面**
   - 列表 + 创建 / 编辑 / 删除
   - 不可操作 super_admin 行（前端禁用 + 后端保护）

6. **questions 页面**
   - 多过滤栏
   - 批量选择 + 批量审核（带确认弹窗）
   - 详情抽屉（侧滑）
   - 版本历史 Tab

7. **审核工作台 `/review`**
   - 快速审核模式
   - re_pending 单独 Tab（diff 高亮对比）

8. **Dashboard**
   - 统计卡片 + 折线图（recharts）

9. **角色权限管理 `/roles`**
   - 权限矩阵编辑（按 category 分组展示）
   - 修改后弹窗确认（critical 操作）

10. **审计日志 `/audit-logs`**
    - 多维过滤 + JSON 详情展示
    - severity 颜色标识

### 验收标准
- 权限菜单 / 按钮按 RBAC 隐藏
- 批量审核有 loading + 结果反馈（成功 / 失败明细）
- 版本对比 diff 正确高亮
- 移动端不要求适配
- 任何写操作有二次确认（重要操作）

### 禁止修改
- 所有 Phase 0-5 已完成模块
- 任何后端 API（仅消费）

### 本阶段完成后更新文档
- `docs/admin/ADMIN_ARCHITECTURE.md`（补充前端模块结构）
- 新建 `docs/frontend/ADMIN_UI_RULES.md`

---

## 阶段间不可修改约定

| 已完成阶段 | 禁止修改 |
|-----------|---------|
| Phase 0 之后 | PrismaService / RedisService / 全局拦截器 / DB schema 主体 |
| Phase 1 之后 | JWT 签发逻辑 / Guard 实现 / permission 命名 / auth API 路径 |
| Phase 2 之后 | AdminUser 表结构 / users 封禁字段 / app-users 与 admin-users API 路径 |
| Phase 3 之后 | 题目审核 API 路径 / question_versions 表结构 / audit_log 写入分级 |
| Phase 4 之后 | Subject 表结构 / Imports API 路径 |
| Phase 5 之后 | Dashboard 接口路径 / audit-logs 查询参数 |

**修改已完成阶段必须**：
1. 提出变更原因（写入 commit message）
2. 评估影响范围
3. 同步更新对应 docs
4. 写 audit_log（severity: critical）

---

## 明确不实现（避免范围蔓延）

DeepSeek **不得**自行实现以下功能（即使认为有价值）：

- ❌ `question_banks`（题库分组） — Phase 7+ 再议
- ❌ `tags` 表的 Admin 端管理
- ❌ 多租户支持
- ❌ MFA / 双因子认证
- ❌ 题目导出 CSV/Excel（Phase 3.5 可选，需先确认）
- ❌ AI 自动审核题目
- ❌ 用户消息推送 / 邮件通知
- ❌ API 网关 / 微服务拆分
- ❌ 题目回滚 rollback 功能（API 路径已预留，实现留待 Phase 3.5+）
- ❌ 操作员二次密码确认（X-Confirm-Password Header 预留，实现留待未来）

如需实现以上任一项，DeepSeek **必须先停下来提问确认**。
