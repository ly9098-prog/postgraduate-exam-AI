# 后台管理系统 — 总体架构设计

> 版本：v2.1（FastAPI 方案确认版） | 状态：可启动开发 | 更新：2026-05-29
> 修订自审计报告 C1/C2、模块拆分调整；2026-05-29 根据维护者确认收敛为现有 FastAPI 后端内实现。
>
> - **变更原因**：Admin Backend 已确认遵循 `docs/PROJECT_RULES.md`，并入现有 FastAPI + SQLAlchemy + Alembic 技术栈；不再采用独立 `NestJS + Prisma + BullMQ` 后端方案。
> - **Phase 4 同步原因**：2026-05-29 根据已完成的科目树与导入管理实现，补充实际 router 注册、Subject/Import service 行为与 Redis 任务指针。
> - **技术结论**：Admin API 统一挂载在 `/api/admin/v1`；ORM 使用 SQLAlchemy；数据库迁移使用 Alembic；Redis 可选且必须可降级；Phase 1 审计日志同步写入，队列能力延后。

---

## 一、系统定位

本后台管理系统（Admin Dashboard）是 2240AI 考研刷题小程序的运营中台，负责：

- 后台管理员账号与权限控制（RBAC）
- 小程序用户管理（查看 / 封禁）
- 题库审核 / 编辑 / 版本管理
- 科目树管理
- AI / OCR 任务监控
- 审计日志（Audit Log）
- 系统统计与报表

**核心设计原则**：
- 长期运营型产品，权限优先 / 可维护性优先 / 不提前过度抽象
- **双身份系统严格隔离**：AppUser（小程序）与 AdminUser（后台）使用不同 JWT、不同表、不同模块
- **零硬编码特权**：super_admin 走 role_permissions 表，不在代码中分支特殊处理（仅初始化与角色保护例外）
- **审计不变式**：Critical 操作必须同步事务内写入 audit_log，失败则操作回滚

---

## 二、双身份系统（重要）

```
┌──────────────────────────────┐  ┌──────────────────────────────┐
│        AppUser（小程序用户）     │  │     AdminUser（后台账号）       │
├──────────────────────────────┤  ├──────────────────────────────┤
│ 表：users                     │  │ 表：admin_users               │
│ 标识：openid                  │  │ 标识：username + password     │
│ JWT type：app                 │  │ JWT type：admin               │
│ JWT 签发：FastAPI             │  │ JWT 签发：FastAPI             │
│ 模块：app-users（只读）        │  │ 模块：admin-users（CRUD）      │
│ 角色：无（不参与 RBAC）         │  │ 角色：super_admin / admin     │
└──────────────────────────────┘  └──────────────────────────────┘
                  │                                │
                  └─── 共享 PostgreSQL ────────────┘
                       共享 Redis（命名空间隔离）
```

**严格约束**：
- AppUser 不进 roles 表，不持有 permissions
- AdminUser 使用 username + password + RBAC 是后台管理系统的显式例外；该例外仅限 `/api/admin/v1`，不改变 AppUser 仍以微信 openid 作为唯一身份的项目规则
- `/api/admin/v1` 收到 `type: "app"` 的 JWT 直接拒绝；小程序端接口收到 `type: "admin"` 直接拒绝
- "用户管理"模块在文档与代码中拆分为：
  - `app-users` — 管理小程序用户（is_banned 等）
  - `admin-users` — 管理后台账号（角色、密码等）

---

## 三、前后端结构

