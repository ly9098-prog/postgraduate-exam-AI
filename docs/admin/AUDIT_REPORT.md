# 后台管理系统规划方案 — 生产环境级架构审计报告

> 审计日期：2026-05-26
> 审计对象：Sonnet 生成的 9 份规划文档
> 审计标准：长期运营型生产环境产品
> 审计目标：避免 3-6 个月后被迫大重构

---

# 一、总体审计结论

## 当前架构等级

> **C+（在 0~A 区间）** — 可作为开发起点，但有 3 处 Critical 隐患必须先改，否则一定在 3-6 个月内造成重构。

## 当前风险等级

| 维度 | 评分 | 说明 |
|------|------|------|
| 文档完整度 | A | 9 份文档体系覆盖全面，超出预期 |
| 模块拆分 | B+ | NestJS 模块边界清晰，但缺 question_banks/subjects 设计 |
| RBAC 设计 | **C-** | **存在权限模型混乱、SuperAdmin 硬编码、JWT 设计错误三个高危问题** |
| Prisma/DB | C | subjects 表完全缺失，question_imports 状态机不完整，事务边界未定义 |
| Redis | B | 命名空间隔离 OK，但 TTL 雪崩、登录限流单维度、权限缓存清理粒度粗 |
| API 规范 | B+ | 命名清晰，但响应结构 HTTP 与业务 code 双码混用 |
| 审核流 | C+ | 状态机不完整（编辑后是否重审未定义） |
| 操作日志 | C | 异步写入 + 失败仅打 log，关键操作日志可丢失 |
| DeepSeek 约束 | A- | 规则详尽，但缺"必须人工 Review"清单 |

## 是否适合直接开发

> **不允许直接开发**。

需先修正下列 **6 个 Critical 问题**，再启动 Phase 0；其余 **11 个 Important 问题** 应在 Phase 1 完成前修复。

## 是否建议先修正

> **强烈建议先修正**。

修正成本：约 0.5 天文档调整。
不修正代价：3-6 个月后必然重构（涉及 RBAC 模型、operation_logs 表结构、API 响应规范），代价 ≥ 5-10 天 + 数据迁移风险。

---

# 二、高危问题（Critical）— 必须开发前修复

## C1. 用户身份模型混乱（双身份系统未隔离）

### 问题描述
- 现有 `users` 表（小程序用户）：以 `openid` 为唯一标识，**无 role 字段**
- 新增 `admin_users` 表（后台账号）：用户名+密码，有 `role_id`
- 但 `RBAC_RULES.md` 把 `normal_user` 列为**系统角色**之一
- `JWT Payload` 中又写 `role: "super_admin" | "admin" | "normal_user"`

### 为什么危险
小程序端用户根本不登录后台、不签发 admin JWT、不进 RBAC 体系。把 `normal_user` 列为系统角色是**概念混淆**：
- 如果 normal_user 进 roles 表，则需要为每个小程序用户建一条 admin_users 关联记录 → 数据爆炸
- 如果不进 roles 表，则文档自相矛盾，DeepSeek 实施时一定卡住或乱写
- JWT 不会出现 `role: "normal_user"` 这种 Payload，因为小程序用 FastAPI 签的不是同一套 JWT

### 未来如何恶化
Phase 2 开发"用户管理"时直接卡死：
- 是把 users 表数据当 admin_users 表处理？还是新建关联？
- 后期想给小程序用户加权限（如 VIP 用户）时，会被迫把 RBAC 强行套到 users 表上 → 大重构

### 修改建议
1. **删除 `normal_user` 角色**（从 roles 表、RBAC_RULES、JWT Payload 全部移除）
2. **明确两个身份系统**：
   - `AppUser`（users 表）— 小程序用户，无 role，由 FastAPI 管理
   - `AdminUser`（admin_users 表）— 后台账号，有 role，由 NestJS 管理
3. **JWT 区分签发**：
   - 小程序 JWT：`{ sub: appUserId, type: "app" }`（FastAPI 签发）
   - 后台 JWT：`{ sub: adminUserId, type: "admin", roleId }`（NestJS 签发）
4. **校验**：NestJS 收到 `type: "app"` 的 JWT 直接拒绝；反之亦然

---

## C2. JWT Payload 携带 permissions[] — 严重设计错误

