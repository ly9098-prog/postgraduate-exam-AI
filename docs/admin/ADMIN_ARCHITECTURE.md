# 后台管理系统 — 总体架构设计

> 版本：v2.0（审计修订版） | 状态：可启动开发 | 更新：2026-05-26
> 修订自审计报告 C1/C2、模块拆分调整、引入 BullMQ

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
│ JWT 签发：FastAPI             │  │ JWT 签发：NestJS              │
│ 模块：app-users（只读）        │  │ 模块：admin-users（CRUD）      │
│ 角色：无（不参与 RBAC）         │  │ 角色：super_admin / admin     │
└──────────────────────────────┘  └──────────────────────────────┘
                  │                                │
                  └─── 共享 PostgreSQL ────────────┘
                       共享 Redis（命名空间隔离）
```

**严格约束**：
- AppUser 不进 roles 表，不持有 permissions
- NestJS 收到 `type: "app"` 的 JWT 直接拒绝；FastAPI 收到 `type: "admin"` 直接拒绝
- "用户管理"模块在文档与代码中拆分为：
  - `app-users` — 管理小程序用户（is_banned 等）
  - `admin-users` — 管理后台账号（角色、密码等）

---

## 三、前后端结构

```
┌─────────────────────────────────────────────────────────┐
│                Admin Frontend (Next.js 15)               │
│         React 19 + TypeScript + shadcn/ui                │
│         TanStack Table + React Query + Zustand           │
│                  Port: 3001 (dev)                        │
└─────────────────┬───────────────────────────────────────┘
                  │ HTTPS + Bearer JWT (type: admin)
┌─────────────────▼───────────────────────────────────────┐
│  Admin Backend (NestJS)                                  │
│  ┌────────────┐  ┌────────────┐  ┌──────────────────┐   │
│  │ Auth/RBAC  │  │ Resources  │  │ Audit/Observe   │   │
│  │ Module     │  │ Modules    │  │ Module          │   │
│  └─────┬──────┘  └─────┬──────┘  └────────┬─────────┘   │
│        │               │                   │             │
│  ┌─────▼───────────────▼───────────────────▼─────────┐  │
│  │  Common Layer (Prisma/Redis/BullMQ/Logger)        │  │
│  └─────┬─────────────────┬─────────────┬─────────────┘  │
│                  Port: 4000 (dev)                        │
└────────┼─────────────────┼─────────────┼────────────────┘
         │                 │             │
   ┌─────▼──────┐   ┌──────▼──────┐  ┌──▼─────────────┐
   │ PostgreSQL │   │    Redis    │  │ BullMQ Workers │
   │ (共享)      │   │(命名空间隔离)│  │ (audit/stats)  │
   └────────────┘   └─────────────┘  └────────────────┘
```

**重要约束**：
- Admin Backend 与 小程序 FastAPI Backend **共享同一 PostgreSQL 数据库**
- Admin Backend **不调用** FastAPI Backend 的 API，只通过 Prisma 直接读写 DB
- Redis 实例共享，key 命名空间用前缀严格隔离（`admin:` / `app:`），互不读写
- 部署时 Admin Backend 与 FastAPI Backend 并行运行，不互相依赖
- BullMQ 用于 Normal 级别审计日志的异步写入（Critical/Important 同步写）

---

## 四、模块拆分

### Admin Backend (NestJS)

```
src/
├── main.ts
├── app.module.ts
├── modules/
│   ├── auth/                  # 登录 / 登出 / refresh / me
│   ├── rbac/                  # 角色 / 权限 / 角色权限绑定（合并的 RBAC 域）
│   ├── admin-users/           # 后台管理员管理（CRUD）
│   ├── app-users/             # 小程序用户管理（查看 / 封禁）
│   ├── questions/             # 题目 CRUD
│   ├── question-versions/     # 题目历史版本（编辑快照）
│   ├── question-imports/      # 导入批次查看
│   ├── review/                # 审核工作流（独立模块，不混在 questions）
│   ├── subjects/              # 科目树管理
│   ├── audit-log/             # 审计日志（替代 operation-logs，命名更准确）
│   ├── dashboard/             # 统计概览
│   └── health/                # liveness / readiness
├── common/
│   ├── guards/                # JwtAuthGuard / RolesGuard / PermissionsGuard
│   ├── decorators/            # @Roles / @Permissions / @Public / @CurrentUser / @AuditLog
│   ├── interceptors/          # ResponseInterceptor / AuditLogInterceptor
│   ├── filters/               # GlobalExceptionFilter
│   ├── dto/                   # PaginationDto / IdParamDto 等
│   └── utils/
├── infrastructure/
│   ├── prisma/                # PrismaService 封装
│   ├── redis/                 # RedisService 封装（含 namespace 工具）
│   └── queue/                 # BullMQ 封装（audit-log queue / stats queue）
└── scripts/
    ├── init-super-admin.ts    # 超管初始化（仅 docker exec / SSH 执行）
    ├── seed-permissions.ts    # 权限表种子
    ├── seed-roles.ts          # 角色 + role_permissions 种子（super_admin 全权限）
    └── hash-password.ts       # bcrypt 密码生成工具