```
┌─────────────────────────────────────────────────────────┐
│                Admin Frontend（待确认 Web UI）            │
│      如后续实现，应仅消费 /api/admin/v1，不新增后端栈       │
└─────────────────┬───────────────────────────────────────┘
                  │ HTTPS + Bearer JWT (type: admin)
┌─────────────────▼───────────────────────────────────────┐
│  Existing FastAPI Backend                               │
│  ┌────────────┐  ┌────────────┐  ┌──────────────────┐   │
│  │ Admin Auth │  │ Admin APIs │  │ Audit/Observe    │   │
│  │ + RBAC     │  │ /admin/v1  │  │ Sync Phase 1     │   │
│  └─────┬──────┘  └─────┬──────┘  └────────┬─────────┘   │
│        │               │                   │             │
│  ┌─────▼───────────────▼───────────────────▼─────────┐  │
│  │ FastAPI dependencies + SQLAlchemy + Alembic + log  │  │
│  └─────┬─────────────────┬───────────────────────────┘  │
│         Base path: /api/admin/v1                         │
└────────┼─────────────────┼───────────────────────────────┘
         │                 │
   ┌─────▼──────┐   ┌──────▼──────┐
   │ PostgreSQL │   │ Redis 可选   │
   │ / SQLite   │   │(degraded)    │
   └────────────┘   └─────────────┘
```

**重要约束**：
- Admin Backend **并入现有 FastAPI Backend**，统一使用 `/api/admin/v1` 路由前缀，不创建新的 NestJS/Prisma/BullMQ 独立服务
- ORM 使用 SQLAlchemy；migration 使用 Alembic，与现有后端迁移体系保持一致
- Admin 模块不通过 HTTP 调用小程序端 API；如需复用 AI/OCR/题库逻辑，优先在同一 FastAPI 代码库内通过 service 层边界复用，并保持 `question_imports + 人工确认` 不变
- Redis 实例可共享，key 命名空间用前缀严格隔离（`admin:` / `app:`），互不读写；Redis 不可用时非关键能力必须降级
- Phase 1 不引入 BullMQ 或新队列依赖；审计日志先同步写入，队列/异步化留待后续 Phase 评估

---

## 四、模块拆分

### Admin Backend (FastAPI)

```
backend/app/
├── api/
│   ├── v1/                    # 小程序端既有 API
│   └── admin/v1/              # Admin API：/api/admin/v1
│       ├── auth.py            # 登录 / 登出 / refresh / me
│       ├── rbac.py            # 角色 / 权限 / 角色权限绑定
│       ├── admin_users.py     # 后台管理员管理（CRUD）
│       ├── app_users.py       # 小程序用户管理（查看 / 封禁）
│       ├── questions.py       # 题目 CRUD / 审核
│       ├── question_versions.py
│       ├── imports.py         # 导入批次查看 / AI 任务状态
│       ├── subjects.py        # 科目树管理
│       ├── audit_logs.py      # 审计日志
│       ├── dashboard.py       # 统计概览
│       └── health.py          # liveness / readiness
├── core/                      # 配置 / 数据库 / 安全 / JWT
├── models/                    # SQLAlchemy 模型（admin_users / roles / permissions ...）
├── schemas/                   # Pydantic 请求/响应模型
├── services/                  # Admin 业务逻辑与事务边界
└── utils/
backend/alembic/               # Alembic migrations
```

**实现映射**：
- NestJS Guard / Decorator 概念统一替换为 FastAPI dependencies（如 `get_current_admin`、`require_permission`、`require_role`）
- PrismaService 替换为现有 SQLAlchemy session / service 层事务控制
- ResponseInterceptor / GlobalExceptionFilter 替换为 FastAPI middleware / exception handler / response helper
- BullMQ queue 不在 Phase 1 实现；审计日志由 service 层同步写入

**Phase 4 实现同步（2026-05-29）**：
- 科目树接口由 `backend/app/api/v1/admin_subjects.py` 提供，导入管理接口由 `backend/app/api/v1/admin_imports.py` 提供；二者在 `backend/app/main.py` 中直接 `include_router` 注册到 `/api/admin/v1`。
- `backend/app/api/v1/admin.py` 仅作为早期聚合导出文件存在，当前路由生效以 `main.py` 的直接注册为准。
- 科目树 service 使用 SQLAlchemy 维护 `subjects`，`path` 按 `code` 拼接（如 `math/math_advanced`），最大层级为 3；删除科目时会拒绝存在子科目或已有 `questions.subject = subjects.code` 引用的记录。
- 导入管理读取既有 `question_imports` 批次与题目明细；`/imports/{batchId}/enrich` 当前创建 AI 辅助任务状态和 `import.enrich` 审计日志，不直接写入 `questions`，也不绕过人工确认流程。
- 导入 AI 任务状态使用 `admin:ai:task:{taskId}` 保存 payload，并使用 `admin:ai:batch:{batchId}:task` 指向该批次最新任务；当前 TTL 为 86400 秒。

