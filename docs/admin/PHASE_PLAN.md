# 分阶段开发计划

> 版本：v2.6（已完成能力与后续计划分离） | 状态：Phase 0-7+ 核心能力已实施 | 更新：2026-09-02
> 修订自审计报告 I1（subjects）、I2（明确不实现 question_banks）、C6（question_versions）、C5（audit_log 分级）；2026-05-29 根据维护者确认收敛为现有 FastAPI 后端内实现。
>
> - **变更原因**：同步 Phase 7 后台 AI 解析设置、全局月度额度、权限拦截、前端入口与验证结果。
> - **技术结论**：Admin Backend 位于现有 FastAPI 后端 `/api/admin/v1`；ORM 使用 SQLAlchemy；迁移使用 Alembic；Redis 可选降级；不创建 NestJS/Prisma/BullMQ 独立后端；Phase 1 审计日志同步写入，队列延后；Phase 6 前端位于 `admin-frontend`；Phase 7 AI 设置由后端与 Admin UI 共同实现。
> - **2026-09-02 状态校正**：系统健康、任务/队列/trace、PostgreSQL 备份已落地，使用 `system:read` / `system:write` / `system:backup`；用户/Admin JWT 签名域隔离，部署档案冲突会在启动时拒绝。下文早期“待实现”条目仅保留为历史计划，不代表当前缺失。

> **阅读口径**：本文件保留了各 Phase 的原始验收清单，`DeepSeek 应完成`、`禁止修改` 和部分验收命令属于当时的实施计划。当前实现以 `backend/app/api/v1/admin_*.py`、`backend/app/api/admin/router.py`、`backend/app/services/admin_*.py`、`backend/app/schemas/admin_*.py`、`backend/app/models/` 及 `backend/alembic/versions/` 为准。

---

## 总览

| 阶段 | 名称 | 周期估算 | 核心产出 |
|------|------|---------|---------|
| Phase 0 | 基础设施 + 全表初始化 | 2-3天 | FastAPI Admin 路由骨架、全部新表（含 subjects/audit_logs/question_versions）、Alembic migration、Redis 可选连接 |
| Phase 1 | RBAC 权限体系 | 3-4天 | JWT/FastAPI dependencies/Seed/超管脚本/同步审计日志 |
| Phase 2 | 用户管理系统 | 2天 | app-users + admin-users 两个独立 Admin router/service |
| Phase 3 | 题库管理系统 | 3-4天 | 题目审核、编辑（+ 版本快照）、批量操作、re_pending 状态机 |
| Phase 4 | 科目与导入管理 | 2天 | 科目树 CRUD、导入批次查看、AI 任务监控 |
| Phase 5 | 审计日志与统计 | 已完成 | audit-logs 查询、Dashboard 统计（Redis 可用时缓存防穿透） |
| Phase 6 | 前端 Admin Dashboard | 已完成 | Next.js 16 + React 19 Admin UI，仅消费 `/api/admin/v1` |
| Phase 7 | 后台 AI 解析设置与全局月度额度 | 已完成 | AI 解析开关、月度全局 API 调用额度、用量查询、前端设置页 |
| Phase 7+ | AI 解析设置页配置接口扩展 | 2026-06-10 完成 | 模型配置表、AI 配置键值表、模型列表/更新接口、配置读取/更新接口 |

---

## Phase 0：基础设施 + 全表初始化

### 目标
搭建 FastAPI Admin 路由骨架，**一次性完成所有新表的 migration**（避免后期跨 Phase 加表），建立基础设施（DB / Redis / 统一错误处理 / 健康检查）。

### DeepSeek 应完成

1. **创建 Admin Backend 项目（并入现有 FastAPI）**
   - Admin route 文件位于现有 `backend/app/api/v1/admin_*.py`，由 `backend/app/api/admin/router.py` 聚合；业务服务与 schema 分别位于 `backend/app/services/admin_*.py`、`backend/app/schemas/admin_*.py`，不创建独立 NestJS 项目。
   - 不安装新框架依赖，不创建 Prisma schema。
   - 如需继续拆分模块，必须保持在现有 FastAPI 代码库内完成。