### 问题描述
`ADMIN_ARCHITECTURE.md` 第 156 行：
```
JWT Payload {
  sub, role,
  permissions: ["user:read", ...]  // 缓存在 Redis
  iat, exp
}
```
同时又说"权限列表优先从 Redis 取"。

### 为什么危险
**JWT 是签名后不可变的**。一旦把 permissions 写进 JWT：
1. **权限收回失效**：管理员被降权后，旧 token 仍持有原 permissions[]，必须把 token 加入黑名单才能踢出
2. **Token 体积膨胀**：当前 17 个权限就已较长；后期加 reviewer/content_editor 等角色，permissions 可能 30+ 项 → 每次请求 Header 多带几 KB
3. **冗余字段诱导错误**：开发者会下意识从 JWT 取权限（不查 Redis），导致权限变更不生效的隐性 bug
4. **代码两套真相**：JWT 里一份 + Redis 里一份，必然不一致

### 未来如何恶化
- 6 个月后某次紧急权限收回，发现"已收回的管理员还能用"，定位到 JWT 残留 → 必须改 JWT 结构 → 所有已签发 token 强制失效 → 全员重新登录
- 引入 reviewer 角色后 JWT 体积超过反向代理 Header 限制（如 nginx 默认 8K）

### 修改建议
**JWT Payload 仅放最小信息**：
```typescript
{
  sub: adminUserId,    // 用户ID
  type: "admin",       // 防止与小程序 JWT 混用
  roleId: 2,           // 仅 ID，不放 name
  jti: uuid,           // 用于黑名单
  iat, exp
}
```
- permissions **完全从 Redis 取**，Redis Miss 走 DB
- `GET /auth/me` 单独返回 `{ user, role, permissions: [] }` 给前端缓存
- 增加 `admin:user:tokens-not-before:{userId}` key（存储该用户 token 必须晚于的时间戳），用于强制失效全部已签发 token（行业标准方案）

---

## C3. Super Admin 跳过 role_permissions 表 — 隐性权限漏洞

### 问题描述
`RBAC_RULES.md` 第 73 行：
> super_admin = ALL permissions（**不走 role_permissions 表，代码层直接放行**）

`PermissionsGuard` 实现会变成：
```typescript
if (user.isSuperAdmin) return true;  // 硬编码特权分支
return userPermissions.includes(required);
```

### 为什么危险
1. **隐式权限授予**：新增模块时（如未来加 `payment:write`），super_admin 自动获得，开发者意识不到
2. **合规审计灾难**：合规要求"列出某用户拥有的所有权限"——硬编码用户没法被 SQL 查询到
3. **特权分支是漏洞温床**：任何业务代码只要写 `if (!user.isSuperAdmin && !hasPermission)`，就有可能写错（漏 `!`、写成 `||` 等）
4. **测试覆盖盲点**：自动化测试用 super_admin 时通过，用 admin 时失败，bug 在生产环境才发现
5. **无法实现"super_admin 临时降权"** 等审计功能

### 未来如何恶化
- 6 个月后引入合规要求（数据隐私法/GDPR），需要列出"谁能访问用户PII"——硬编码用户查不出来 → 重写 PermissionsGuard
- 引入"super_admin 也要审计敏感操作"时，硬编码分支无法 hook

### 修改建议
**super_admin 必须走 role_permissions 表**：
1. Seed 脚本初始化时，把所有 permission 全部绑定到 super_admin role
2. 新增权限的 migration 必须**强制把新权限加到 super_admin 角色**（添加自动化检查）
3. PermissionsGuard 统一逻辑：`return userPermissions.includes(required)`，**消除所有特权分支**
4. 仅在"修改/删除 super_admin 账号"等极少数地方保留显式判断

---

## C4. Super Admin 初始化方案 B 严重不安全 — 立即删除

### 问题描述
`RBAC_RULES.md` 5.3 方案 B：
```bash
# docker-compose.prod.yml 中临时添加
SUPER_ADMIN_OPENID=<你的openid>
SUPER_ADMIN_INIT=true  # 运行一次后自动清除该逻辑
```

