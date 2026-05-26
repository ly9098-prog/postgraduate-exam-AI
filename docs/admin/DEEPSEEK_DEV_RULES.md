# 给 DeepSeek V4 Pro 的开发规则

> 版本：v2.0（审计修订版） | 状态：永久约束 | 更新：2026-05-26
> **本文档的所有规则适用于 Admin 系统开发的全部阶段，不可违反。**

---

## 一、首要原则

> **先读文档，再写代码。先问清楚，再动手。**

每次开始一个 Phase 之前：
1. 阅读 `docs/admin/` 下所有相关文档（按 README.md 必读清单）
2. 阅读 `docs/admin/AUDIT_REPORT.md`（理解为什么有这些约束）
3. 确认 Phase 目标与验收标准
4. 文档与需求冲突 → **停下来提问**，不要自行决定

---

## 二、数据库约束

### 2.1 禁止擅自修改 schema

- ❌ 修改已有 migration 文件
- ❌ 直接 `ALTER TABLE` 绕过 Prisma migration
- ❌ 删除任何 admin 系列表
- ❌ 修改 super_admin 角色的 id（必须永远 = 1）或 isSystem 字段
- ✅ 每次变更创建新 migration（格式 `NNNN_describe`）

### 2.2 禁止擅自新增字段

- ❌ 未经评审向 users / questions / question_imports 加字段
- ✅ 新增字段必须有默认值（`NOT NULL DEFAULT ...`）
- ✅ 新增字段必须确认 FastAPI 端兼容性

### 2.3 Prisma 规范

- ✅ 字段命名 `camelCase`，DB 层 `snake_case`（`@map`）
- ✅ 表名 `@@map("snake_case")`
- ❌ `@@ignore` 禁用
- ✅ 外键必须显式定义 relation，禁止裸 Int
- ✅ 大对象表（audit_logs / question_versions）使用 `BigInt` 作为主键

### 2.4 禁止破坏性操作

- ❌ `DROP TABLE`（即使是测试表）
- ❌ `DROP COLUMN`（必须先 `@deprecated` 保留 1 个 Phase）
- ❌ 修改已有列的数据类型
- ❌ 生产环境 `prisma migrate reset`
- ❌ 删除 audit_log 表的任何记录（仅追加）

---

## 三、API 规范约束

### 3.1 命名规范不可修改

- ✅ 路径严格按 `ADMIN_API_SPEC.md`
- ✅ 资源名复数（`/questions` / `/app-users`）
- ✅ 特殊操作动词后缀（`/approve` / `/ban`），禁用 `/update`、`/handle`
- ❌ 创建文档未列出的 API（需先提问）

### 3.2 响应结构（Stripe 风格）

- ✅ 成功响应：`{ data, meta: { requestId, timestamp } }`
- ✅ 错误响应：`{ error: { type, message, hint?, field? }, meta }`
- ❌ 裸 JSON 返回（绕过 ResponseInterceptor）
- ❌ 在 Controller 手动 `return { error: ... }`（必须 throw Exception）
- ❌ 业务 code 与 HTTP code 混用（v2 已统一为 Stripe 风格）

### 3.3 HTTP 状态码

按 `ADMIN_API_SPEC.md §五`，error.type 仅在白名单内取值。

---

## 四、RBAC 一致性约束

### 4.1 权限命名

- ✅ 严格 `resource:action` 小写 + 冒号
- ❌ `viewUsers` / `users_read` / `USER:READ`
- ✅ 与 permissions 表记录一致

### 4.2 Super Admin 保护（强制）

- ❌ 任何 API 不得创建/变更角色为 super_admin
- ❌ 任何 API 不得删除/封禁/修改 super_admin
- ❌ super_admin 之间互删（除自删）
- ✅ super_admin 的权限**通过 role_permissions 表绑定**，不允许 `if (isSuperAdmin) return true` 硬编码

### 4.3 JWT Payload

- ❌ 携带 permissions[] 数组
- ❌ 携带 role.name / password / session_key 等敏感字段
- ✅ 仅含 `{ sub, type, roleId, jti, iat, exp }`
- ✅ type 字段必须等于 "admin"，否则 401

### 4.4 权限缓存一致性

- ✅ 修改角色权限后必须 `bumpRoleVersion(roleId)`
- ✅ 修改用户角色后必须 `clearPermissionCache(userId)`
- ✅ 修改密码后必须 `setUserNbf(userId, now)`
- ❌ 使用 SCAN / KEYS 枚举用户清缓存

---

## 五、类型一致性约束

### 5.1 前后端类型

- ✅ 后端 DTO 变更后同步更新 `src/types/index.ts`
- ✅ ISO 8601 字符串传日期
- ✅ ID 统一 `number`（除 BigInt 表）
- ✅ 枚举用 `as const` 共享常量