2. **SQLAlchemy / Alembic 初始化与 schema**
   - 以现有 FastAPI backend 的 SQLAlchemy 模型与 Alembic migration 体系为准，创建 Admin 所需模型与迁移。
   - 新表包括：admin_users / roles / permissions / role_permissions / audit_logs
   - 复用已有表（users / questions / question_imports）时，必须先确认兼容性后再写 Alembic migration。
   - `audit_logs` 分区不作为 Phase 0 必落 migration：开发/SQLite 环境不启用分区；生产 PostgreSQL 分区如需启用，属于部署脚本范畴，需单独确认后执行。

3. **目录结构**
   ```
   backend/app/
   ├── api/v1/admin_*.py      # Admin routes，URL 统一 /api/admin/v1
   ├── api/admin/router.py    # Admin router 聚合入口
   ├── schemas/admin_*.py     # Pydantic 请求/响应模型
   ├── services/admin_*.py    # 业务逻辑与事务边界
   ├── models/                # SQLAlchemy Admin 模型
   ├── core/                  # JWT / 安全 / DB / Redis 可选封装
   └── main.py                # 挂载 admin router
   backend/alembic/           # Alembic migrations
   ```

4. **SQLAlchemy Session / Service 层事务控制**

5. **RedisService**（见 REDIS_PLAN.md，含 jitter / 防穿透锁 / role version 工具）
   - 连接失败时静默降级，不阻塞启动

6. **审计日志队列**
   - Phase 0/1 不引入 BullMQ/DLQ；audit_log 先由 FastAPI service 层同步写入
   - 后续如需队列化，必须在不新增独立后端的前提下单独确认

7. **FastAPI middleware / exception handler / response helper**
   - 统一包装业务响应为 Stripe 风格（`{ data, meta }`）
   - 统一错误响应（`{ error: { type, message, hint, field }, meta }`）
   - 全局参数校验，pageSize 上限 100
   - RequestId middleware：生成或透传 `requestId`，写入 `X-Request-Id`；业务 API 注入 `meta.requestId`，该 `requestId` 即全链路 traceId
   - Health 探针保持轻量：可只返回 `X-Request-Id` 响应头，不写 audit_log

8. **环境变量**
   ```env
   APP_ENV=development
   DEPLOYMENT_PROFILE=local_import
   PROCESS_ROLE=web
   DATABASE_URL=sqlite+aiosqlite:///./postgraduate.db
   REDIS_URL=redis://localhost:6379/0
   APP_SECRET=change-me-in-development
   CORS_ORIGINS=["http://localhost:3000"]
   # 生产环境必须同时使用 APP_ENV=production 与 DEPLOYMENT_PROFILE=cloud_api，
   # 并配置 APP_SECRET；USER_JWT_SECRET / ADMIN_JWT_SECRET 可进一步隔离签名根。
   ```

9. **健康检查（I10）**
   - `GET /health/live`
   - `GET /health/ready`
   - `GET /health`

10. **Seed 入口**
    - 当前由应用 bootstrap（`backend/app/services/admin_bootstrap_service.py`）在本地导入档案初始化角色、权限和开发管理员；Alembic revisions 负责表结构
    - 文档早期规划中的 `backend/scripts/seed_admin_*.py` 路径未在当前仓库实现，不应作为现行命令执行