### 为什么危险
1. **环境变量持久化**：`docker-compose.prod.yml` 文件改了就是改了，"运行一次后清除"在容器内做不到（容器重启会再次读取）
2. **概念错误**：`SUPER_ADMIN_OPENID` 这个名字本身就违背了规划——`admin_users` 表用用户名密码登录，不用 openid（与 C1 关联）
3. **泄露风险**：compose 文件通常进 git 仓库，secret 直接暴露
4. **可重放攻击**：只要 compose 文件还有这两个变量，任何人重启服务就触发提权
5. **审计缺失**：没有任何痕迹证明谁在何时触发了提权

### 修改建议
**完全删除方案 B**。

保留方案 A（CLI + docker exec）和方案 C（DB 直写）即可，但需补充：

**方案 A 改进**：
- 删除多余的 `SUPER_ADMIN_INIT_TOKEN`（docker exec 已经具备执行权限，token 是冗余的）
- 脚本必须检查 `admin_users` 表是否已存在 super_admin，存在则拒绝
- 脚本执行后必须打印 `INSERT 操作的事务 ID`，并写入 operation_logs（operatorId=null, action=`system.init_super_admin`, ip=`<bootstrap>`）
- **生产环境脚本必须强制要求 stdin 输入密码**，禁止从 CLI 参数传密码（避免落入 shell history）

**方案 C 改进**：
- 必须使用 `bcrypt` 预先生成 password_hash（提供独立小工具：`npm run hash-password`）
- 生产 DB 直写后必须立即 `git tag` 该时刻的 schema，方便审计

---

## C5. operation_logs 异步写入 + 失败仅打 log — 审计日志可丢失

### 问题描述
`OPERATION_LOG.md` 第 130 行：
> - 日志写入**异步执行**，不阻塞 API 响应
> - 写日志失败**不影响主流程**（只打 error log）

`LoggingInterceptor` 实现使用 `tap()` 异步写入。

### 为什么危险
1. **关键操作日志丢失**：管理员误删 1000 道题、批量封禁用户、修改角色权限——这些是**法务追责的核心证据**。一旦 Redis/DB 抖动导致写入失败，仅"打 error log"，无法重建审计链
2. **`tap()` 异步在进程崩溃时直接丢**：Node 进程异常退出时，事件循环中的未完成写入直接消失
3. **violation of audit invariant**：合规上要求"操作即记录"，异步写入违反这个不变式
4. **没有兜底队列**：没有用 BullMQ / Redis Stream / 本地文件 backup

### 未来如何恶化
- 引入合规审计后，发现某段时间日志缺失 → 重新设计写入机制 → 重写 LoggingInterceptor
- 出现"管理员说自己没操作"的争议时，无法举证

### 修改建议
**分级日志写入策略**：

| 操作类型 | 写入策略 | 失败处理 |
|---------|---------|---------|
| Critical（删除/批量/角色变更/super_admin相关）| **同步写入，在事务内** | 写日志失败 → 整个操作回滚 |
| Important（编辑/封禁/审核）| 同步写入，事务外 | 失败重试 3 次，仍失败则操作结果回滚 |
| Normal（创建/更新简单字段）| 异步写入，BullMQ 队列 | 队列重试 + DLQ 兜底 |
| Low（登录/登出/查询敏感数据）| 异步 fire-and-forget | 失败仅打 error log |

**Critical/Important 操作必须在 Service 层显式写日志**，不依赖 LoggingInterceptor。

---

## C6. 审核流状态机不完整 — 已发布题目编辑后无重审机制

### 问题描述
`REVIEW_FLOW.md` 状态机仅描述：
```
pending → approved（写入 questions, is_active=true）
pending → rejected
approved → 下架（is_active=false）
```

但忽略了关键问题：**已 approved 的题目被 admin 编辑后，状态如何变化？**

`ADMIN_API_SPEC.md` 中 `PATCH /questions/{id}` 仅需 `question:write` 权限（非 review），编辑完成后题目仍是 approved + is_active=true。

### 为什么危险
1. **绕过审核**：拥有 `question:write` 但无 `question:review` 的角色（如 content_editor），可以通过编辑实质性修改题目内容（如答案）但不触发审核 → 是**权限越级漏洞**
2. **历史数据丢失**：编辑前的版本未存档，无法回滚
3. **数据库 review_status 字段语义冲突**：现有 questions.review_status 默认 "approved"，那它到底跟踪的是什么生命周期？