```

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
NestJS Middleware → CORS / RateLimit
  │
  ▼
JwtAuthGuard
  │ 1. 验证签名
  │ 2. 校验 type === "admin"
  │ 3. 检查 admin:jwt:blacklist:{jti}
  │ 4. 检查 admin:user:nbf:{userId} > token.iat
  ▼
RolesGuard / PermissionsGuard
  │ 从 admin:perm:user:{userId} 读取权限（含 role-version 比对）
  │ Miss → 查 DB → 回写 Redis
  ▼
Controller → Service Layer
  │
  ├──► Prisma → PostgreSQL（事务边界由 Service 显式控制）
  │
  ├──► RedisService（缓存 / 限流 / 任务状态）
  │
  └──► AuditLog（Critical 同步事务内 / Normal 入 BullMQ 队列）
  │
  ▼
ResponseInterceptor → 统一响应格式
  │
  ▼
GlobalExceptionFilter（异常时介入，返回 Stripe 风格错误响应）
  │
  ▼
前端
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
JwtAuthGuard
  ├ 验证签名 + type === "admin"
  ├ 检查 admin:jwt:blacklist:{jti}
  └ 检查 admin:user:nbf:{userId}（强制全员失效用）
  │
  ▼
RolesGuard
  └ 检查 user.roleId 对应的 role.name 是否满足 @Roles()
  │
  ▼
PermissionsGuard
  ├ 读取 admin:perm:user:{userId} = { version, permissions }
  ├ 对比 admin:role:version:{roleId}，不匹配则视为失效
  ├ Miss/失效 → 查 DB 重新加载 → 回写 Redis（TTL 15min ± 抖动）
  └ 检查 permissions 是否包含 @Permissions() 要求
  │
  ▼
Controller 执行（Service 层可再次 assertPermission()）
```

**权限命名规范**：`resource:action`（小写 + 冒号）
- `app_user:read` / `app_user:write` / `app_user:ban`
- `admin_user:read` / `admin_user:write` / `admin_user:delete`
- `question:read` / `question:write` / `question:delete` / `question:review`
- `question:batch_review`
- `subject:read` / `subject:write` / `subject:delete`
- `role:read` / `role:write`
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
| AI 任务状态 | `admin:ai:task:{taskId}` | 1h |
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
| important | 编辑/封禁/审核 | 同步（事务外） | 重试 3 次失败 → 业务回滚 |
| normal | 创建/更新简单字段 | BullMQ 队列异步 | DLQ 兜底 |
| low | 登录/登出/敏感查询 | fire-and-forget | 仅 error log |

---

## 十、后续扩展策略

1. **新角色扩展**（reviewer / content_editor）：roles 表 + role_permissions 绑定，无需改代码
2. **新权限扩展**：permissions 表新增条目 + 同步加入 super_admin 的 role_permissions（CI 自动校验）
3. **新模块扩展**：NestJS 按 Module 隔离，新增模块不影响已有模块
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