### 验收标准
- `alembic upgrade head` 在干净 DB 上一次性成功；生产启动前 revision 与 Alembic head 一致
- `GET /health/ready`：DB OK 时返回 200；Redis OK 返回 `{ status: "ok", db: "ok", redis: "ok" }`；Redis 不可用但 DB OK 时仍返回 200 且 `redis: "degraded"`
- DB 失败或关键 migration 未完成时，`GET /health/ready` 返回 503
- `GET /health/live` 在 DB/Redis 挂掉时仍返回 200
- 审计日志同步写入能力可用（Phase 0/1 不要求 BullMQ queue/worker）
- 错误响应格式符合 `{ error: { type, message } }`
- 项目可启动，无报错
- 业务 API 响应头 `X-Request-Id` 与响应体 `meta.requestId` 一致；health 探针至少返回 `X-Request-Id`

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
   - 历史计划中的 `seed_admin_permissions.py`、`seed_admin_roles.py`、`init_super_admin.py`、`hash_admin_password.py` 尚未作为独立脚本保留
   - 当前角色/权限 bootstrap 由 `backend/app/services/admin_bootstrap_service.py` 执行；管理员密码由 `backend/app/core/admin_security.py` 的 bcrypt 工具处理

8. **CI 校验**
   - 通过 Python 测试或数据库查询校验 `super_admin` 在 `role_permissions` 中覆盖全部 `permissions`；仓库当前未提供独立 Node CLI

9. **AuditLogService**（同步事务内 + 同步重试 + 异步队列 + fire-forget）

### 验收标准
- 登录失败达到 `ADMIN_LOGIN_MAX_FAILURES`（默认 5；用户名与 IP 维度）→ 返回 429，并带 `Retry-After`
- token 携带 type=app 访问 → 401
- 登出后立即失效
- super_admin 拥有所有权限（DB 查询验证，非代码硬编码）
- 任何 API 创建 role.name=super_admin → 403
- 修改 admin 用户的 role 为 super_admin → 403
- 修改角色权限后，相关用户的下次请求获得新权限（无需登出）
- `init_super_admin.py` 重复执行不会创建第二个 super_admin（幂等）
- 修改密码后，旧 token 立即失效

### 禁止修改
- Phase 0 建立的 SQLAlchemy session / RedisService / FastAPI middleware 与 exception handler
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
   - `PATCH /app-users/:id`：仅允许运营备注/状态类字段；nickname/avatar_url 等微信来源资料默认不可改，若维护者确认允许修改 nickname，必须列字段白名单并写 important audit
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

3. **DB / 既有字段确认**
   - `0006_question_imports_review`：reject_reason / reviewed_by / reviewed_at
   - `0007_questions_add_index`：复合索引（按需）
   - 实施前必须确认 `questions.review_status` 字段是否真实存在、默认值是否为 `approved`、FastAPI 刷题池是否过滤 `review_status='approved' AND is_active=true`
   - 若 `questions.review_status` 不存在，必须单独列 migration 与兼容策略，不能只靠文档约定

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
   - `POST /imports/:batchId/enrich`：仅创建/更新 AI 任务记录与状态展示
     - 写 Redis `admin:ai:task:{taskId}`
     - **不得直接调用 FastAPI API**；如需复用 FastAPI 侧 AI/OCR 逻辑，必须先确认模块边界、调用方式与失败降级
     - 当前 Phase 不实现实际 enrich worker；worker 归属待确认
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

## Phase 5：审计日志与统计（已完成，2026-05-29）

### 目标
audit-logs 查询接口 + Dashboard 统计（含缓存防穿透）。

### 实际完成（2026-05-29）

1. **AuditLogModule**
   - `GET /api/admin/v1/audit-logs`：支持 `page`、`pageSize`、`operatorId`、`action`（`*` 转 LIKE）、`resourceType`、`resourceId`、`severity`、`status`、`from`、`to` 过滤。
   - `GET /api/admin/v1/audit-logs/{audit_log_id}`：返回单条审计日志详情，包含 `detail`、`user_agent`、`error_message`。
   - 权限依赖：`audit:read`。