### 未来如何恶化
- reviewer 角色启用后，审核员发现题目被随意修改 → 投诉权限混乱
- 出现错题反馈时无法追溯"哪个版本的题目导致用户答错"

### 修改建议
**完善状态机**：
```
状态：pending → approved → editing → re_pending → approved
                       ↓                        ↑
                    archived            （需要 question:review 权限）
```
**新增表 `question_versions`**（记录每次编辑的快照）：
```prisma
model QuestionVersion {
  id          Int      @id @default(autoincrement())
  questionId  Int      @map("question_id")
  version     Int                          // 版本号
  content     Json
  options     Json?
  answer      String   @db.Text
  analysis    String?  @db.Text
  editedBy    Int      @map("edited_by")   // admin_user.id
  editReason  String?  @map("edit_reason") @db.Text
  createdAt   DateTime @default(now()) @map("created_at")

  @@index([questionId, version])
  @@map("question_versions")
}
```
**编辑流程**：
1. 编辑题目时先把当前版本写入 `question_versions`
2. 修改 questions 表数据
3. 如果 admin 同时具备 `question:review` → 直接保持 approved
4. 如果 admin 仅有 `question:write` → 题目变 `re_pending`，需 reviewer 重新审核

---

# 三、中风险问题（Important）— Phase 1 完成前修复

## I1. subjects 表完全缺失（任务明确要求但未设计）

任务要求列出 subjects 表，但 `DB_SCHEMA_ADMIN.md` 完全没有 subjects 表的设计。
现状：questions.subject 是裸 String(32) 字段（"408" / "math" / "english"）。
PHASE 4 又要做"科目树管理"。

**修改建议**：补充 `subjects` 表 schema：
```prisma
model Subject {
  id        Int       @id @default(autoincrement())
  parentId  Int?      @map("parent_id")
  code      String    @unique @db.VarChar(32)   // 408_ds, math_advanced
  name      String    @db.VarChar(64)
  level     Int       @default(1)               // 1=主科目, 2=子科目
  sortOrder Int       @default(0) @map("sort_order")
  isActive  Boolean   @default(true) @map("is_active")
  createdAt DateTime  @default(now()) @map("created_at")

  parent    Subject?  @relation("SubjectHierarchy", fields: [parentId], references: [id])
  children  Subject[] @relation("SubjectHierarchy")

  @@index([parentId])
  @@index([code])
  @@map("subjects")
}
```
同时定义 questions.subject 与 subjects.code 的关联策略（保留 String 字段作为 denormalize，由触发器或应用层保证一致性）。

## I2. question_banks 模块完全缺失

任务要求关注 question_banks，但规划中无任何设计。
建议：明确告知"当前阶段不实现 question_banks"，作为 Phase 7+ 预留；并在文档中显式记录该决策原因（避免 DeepSeek 自行实现）。

## I3. 批量操作事务边界未定义

`POST /questions/batch-approve { ids: [1,2,3,...] }` 返回 `{ success: 45, failed: 5 }`：
- 是否在单事务中执行？
- 中途失败的题目，前面已成功的是否回滚？

**修改建议**：明确策略——
- **单条独立事务**（推荐）：每条独立 try/catch，互不影响。**符合用户预期**
- 必须强制要求：批量操作返回明细 `failedItems: [{ id, reason }]`
- 必须强制要求：批量操作整体写一条 operation_log（action=batch_approve, detail 含 successIds + failedItems），而非 50 条单独日志

## I4. Redis 缓存雪崩与击穿风险

所有 TTL 写死（5min/15min/24h），无抖动；缓存 Miss 后无锁。

**修改建议**：
- 所有 TTL 加 **±10% 随机抖动**：`ttl = base + random(-base*0.1, base*0.1)`
- 关键缓存（dashboard 统计）使用 **SETNX 锁 + stale-while-revalidate**：缓存过期后只允许一个请求查 DB，其他请求返回旧值
- Dashboard 统计改用**主动定时刷新**（cron 5min），消除 Lazy 过期带来的雪崩

## I5. 登录限流单维度（仅按 IP）— 撞库 + 误锁双风险

### 撞库
攻击者用代理池/IPv4 池，每个 IP 失败 4 次就换，绕过限流。

### 误锁
公司 NAT 出口共享同一公网 IP，一个同事错密码会锁全公司。