### 5.2 Prisma 类型不泄露

- ❌ Controller 直接返回 `prisma.xxx.findMany()` 结果
- ✅ 必须经 Service 映射为 DTO

---

## 六、模块隔离约束

### 6.1 循环依赖

- ❌ Module A → Module B 同时 Module B → Module A
- ✅ 通过 CommonModule 或 EventEmitter 解耦

### 6.2 跨 Phase 修改

- ❌ 修改其他 Phase 已完成模块的 Public API（导出的类、Service 方法签名）
- ⚠️ 必要时提问 + 评估影响

### 6.3 不修改 FastAPI

- ❌ 不调用 FastAPI 的 API
- ❌ 不修改 FastAPI 任何文件
- ✅ 通过共享 DB 通信（仅特定字段）

### 6.4 模块命名

- ✅ `app-users`（小程序用户） vs `admin-users`（后台账号）严格区分
- ❌ 用 `users` 模糊命名

---

## 七、安全约束

### 7.1 密码

- ✅ bcrypt rounds ≥ 12
- ❌ 明文密码 / hash 出现在日志 / 响应 / 错误信息
- ❌ GET 请求传密码
- ✅ CLI 脚本密码从 stdin 读取（不接受 CLI 参数）

### 7.2 SQL 注入

- ✅ 所有查询走 Prisma
- ❌ 拼接原始 SQL 字符串

### 7.3 输入验证

- ✅ 所有 DTO 用 class-validator
- ✅ pageSize ≤ 100
- ✅ 批量 ids.length ≤ 50
- ✅ 时间跨度 ≤ 1 年

### 7.4 敏感信息

- ❌ JWT / 密码 / session_key 入 audit_log / console
- ❌ 错误 stack trace 暴露给生产环境响应

---

## 八、审计日志约束（C5 强制）

### 8.1 分级写入

- ✅ critical 操作 → 同步事务内（与业务一起回滚）
- ✅ important 操作 → 同步 + 重试 3 次失败回滚
- ✅ normal 操作 → BullMQ 队列
- ✅ low 操作 → fire-and-forget

### 8.2 不可篡改

- ❌ UPDATE 已写入 audit_log 记录
- ❌ DELETE audit_log 记录
- ✅ 仅 APPEND-only

### 8.3 detail 字段

- ❌ 包含密码 / token / session_key
- ✅ 超 10KB 自动截断 + `truncated: true`

---

## 九、文档更新义务

每个 Phase 完成后必须按 `PHASE_PLAN.md` 中"本阶段完成后更新文档"要求同步更新 `docs/admin/`：

- 实际代码路径（与规划有出入时）
- 实际 API 请求/响应示例
- 数据库 migration 记录
- 设计决策（为什么这样做）

**文档更新是交付的一部分，不是可选项。**

---

## 十、必须停止并提问的时机

遇到以下情形 **必须停下来提问**，不得自行决定：

1. 文档之间矛盾（如 RBAC_RULES 与 PHASE_PLAN 不一致）
2. 需要新增任何文档未提及的 API
3. 需要新增字段（任何表）
4. 实现某功能有 2 种以上方案
5. 测试时发现 critical 操作 audit_log 写入失败
6. 需要修改其他 Phase 已完成模块
7. Prisma schema 与 DB 出现 drift
8. 任何 super_admin 相关逻辑
9. Redis / DB 降级路径不确定
10. 性能问题（响应 > 1s）需要调整索引
11. 需要引入文档未列出的新依赖包
12. 发现"明确不实现"清单中的功能似乎必要

**提问格式**：
```
[阻塞问题] Phase X - 简短描述
当前情况：...
遇到的问题：...
方案A：... 优点：... 缺点：...
方案B：... 优点：... 缺点：...
我倾向于方案X，因为...
请确认。
```

---

## 十一、必须人工 Review 的模块（I11 新增）

以下文件 / 操作 **必须由项目维护者审核** 后才能合并，DeepSeek 不可自动 commit：