2. **DashboardModule**
   - `GET /api/admin/v1/dashboard/overview`：统计用户、题目、导入、当日 critical audit 数量，并返回 cache 运行指标。
   - `GET /api/admin/v1/dashboard/daily?from=&to=`：默认近 7 天；支持用户新增、题目新增、导入新增、审计日志数量按日聚合；跨度超过 1 年返回 422。
   - `GET /api/admin/v1/dashboard/questions-stats`：按 `subject`、`review_status`、`difficulty` 聚合题目分布。
   - `overview` 使用现有 `app.core.cache`，Redis 可用时 key 为 `admin:dashboard:overview`，TTL `300 ± 10%`，锁 key 为 `admin:dashboard:overview:lock`，锁 TTL 10 秒；Redis 不可用或未抢到锁且重试 miss 时降级为直接查 DB。

3. **审计查询保护**
   - 未指定 `from` 时默认查询近 183 天。
   - 查询跨度超过 365 天返回 422。
   - `from > to` 返回 422。

### 未实现 / 延后
- 未引入 BullMQ，也未实现每 5 分钟主动刷新 cron；当前为请求触发的缓存 + 防穿透锁，符合“不新增独立后端/不主动加新依赖”约束。
- `release_lock` 当前通过读取锁值后删除实现，未使用 Lua 原子释放；若生产强依赖严格分布式锁语义，需后续单独确认。

### 验收标准
- `GET /dashboard/overview` Redis 命中时走缓存，Redis 不可用时直接查 DB。
- `GET /dashboard/daily` 日期范围校验生效，跨度 > 1 年返回 422。
- `GET /audit-logs` 可查询 1 个月前日志；未指定时间默认近 183 天。
- Phase 5 service tests 覆盖审计查询、统计聚合、cache jitter/lock helper。

### 禁止修改
- Phase 0/1/2/3/4 已完成模块。

### 本阶段完成后更新文档
- `docs/admin/AUDIT_LOG.md`、`docs/admin/ADMIN_API_SPEC.md`、`docs/admin/REDIS_PLAN.md`、`docs/admin/README.md` 已于 2026-05-29 同步 Phase 5 实现。

---

## Phase 6：前端 Admin Dashboard（主要实现已完成，2026-05-30）

### 目标
Next.js 完整后台 UI，仅消费现有 FastAPI Admin API `/api/admin/v1`，不修改后端。

### 实际完成（2026-05-30）

1. **项目与技术栈**
   - 前端位于 `admin-frontend`，使用 Next.js 16.2.6、React 19.2.4、TypeScript、Tailwind CSS 4。
   - 数据请求使用原生 `fetch` 封装 + React Query；列表能力使用 TanStack Table；会话状态使用 Zustand；图表使用 Recharts。
   - API base 默认 `http://localhost:8000/api/admin/v1`，可通过 `NEXT_PUBLIC_ADMIN_API_BASE_URL` 覆盖。

2. **认证与壳子**
   - `/login` 使用后台用户名/密码登录，不接入微信登录。
   - access token 保存在内存态并注入 `Authorization: Bearer <token>`；refresh 依赖 HttpOnly cookie 与 `credentials: include`。
   - Admin Shell 启动时通过 `/auth/me` 或 `/auth/refresh` bootstrap，会话失效跳转 `/login?next=<currentPath>`。
   - 侧边栏按权限展示 Dashboard、app-users、admin-users、questions、review、roles、audit-logs。

3. **页面范围**
   - `/dashboard`：统计卡片、趋势图、题目分布。
   - `/app-users`：小程序用户列表与封禁/解封操作。
   - `/admin-users`：后台管理员列表、创建/编辑/删除、强制登出、重置密码。
   - `/questions`：题库过滤、批量审核、详情/版本信息入口。
   - `/review`：审核工作台，含待审核与 `re_pending` 入口。
   - `/roles`：角色与权限矩阵管理。
   - `/audit-logs`：多维过滤、severity 标识、JSON 详情抽屉。

4. **接口边界与参数修复**
   - Phase 6 不修改后端，仅消费 `/api/admin/v1`。
   - audit-log 查询参数已按后端别名发送：`pageSize`、`resourceType`、`from`、`to`。

5. **验证结果**
   - 已通过 `npm --prefix admin-frontend run lint`。
   - 已通过 `npm --prefix admin-frontend run build`。