**修改建议**：双维度限流
```
admin:login:fail:ip:{ip}        TTL 10min, threshold 10
admin:login:fail:user:{username} TTL 30min, threshold 5
```
任一维度达到阈值 → 锁定。Username 级别锁定时返回"账号已锁定"，IP 级别锁定时返回"IP已锁定"，避免攻击者通过错误信息差异判断用户名是否存在（**用户名枚举防御**）：实际响应均为通用"登录失败"。

## I6. 权限缓存清理粒度粗 — 大用户量下性能瓶颈

"角色的权限配置变更时，批量删除所有持有该角色的用户缓存"——SCAN 或者全表查 userId 清理。

**修改建议**：使用 **role version** 机制
```
admin:role:version:{roleId} → 时间戳/uuid（角色每次更新时刷新）
admin:perm:{userId} → { version, permissions[] }
```
权限验证时比对 version；不一致则视为缓存失效，重新拉取。
避免 SCAN 操作。

## I7. operation_logs 无分区与归档策略

按月分区只在"扩展建议"中一笔带过，未列入 PHASE 计划。
当前估算：每个管理员日均 50 操作 × 10 个 admin = 500/天 × 365 = 18 万/年。
detail 平均 2KB → 单年 360MB。3 年后查询变慢。

**修改建议**：在 PHASE 5 显式列出：
- 启用 `pg_partman` 按月分区
- 6 个月以上日志冷归档（移到 `operation_logs_archive` 或 S3 Parquet）
- 提供查询时自动跨分区聚合

## I8. API 响应结构 HTTP + 业务 code 双码混用

错误响应同时携带 HTTP 403 和 业务 code 40301——前端必须既看 HTTP status 又看 code，逻辑复杂。

**修改建议**：选定一种风格并贯彻：

**推荐 Stripe 风格**：
- HTTP 状态码精确表达 HTTP 错误（401/403/404/422/500）
- 业务 code **仅在 HTTP 200 时使用**（业务异常）
- 错误响应包含 `{ error: { type, message, hint } }` 结构化对象

或者完全使用 Java 风格（HTTP 永远 200，业务 code 区分一切错误），不要混用。

## I9. JWT 黑名单缺失"用户级强制失效"机制

当 super_admin 想强制踢出某个 admin 的所有会话（如怀疑账号被盗）时，必须枚举该用户的所有 jti——做不到。

**修改建议**：增加用户级 not-before 时间戳：
```
admin:user:nbf:{userId} → timestamp
```
JWT 验证时：`if (jwt.iat < nbf) reject`。强制踢出只需更新此 key 即可。

## I10. health check 无分级（liveness vs readiness）

`GET /health` 返回 `{ status, db, redis }` — 但 K8s/Docker 部署时需要分别的探针。

**修改建议**：
- `GET /health/live` — 进程是否活着（不依赖 DB/Redis）
- `GET /health/ready` — 是否可以接收流量（依赖 DB 必须 OK，Redis 可降级）
- `GET /health` — 综合状态，仅供运营查看

## I11. 缺失"必须人工 Review 的模块"清单

`DEEPSEEK_DEV_RULES.md` 列了禁止项，但**没有明确哪些 PR 必须人工审核后再合并**。

---

# 四、低风险优化项（Optional）

| # | 问题 | 建议 |
|---|------|------|
| O1 | `operation_logs.ip` 字段 VarChar(64) 过大 | IPv6 最多 39 字符，改 VarChar(45) |
| O2 | `admin_users.email` 无 unique index | 后期想加 email 登录时无法直接用 |
| O3 | `subjects` 树形仅靠 parent_id，深层查询需递归 | 加 `path String`（物化路径）字段，如 `/1/3/15` |
| O4 | 缺 idempotency-key 设计 | 关键写操作（批量审核）支持 `Idempotency-Key` Header |
| O5 | 缺 DB schema 变更通知机制 | FastAPI 端给 users 加字段时，Prisma schema 不会自动同步——增加 CI 中的 `prisma db pull` diff 检查 |
| O6 | 错误码命名前缀冗余（40001/40101/40301）| 加业务分类前缀，如 1001/1002/2001/3001 |
| O7 | 没有"管理员密码强制 N 天后修改"机制 | 后期合规要求时再加，不阻塞当前 |
| O8 | 没有 audit 日志的 file 数字签名 | 高合规场景需要，当前阶段不需要 |
| O9 | 缺 API rate limit 的全局豁免名单 | 内部健康检查/监控需要走特殊路径 |
| O10 | 文档缺 git workflow 规范 | DeepSeek 不知道如何提交 PR |