```
[CORE - 安全核心]
1. src/modules/auth/**                      — JWT 签发/验证/黑名单
2. src/modules/rbac/guards/**.guard.ts      — 所有 Guards
3. src/modules/rbac/services/permission.service.ts
4. src/common/decorators/*.decorator.ts     — 权限装饰器
5. src/scripts/init-super-admin.ts          — 超管初始化
6. src/scripts/seed-permissions.ts          — 权限种子
7. src/scripts/seed-roles.ts                — 角色种子
8. src/scripts/hash-password.ts             — 密码哈希工具

[DATA - 数据完整性]
9. prisma/migrations/**                     — 任何 DB migration
10. src/modules/audit-log/**                — 审计日志全模块
11. src/common/interceptors/audit-log.interceptor.ts
12. src/common/interceptors/response.interceptor.ts
13. src/common/filters/*.filter.ts

[SENSITIVE - 敏感操作]
14. 任何包含 "super_admin" 字符串的文件
15. 任何 batch-* API 实现
16. 任何使用 $transaction 的 Service 方法
17. 任何调用 setUserNbf / forceLogout 的实现
18. 任何修改 role_permissions 表的代码

[INFRA - 基础设施]
19. docker-compose.prod.yml / .env.production
20. CI 配置（.github/workflows/**）
21. src/infrastructure/redis/redis.service.ts
22. src/infrastructure/queue/**

[REVIEW - 审核流]
23. 任何 /questions/{id}/approve / reject 实现
24. 任何 question_versions 写入逻辑
25. 任何修改 review_status 的代码
```

**Review 流程**：
1. DeepSeek 完成开发后开 PR
2. PR description 中明确列出涉及的"必须人工 Review"文件
3. 项目维护者逐项检查
4. 通过后才合并

---

## 十二、A-I 八类禁止项汇总

### A. 数据库
```
- 修改已有 migration 文件
- 直接 ALTER TABLE
- 删除 admin 系列表
- 修改 super_admin 角色 id / isSystem
- 给 users / questions 加字段（未经评审）
- production 执行 migrate reset
- DROP TABLE / DROP COLUMN
- 修改已有列数据类型
```

### B. RBAC
```
- 硬编码 if (user.isSuperAdmin) 特权分支（除限定 2 处）
- 提供任何能将用户提升为 super_admin 的 API
- 修改 PermissionsGuard / RolesGuard / JwtAuthGuard 核心逻辑
- 修改权限命名格式
- JWT Payload 添加 permissions / role name / 敏感数据
- 跳过 AuditLogService 直接 prisma.auditLog.create
- 在 normal_user / app_user 上挂 RBAC 逻辑（这两个不参与 RBAC）
```

### C. API
```
- 创建文档未列出的 API
- 修改已发布 API 的请求/响应结构
- 响应混入裸 JSON
- 错误时手动 return { error: ... }
- GET body 传数据
- pageSize > 100
- 批量 ids.length > 50
- 修改 /api/admin/v1 前缀
```

### D. Redis
```
- 使用 admin: 之外的 key 前缀
- 修改 RedisService 封装接口
- 使用 KEYS pattern（必须 SCAN）
- 缓存 TTL 不加抖动（除 lock）
- 密码 / token / session_key 入 Redis
- 直接读 app: 命名空间
```

### E. 审计日志
```
- DELETE / UPDATE 已写入记录
- 跳过 critical / important 操作的同步写日志
- detail 写入密码 / JWT / session_key
- detail > 10KB 不截断
- audit_log 表改名（已固定为 audit_logs）
```

### F. 模块
```
- 循环依赖
- 直接 new Service（必须 DI）
- Controller 直接调 Prisma（必须经 Service）
- Controller 返回 Prisma 原始类型
- 跨 Phase 修改其他 Phase 模块的 Public API
```

### G. 安全
```
- 非 bcrypt 哈希
- bcrypt rounds < 12
- GET / URL 参数传密码
- console.log token / password
- 拼接原始 SQL
- 关闭 ValidationPipe / GlobalExceptionFilter
- production 暴露 /debug / /__internal
- CORS allowlist 配置缺失（不允许 Allow-Origin: *）
```

### H. 范围
```
- 实现 question_banks
- 实现 tags Admin 端
- 实现多租户
- 实现 MFA
- 实现 AI 自动审核
- 实现消息推送
- 实现 /api/v1（无 admin 命名空间）路径
```

### I. 流程
```
- 文档矛盾时自行决策（必须提问）
- 跳过 Phase 验收标准
- 不更新文档就标记 Phase 完成
- 自动合并涉及"必须人工 Review"文件的 PR
- 不写 audit_log 的 critical 操作
```

---

## 十三、Git 工作流（O10）

- 分支命名：`admin/phase-N-<feature>`，如 `admin/phase-0-bootstrap`
- 每个 Phase 一个分支，完成后开 PR 到 `main`
- Commit message 格式：
  ```
  <type>(admin/<module>): <subject>

  - 详细说明
  - Phase: N
  - 涉及人工 Review 文件: [...]
  ```
  type: `feat / fix / docs / refactor / test / chore`
- PR description 必须包含：
  - 涉及哪些 Phase 任务
  - 修改了哪些 Critical 文件
  - 文档同步状态
  - 验收清单（按 PHASE_PLAN.md 验收标准）