### Admin Frontend (Next.js)

```
src/
├── app/
│   ├── (auth)/login/
│   ├── (admin)/
│   │   ├── layout.tsx          # 带权限检查的 Layout
│   │   ├── dashboard/
│   │   ├── app-users/          # 小程序用户
│   │   ├── admin-users/        # 后台账号
│   │   ├── questions/
│   │   ├── review/             # 审核工作台
│   │   ├── subjects/
│   │   ├── roles/
│   │   ├── imports/
│   │   └── audit-logs/
│   └── (errors)/403, 404
├── components/
│   ├── ui/                     # shadcn/ui
│   ├── data-table/             # TanStack Table 封装
│   ├── permission-guard/       # 按钮级权限组件
│   └── layout/
├── lib/
│   ├── api/                    # axios + React Query 封装
│   ├── auth/                   # JWT 存储与刷新（access in memory，refresh in HttpOnly Cookie）
│   └── permissions/            # 前端权限判断（从 /auth/me 缓存 permissions[]）
├── hooks/
│   ├── usePermission.ts
│   └── useCurrentUser.ts
├── store/
│   └── auth.store.ts           # Zustand
└── types/
    └── index.ts                # 与 Backend DTO 同步
```

---

## 五、数据流

```
用户操作
  │
  ▼
Next.js Page (React Query 发起请求，携带 access JWT)
  │
  ▼
FastAPI middleware / dependencies → CORS / RateLimit / RequestId
  │ 生成或透传 requestId；requestId 即全链路 traceId
  ▼
get_current_admin
  │ 1. 验证签名
  │ 2. 校验 type === "admin"
  │ 3. 检查 admin:jwt:blacklist:{jti}（Redis 可用时）
  │ 4. 检查 admin:user:nbf:{userId} > token.iat（Redis 可用时）
  ▼
require_role / require_permission dependencies
  │ 从 admin:perm:user:{userId} 读取权限（含 role-version 比对，Redis 可用时）
  │ Miss / Redis 降级 → 查 DB
  ▼
FastAPI route → Service Layer
  │
  ├──► SQLAlchemy → PostgreSQL/SQLite（事务边界由 Service 显式控制）
  │
  ├──► Redis（缓存 / 限流 / 任务状态，可降级）
  │
  └──► AuditLog（Phase 1 同步写入；detail.extra.requestId 关联应用日志，队列延后）
  │
  ▼
统一响应 helper / exception handler（X-Request-Id + meta.requestId）
  │
  ▼
前端错误提示 / 反馈展示同一 requestId
```

---

## 六、权限流（修订版）

```
JWT Payload（最小集，不包含 permissions）
{
  sub: adminUserId,
  type: "admin",
  roleId: 2,
  jti: uuid,
  iat, exp
}

请求进入
  │
  ▼
get_current_admin
  ├ 验证签名 + type === "admin"
  ├ 检查 admin:jwt:blacklist:{jti}（Redis 可用时）
  └ 检查 admin:user:nbf:{userId}（强制全员失效用，Redis 可用时）
  │
  ▼
require_role
  └ 检查 user.roleId 对应的 role.name 是否满足要求
  │
  ▼
require_permission
  ├ 读取 admin:perm:user:{userId} = { version, permissions }（Redis 可用时）
  ├ 对比 admin:role:version:{roleId}，不匹配则视为失效
  ├ Miss/失效/Redis 降级 → 查 DB 重新加载 → 可用时回写 Redis（TTL 15min ± 抖动）
  └ 检查 permissions 是否包含要求权限
  │
  ▼
Route 执行（Service 层可再次 assert_permission()）
```

**权限命名规范**：`resource:action`（小写 + 冒号）
- `app_user:read` / `app_user:write` / `app_user:ban`
- `admin_user:read` / `admin_user:write` / `admin_user:delete`
- `question:read` / `question:write` / `question:delete` / `question:review`
- `question:batch_review`
- `subject:read` / `subject:write` / `subject:delete`
- `role:read` / `role:write` / `role:delete`
- `permission:read`
- `audit:read`
- `dashboard:read`
- `import:read` / `import:write`