---

# 五、推荐修正方案

## 5.1 推荐架构（修正后）

```
┌─────────────────────────────────────────────────────────┐
│                Admin Frontend (Next.js 15)               │
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
│  │  Common Layer (Prisma/Redis/Queue/Logger)         │  │
│  └─────┬─────────────────┬─────────────┬─────────────┘  │
└────────┼─────────────────┼─────────────┼────────────────┘
         │                 │             │
   ┌─────▼──────┐   ┌──────▼──────┐  ┌──▼─────┐
   │ PostgreSQL │   │    Redis    │  │ BullMQ │
   │ (共享)      │   │ (Namespaced) │  │ Queue  │
   └────────────┘   └─────────────┘  └────────┘
                                          │
                              ┌───────────▼──────────┐
                              │ Async Workers        │
                              │ (audit log, stats)   │
                              └──────────────────────┘
```

## 5.2 推荐模块拆分（按职责重组）

```
src/
├── modules/
│   ├── auth/                  # 登录/登出/refresh/me
│   ├── rbac/                  # 角色 + 权限 + 用户角色绑定
│   ├── admin-users/           # 后台管理员管理
│   ├── app-users/             # 小程序用户管理（区分命名！）
│   ├── questions/             # 题目 CRUD
│   ├── question-versions/     # 题目历史版本
│   ├── question-imports/      # 导入批次
│   ├── review/                # 审核工作流（独立模块，不混在 questions 内）
│   ├── subjects/              # 科目树
│   ├── audit-log/             # 操作日志（替代 operation-logs，命名更准确）
│   ├── dashboard/             # 统计
│   └── health/                # 健康检查
├── common/                    # Guards/Decorators/Interceptors/DTO 基类
├── infrastructure/            # Prisma/Redis/BullMQ
└── scripts/                   # CLI 脚本
    ├── init-super-admin.ts
    ├── seed-permissions.ts
    └── hash-password.ts
```

**关键重构**：
- `users` 模块拆为 `app-users` 和 `admin-users` 两个独立模块（避免歧义）
- `review` 独立成模块（不混在 questions 内）
- `operation-logs` 改名为 `audit-log`（更准确）

## 5.3 推荐 Redis 策略

```
admin:
├── jwt:
│   ├── blacklist:{jti}          → "1"          TTL=剩余有效期
│   └── nbf:user:{userId}         → timestamp    无 TTL
├── perm:user:{userId}            → { v, perms } TTL=15min±jitter
├── role:version:{roleId}         → uuid         无 TTL
├── login:
│   ├── fail:ip:{ip}              → counter      TTL=10min
│   └── fail:user:{username}      → counter      TTL=30min
├── stats:
│   ├── overview:{date}           → JSON         TTL=5min±jitter
│   └── lock:{key}                → "1"          TTL=10s（防穿透锁）
└── ratelimit:{userId}:{endpoint} → counter      TTL=60s
```

## 5.4 推荐 Prisma 设计（关键调整）

| 调整项 | 原方案 | 推荐方案 |
|--------|--------|---------|
| AdminUser.role | 单 role_id | 保留单 role_id（KISS），不引入多角色（除非确实需要） |
| Role 系统角色 | 删除 normal_user | 仅保留 super_admin / admin |
| Permission 表 | 简单 resource:action | 加 `category` 字段（user/content/system），便于前端 UI 分组 |
| RolePermission | OK | OK |
| OperationLog | 异步写 | 改名 AuditLog；Critical 类型同步事务内写；增加 `severity` 字段（critical/important/normal） |
| Subject | 缺失 | **必须新增**（见 I1） |
| QuestionVersion | 缺失 | **必须新增**（见 C6） |
| Users 加 is_banned | OK | 同时加 `banned_by` (Int) 关联 admin_user |

## 5.5 推荐 RBAC 方案