### 验收状态
- 权限菜单按 RBAC 权限集合隐藏；后端 RBAC 仍为最终授权来源。
- 重要写操作已按 UI 规则要求提供确认/反馈入口。
- 批量审核与列表操作使用 React Query 刷新相关数据。
- 移动端不作为 Phase 6 适配目标。

### 禁止修改
- 所有 Phase 0-5 已完成后端模块。
- 任何后端 API（Phase 6 仅消费）。

### 本阶段完成后更新文档
- `docs/admin/PHASE_PLAN.md`、`docs/admin/README.md`、`docs/frontend/ADMIN_UI_RULES.md`、`docs/project/CHANGELOG.md` 已于 2026-05-30 同步 Phase 6 前端主要实现。

---

## Phase 7：后台 AI 解析设置与全局月度额度（已完成，2026-05-30）

### 目标
提供后台全局 AI 解析开关、月度全局 API 调用额度配置与用量查询，并在导入 AI 解析任务创建前强制拦截超额或全局关闭场景。

### 实际完成（2026-05-30）

1. **后端模型与迁移**
   - 新增 `admin_ai_settings`：保存全局 AI 解析开关、月度调用额度、更新时间与更新管理员。
   - 新增 `admin_ai_usage_monthly`：按月份聚合 AI 解析调用次数与额度快照。
   - Alembic migration：`i0e1f2a3b4c5_add_admin_ai_settings.py`。

2. **Admin API**
   - `GET /api/admin/v1/ai-settings`：读取当前 AI 解析设置。
   - `PATCH /api/admin/v1/ai-settings`：更新全局开关或月度调用额度。
   - `GET /api/admin/v1/ai-settings/usage`：查询当前或指定月份用量。

3. **RBAC 与 seed**
   - 新增权限：`ai_setting:read`、`ai_setting:write`。
   - 权限已在 bootstrap / migration seed 中写入；`super_admin` 通过 `role_permissions` 绑定权限，非硬编码。

4. **AI 解析拦截**
   - `create_import_enrich_task` 创建任务前调用 `ensure_ai_parse_allowed`。
   - 全局关闭时所有管理员均不可触发 AI 解析；`super_admin` 不绕过全局关闭。
   - 月度额度超限时拦截普通管理员；`super_admin` 仅绕过额度限制，不绕过全局关闭。

5. **前端 Admin UI**
   - 新增独立 `/ai-settings` 页面。
   - 侧边栏新增 AI 设置入口，并按 `ai_setting:read` 权限展示。
   - 页面支持查看/更新全局开关、额度与月度用量。

6. **验证结果**
   - 已通过 `python3 -m compileall backend/app`。
   - 已通过 `npm --prefix admin-frontend run lint`。
   - `npm --prefix admin-frontend run build` 因 Google Fonts 网络获取失败未完成，需联网或字体本地化后复验。

### 验收状态
- AI 解析全局关闭优先级高于额度绕过。
- 月度额度对普通管理员生效，`super_admin` 只绕过额度。
- 新增 API 受 `ai_setting:read` / `ai_setting:write` 保护。
- 前端有独立页面与侧边栏入口。

### 禁止修改
- 不改变 `question_imports + 人工确认` 导入边界。
- 不实现纯 AI 自动入库。
- 不绕过后端 RBAC 与 AI 设置服务直接触发解析。

### 本阶段完成后更新文档
- `docs/admin/README.md`、`docs/admin/PHASE_PLAN.md`、`docs/admin/ADMIN_API_SPEC.md`、`docs/admin/RBAC_RULES.md`、`docs/admin/DB_SCHEMA_ADMIN.md`、`docs/admin/AUDIT_LOG.md`、`docs/frontend/ADMIN_UI_RULES.md`、`docs/project/CHANGELOG.md` 已于 2026-05-30 同步 Phase 7 实现。

---