完整权限清单见 [RBAC_RULES.md](./RBAC_RULES.md)。

---

## 七、审核流（含编辑回退状态机）

详细状态机见 [REVIEW_FLOW.md](./REVIEW_FLOW.md)。

简要流程：
```
导入 → pending → approved → editing → re_pending → approved
                       ↓                    ↑
                    archived         （需要 question:review）
```
- 编辑前自动写入 `question_versions` 快照
- 仅有 `question:write` 但无 `question:review` 的角色，编辑后题目自动进入 `re_pending`
- 同时持有两个权限的 admin 编辑后保持 approved（但仍写版本快照）

---

## 八、Redis 使用场景（详见 REDIS_PLAN.md）

| 场景 | Key 模式 | TTL |
|------|----------|-----|
| JWT 黑名单 | `admin:jwt:blacklist:{jti}` | 至 token 过期 |
| 用户级强制失效 | `admin:user:nbf:{userId}` | 永久（覆盖式） |
| 用户权限缓存 | `admin:perm:user:{userId}` | 15min ± 抖动 |
| 角色权限版本号 | `admin:role:version:{roleId}` | 永久（覆盖式） |
| 登录失败计数（IP） | `admin:login:fail:ip:{ip}` | 10min |
| 登录失败计数（账号） | `admin:login:fail:user:{username}` | 30min |
| 管理员在线状态 | `admin:online:{userId}` | 5min |
| OCR 任务状态 | `admin:ocr:task:{taskId}` | 1h |
| AI 任务状态 | `admin:ai:task:{taskId}` | 86400s（Phase 4 enrich） |
| AI 批次最新任务指针 | `admin:ai:batch:{batchId}:task` | 86400s |
| Dashboard 统计 | `admin:stats:overview:{date}` | 5min ± 抖动 |
| 防穿透锁 | `admin:stats:lock:{key}` | 10s |
| 接口限流 | `admin:ratelimit:{userId}:{endpoint}` | 60s |

---

## 九、审计日志策略（修订版）

详细规范见 [AUDIT_LOG.md](./AUDIT_LOG.md)。

**分级写入**：

| Severity | 操作类型 | 写入策略 | 失败处理 |
|----------|---------|---------|---------|
| critical | 删除/批量/角色变更/super_admin相关 | **同步事务内** | 失败 → 业务回滚 |
| important | 编辑/封禁/审核 | 优先与业务更新同一 DB 事务；确需事务外时同步重试 | 事务内失败回滚；事务外补偿必须带版本/updated_at 条件，失败需告警并记录失败审计 |
| normal | 创建/更新简单字段 | Phase 1 同步写入；后续可评估异步队列 | 失败需记录错误日志，关键链路不得静默丢失 |
| low | 登录/登出/敏感查询 | Phase 1 同步或轻量 fire-and-forget（按接口确认） | 仅 error log |

---

## 十、后续扩展策略

1. **新角色扩展**（reviewer / content_editor）：roles 表 + role_permissions 绑定，无需改代码
2. **新权限扩展**：permissions 表新增条目 + 同步加入 super_admin 的 role_permissions（CI 自动校验）
3. **新模块扩展**：FastAPI router + service + schema 隔离，新增模块不影响已有模块
4. **多租户扩展**：admin_users 加 tenant_id 字段（保留预留位）
5. **MFA / 二次验证**：admin_users 加 mfa_enabled / mfa_secret（保留预留位）
6. **审计增强**：audit_log 已有 severity + 分区策略，无需改表结构

---

## 十一、不在本系统范围内（明确排除）

为避免范围蔓延，以下功能**当前不实现**，DeepSeek 不得自行添加：

- `question_banks`（题库分组管理）— Phase 7+ 再议
- 多租户支持
- MFA / 双因子认证
- API 网关 / 微服务拆分
- 用户消息推送 / 邮件通知
- AI 自动审核题目
- 题目导出（CSV / Excel）— Phase 3.5 可选