**核心原则**：
1. 没有任何代码硬编码 super_admin 特权（除登录初始化、角色变更保护两处）
2. JWT 仅放 sub/roleId/jti/type，不放 permissions
3. permissions 全部走 Redis + DB，使用 role-version 机制保证一致性
4. 双层防御：
   - **接口层**：`@Permissions()` 装饰器
   - **服务层**：操作敏感数据时再次校验（如 admin_users 模块所有写操作显式调用 `assertPermission()`）
5. 引入"敏感操作二次验证"机制（删除批量、修改 super_admin 等需要重输密码或 MFA），写入文档预留位

---

# 六、最终是否允许 DeepSeek 开始开发

## **不允许** ❌

## 原因

- 存在 6 个 Critical 问题，其中 C1（身份模型混乱）、C2（JWT 设计错误）、C3（super_admin 硬编码）会**直接污染整个系统骨架**
- 这 3 个问题一旦在代码中固化，后期修复成本约 5-10 天 + 数据迁移风险
- 修复成本：约 0.5 天文档调整 + 0.5 天与你确认决策 = 1 天
- ROI 极高，必须先修

## 允许开发的前置条件

修复以下文档：
1. `RBAC_RULES.md` — 删除 normal_user，删除方案 B，super_admin 走 role_permissions
2. `ADMIN_ARCHITECTURE.md` — JWT Payload 不放 permissions，区分 type=admin/app
3. `DB_SCHEMA_ADMIN.md` — 新增 subjects、question_versions 表
4. `REVIEW_FLOW.md` — 完善 editing/re_pending 状态机
5. `OPERATION_LOG.md` — 改名 audit_log，分级写入策略
6. `ADMIN_API_SPEC.md` — 统一 HTTP/业务 code 风格
7. `REDIS_PLAN.md` — TTL 抖动 + 双维度登录限流 + role-version 机制
8. `PHASE_PLAN.md` — Phase 0 增加 subjects/question_versions 表创建
9. `DEEPSEEK_DEV_RULES.md` — 加入"必须人工 Review 模块"清单

修复完成后即可启动 Phase 0。

---

# 七、DeepSeek 禁止修改清单（详细）

## A. 数据库相关

```
[绝对禁止]
- 修改任何已有 migration 文件内容
- 直接执行 ALTER TABLE 绕过 Prisma migration
- 删除 admin_users / roles / permissions / role_permissions 表
- 修改 super_admin 角色的 id（必须永远 = 1）
- 修改 system 内置角色的 isSystem=true 字段
- 给 questions 表加新字段（除非有明确文档授权）
- 修改 users 表的 openid 列定义
- 在 production 环境执行 prisma migrate reset
- DROP TABLE / DROP COLUMN（即使有备份）
```

## B. RBAC 相关

```
[绝对禁止]
- 在代码中硬编码 if (user.isSuperAdmin) 特权分支（除限定的 2 处）
- 提供任何能将用户角色变更为 super_admin 的 API
- 修改 @Permissions / @Roles 装饰器实现
- 修改 PermissionsGuard / RolesGuard / JwtAuthGuard 核心逻辑（C/U 后必须人工 Review）
- 修改权限命名格式（必须严格 resource:action 小写冒号）
- 在 JWT Payload 中添加 permissions / role name / 任何敏感数据
- 跳过 LoggingInterceptor 直接返回 Controller
- 在 normal_user / app_user 上挂 RBAC 逻辑（这是小程序用户，不参与 RBAC）
```

## C. API 相关

```
[绝对禁止]
- 创建文档未列出的 API 路径
- 修改已发布 API 的请求/响应结构（向下兼容除外）
- 在响应中混入裸 JSON（绕过 ResponseInterceptor）
- 在错误时手动 return { error: ... }（必须 throw 标准 Exception）
- 在 GET 请求 body 中传数据
- 任何接口允许 pageSize > 100
- 任何批量接口允许 ids.length > 50
- 修改 /api/admin/v1 前缀
- 创建 /api/v1（未带 admin 命名空间）的路径
```

## D. Redis 相关

```
[绝对禁止]
- 使用 admin: 之外的 key 前缀（不允许侵入 app: 命名空间）
- 修改 RedisService 的封装接口
- 直接用 redis.flushall / flushdb
- 用 KEYS pattern（生产环境会卡住）— 必须用 SCAN
- 缓存 TTL 不加抖动（除单次性 lock）
- 把密码 / token / session_key 写入 Redis 任何 key
- 直接读小程序端 app: 命名空间的 key
```