## Phase 7+：AI 解析设置页面配置接口扩展（2026-06-10 完成）

### 目标
为 AI 解析设置页面（`/ai-settings`）的 3 个配置 UI 组件（ModelCards / OcrAccordion / AiCompletionPreview）补充后端 API、数据库表与持久化逻辑。

### 实际完成（2026-06-10）

1. **数据库表**
   - 新增 `admin_ai_model_configs`：模型配置表（id, name, display_name, provider, api_base_url, api_key_encrypted[Fernet], is_enabled, is_default, sort_order, created_at, updated_at）。
   - 新增 `admin_ai_configs`：AI 配置键值表（config_key[PK], config_value, updated_by, updated_at），含 17 个默认配置项。

2. **Admin API**
   - `GET /api/admin/v1/ai-models`：模型列表（不含 api_key，含 api_configured: bool）。
   - `PATCH /api/admin/v1/ai-models/{id}`：更新模型（api_key="****" 时不修改；设为 default 时清除其他 default；Fernet 加密存储）。
   - `GET /api/admin/v1/ai-configs`：返回扁平 JSON 键值对。
   - `PATCH /api/admin/v1/ai-configs`：部分更新（不存在的 key 忽略；prompt 字段 max_length=5000 校验）。

3. **权限与审计**
   - 复用 `ai_setting:read` / `ai_setting:write`（无需新增权限）。
   - PATCH 操作写审计日志：action=`ai_config.update` / `ai_model_config.update`，severity=normal。

4. **前端对接**
   - ModelCards / OcrAccordion / AiCompletionPreview 对接后端 API。
   - 骨架屏加载态、错误态保留上次数据。
   - 文案提示：模型卡片提示"当前版本实际使用模型为 DeepSeek V4 Flash"；配置区域提示"配置已保存，将在后续版本中生效"。

5. **修复项**
   - prompt 字段 max_length=5000 校验；AiCompletionPreview useEffect 同步 prompt state；TypeScript 类型修正；文案修正 (DeepSeek → DeepSeek V4 Flash)；错误态保留上次值；配置区域提示文案补全。

### 禁止修改
- 不改变 Phase 7 已有的 `admin_ai_settings` / `admin_ai_usage_monthly` 表结构。
- 不改变 `/ai-settings` / `/ai-settings/usage` 已有 API 路径与语义。
- 不改变 `ensure_ai_parse_allowed` 的全局关闭优先于额度绕过语义。

### 本阶段完成后更新文档
- `docs/admin/ADMIN_API_SPEC.md`、`docs/admin/DB_SCHEMA_ADMIN.md`、`docs/admin/AUDIT_LOG.md`、`docs/project/CHANGELOG.md`、`docs/admin/ADMIN_ARCHITECTURE.md`、`docs/frontend/ADMIN_UI_RULES.md`、`docs/admin/PHASE_PLAN.md`、`docs/admin/README.md` 已于 2026-06-10 同步 Phase 7+ 扩展实现。



| 已完成阶段 | 禁止修改 |
|-----------|---------|
| Phase 0 之后 | SQLAlchemy session / RedisService / FastAPI middleware / exception handler / DB schema 主体 |
| Phase 1 之后 | JWT 签发逻辑 / Guard 实现 / permission 命名 / auth API 路径 |
| Phase 2 之后 | AdminUser 表结构 / users 封禁字段 / app-users 与 admin-users API 路径 |
| Phase 3 之后 | 题目审核 API 路径 / question_versions 表结构 / audit_log 写入分级 |
| Phase 4 之后 | Subject 表结构 / Imports API 路径 |
| Phase 5 之后 | Dashboard 接口路径 / audit-logs 查询参数 |
| Phase 7 之后 | AI 设置接口路径 / `ai_setting:*` 权限名 / 全局关闭优先于额度绕过语义 |
| Phase 7+ 之后 | `admin_ai_model_configs` / `admin_ai_configs` 表结构 / `/ai-models` / `/ai-configs` 接口路径与语义 |

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