## E. 操作日志相关

```
[绝对禁止]
- 删除 operation_logs（audit_log）任何记录
- 修改 operation_logs 已写入的记录（追加补充字段除外）
- 跳过 Critical/Important 级别操作的同步写日志
- 在 detail 字段写入密码 / JWT / session_key
- detail 字段超过 10KB 不截断
```

## F. 模块相关

```
[绝对禁止]
- 创建跨模块循环依赖
- 在 Module A 直接 new Module B 的 Service（必须依赖注入）
- 在 Controller 层直接调用 Prisma（必须经 Service）
- 在 Controller 返回 Prisma 原始类型（必须映射 DTO）
- 跨 Phase 修改其他 Phase 已完成模块的 Public API
```

## G. 安全相关

```
[绝对禁止]
- 使用除 bcrypt 之外的密码哈希算法
- bcrypt rounds < 12
- 在 GET / URL 参数中传密码
- 在 console.log / logger.info 中打印 token / password
- 拼接原始 SQL 字符串
- 关闭 ValidationPipe / GlobalExceptionFilter
- 在 production 环境暴露 /debug / /__internal 路由
- 跳过 CORS 配置（必须显式 allowlist）
```

## H. 必须人工 Review 的模块（不允许自动合并）

以下文件/操作必须由项目维护者审核后才能合并：

```
[必须人工 Review]
1. src/modules/auth/**          — JWT 签发/验证/黑名单核心
2. src/modules/rbac/guards/**   — 权限/角色 Guards 实现
3. src/scripts/init-super-admin.ts — 超管初始化脚本
4. src/scripts/seed-*.ts        — 任何 seed 脚本
5. prisma/migrations/**         — 任何 DB migration
6. src/common/interceptors/audit-log.interceptor.ts — 日志拦截器
7. src/common/interceptors/response.interceptor.ts — 响应包装器
8. src/common/filters/*.filter.ts — 全局异常过滤器
9. 任何包含 "super_admin" 字符串的文件
10. 任何 batch- 开头的 API 实现
11. 任何涉及 transaction / $transaction 的 Service 方法
12. docker-compose.prod.yml / .env.production 相关
13. 任何 /admin-users/{id}/role 类的角色变更接口
14. 任何 /questions/{id}/approve 等审核操作
```

## I. 必须严格遵守的提问时机

DeepSeek 在以下情形必须**停止开发并提问**，不允许自行决定：

```
1. 文档之间出现矛盾（如 RBAC_RULES 与 PHASE_PLAN 不一致）
2. 需要新增任何文档未提及的 API
3. 需要新增任何字段（无论是新表还是已有表）
4. 实现某功能时发现技术方案有 2 种以上选择
5. 测试时发现某 Critical 操作日志写入失败
6. 发现某 Phase 已完成模块需要修改
7. 发现 Prisma schema 与实际 DB 不一致（schema drift）
8. 任何与 super_admin 相关的逻辑（无一例外都需要确认）
9. 任何与"安全降级"相关的逻辑（如 Redis 不可用时怎么办）
10. 性能问题（响应 > 1s）需要加索引或调整查询
```

---

# 审计结论

> 当前规划方案是**优秀的初稿**（B+），但作为长期生产环境项目，存在 6 个 Critical 隐患必须先改。
>
> 修复成本约 1 天，不修复代价约 5-10 天 + 数据迁移风险 + 合规风险。
>
> **强烈建议在 DeepSeek 启动 Phase 0 之前完成 C1-C6 的文档修正**。
>
> 修正完成后，本规划具备启动条件，可作为长期运营型产品的合格架构起点。

---

## 相关链接

- [[docs/admin/ADMIN_ARCHITECTURE.md|ADMIN_ARCHITECTURE]] — 管理端架构
- [[docs/admin/ADMIN_API_SPEC.md|ADMIN_API_SPEC]] — 管理 API 合约
- [[docs/admin/DB_SCHEMA_ADMIN.md|DB_SCHEMA_ADMIN]] — 管理端数据模型
- [[docs/admin/RBAC_RULES.md|RBAC_RULES]] — RBAC 与身份域
- [[docs/admin/AUDIT_LOG.md|AUDIT_LOG]] — 审计记录
