# RBAC 权限系统设计规范

> 版本：v2.1（FastAPI 方案确认版） | 状态：可启动开发 | 更新：2026-05-29
> 修订自审计报告 C1（移除 normal_user）、C3（super_admin 走 role_permissions）、C4（删除方案 B）、I5（双维度限流）、I6（role-version）、I9（用户级 nbf）
>
> - **变更原因**：2026-05-29 同步 Admin Backend 已并入 FastAPI 的实际权限依赖方式；Phase 4 科目树与导入管理继续使用 `subject:*`、`import:*` 权限。

---

## 一、角色定义

| 角色 | 标识 | 描述 |
|------|------|------|
| 超级管理员 | `super_admin` | 拥有所有权限（**通过 role_permissions 表绑定，非硬编码**），不可被删除或降权 |
| 普通管理员 | `admin` | 拥有题库管理、用户查看等运营权限 |

**重要说明（C1 修订）**：
- ❌ 旧设计中的 `normal_user` 角色**已移除**
- 小程序用户（AppUser）**不进入 RBAC 体系**，不持有任何 permission
- AppUser 与 AdminUser 是两个完全独立的身份系统，详见 [ADMIN_ARCHITECTURE.md](./ADMIN_ARCHITECTURE.md) §二

**扩展预留（后期按需启用）**：
- `reviewer`：专职审核员，只有审核权限
- `content_editor`：内容编辑，只能编辑题目不能审核
- `readonly_admin`：只读管理员，用于数据分析

若需要“编辑后必须复审”的职责分离，应启用 `content_editor` + `reviewer` 组合；默认 `admin` 是写入、审核、批量审核一体的运营角色，编辑题目时不会进入 `re_pending`。

扩展方式：仅需在 roles 表新增记录并绑定 permissions，**无需改动任何代码**。

---

## 二、权限清单

### 小程序用户管理（AppUser，非 RBAC 主体）
| 权限标识 | 说明 |
|---------|------|
| `app_user:read` | 查看小程序用户列表和详情 |
| `app_user:write` | 编辑运营备注/状态类字段（白名单待确认；默认不改 nickname/avatar_url 等微信来源资料） |
| `app_user:ban` | 封禁/解封小程序用户 |

### 后台管理员管理（AdminUser）
| 权限标识 | 说明 |
|---------|------|
| `admin_user:read` | 查看后台管理员列表 |
| `admin_user:write` | 创建/编辑后台管理员 |
| `admin_user:delete` | 删除后台管理员 |

### 题目管理
| 权限标识 | 说明 |
|---------|------|
| `question:read` | 查看题目列表和详情 |
| `question:write` | 创建和编辑题目（编辑后若无 review 权限则进 re_pending） |
| `question:delete` | 删除题目（软删） |
| `question:review` | 审核题目（通过 / 拒绝） |
| `question:batch_review` | 批量审核题目 |

### 科目管理
| 权限标识 | 说明 |
|---------|------|
| `subject:read` | 查看科目树 |
| `subject:write` | 创建和编辑科目 |
| `subject:delete` | 删除科目（无题目时） |

### 角色 / 权限管理
| 权限标识 | 说明 |
|---------|------|
| `role:read` | 查看角色列表 |
| `role:write` | 创建/编辑角色及其权限绑定 |
| `role:delete` | 删除非系统角色 |
| `permission:read` | 查看权限列表 |

### 导入管理
| 权限标识 | 说明 |
|---------|------|
| `import:read` | 查看导入批次列表 |
| `import:write` | 触发 AI 解析、管理导入任务 |

### 审计与统计
| 权限标识 | 说明 |
|---------|------|
| `audit:read` | 查看审计日志 |
| `dashboard:read` | 查看统计概览 |

---

## 三、角色 - 权限初始映射（C3 修订）

**关键变更**：`super_admin` **必须**通过 `role_permissions` 表绑定所有权限，**代码中不允许任何 `if (isSuperAdmin) return true` 特权分支**（除"角色变更保护"与"删除自身保护"两处）。

### Seed 脚本逻辑

```python
# backend/app/services/admin_auth_service.py / Alembic seed 逻辑（示意）
def seed_roles_and_permissions(session):
    permissions = load_all_permission_names()
    super_admin = upsert_role(name="super_admin", is_system=True)
    bind_all_permissions(super_admin, permissions)

    admin = upsert_role(name="admin", is_system=True)
    bind_permissions(admin, ADMIN_PERMISSIONS)
```

实现可随 FastAPI 初始化脚本调整，但不变式是：`super_admin` 必须通过 `role_permissions` 表绑定全部权限，不能靠代码硬编码放行。

### CI 强制校验

每次 `seed-permissions.ts` 添加新权限后，CI 必须执行：

```bash
npm run check:super-admin-coverage
# 校验 super_admin 是否拥有 permissions 表的全部权限
# 不通过则阻止合并
```

### admin 角色初始权限

```
admin = [
  app_user:read, app_user:write, app_user:ban,
  question:read, question:write, question:review, question:batch_review,
  subject:read, subject:write,
  import:read, import:write,
  audit:read,
  dashboard:read,
]
```

---

## 四、三层权限控制实现

### 4.1 接口级（FastAPI dependencies）

```python
@router.get("/subjects")
async def list_subjects(_=Depends(require_permissions("subject:read"))): ...

@router.post("/imports/{batch_id}/enrich")
async def create_import_enrich_task(
    current_admin=Depends(require_permissions("import:write")),
): ...
```

执行顺序：`get_current_admin → require_role（如需要）→ require_permissions → 业务逻辑`

**关键**：权限依赖内部统一检查用户通过 `role_permissions` 获得的权限集合，不应有 `if (isSuperAdmin) return true` 分支。super_admin 之所以拥有全部权限，是因为 seed 阶段在 role_permissions 表中显式绑定了全部权限。

**Phase 4 权限同步（2026-05-29）**：
- 科目树模块：`GET /subjects`、`GET /subjects/{id}` 使用 `subject:read`；`POST/PATCH /subjects` 使用 `subject:write`；`DELETE /subjects/{id}` 使用 `subject:delete`。
- 导入管理模块：`GET /imports`、`GET /imports/{batchId}`、`GET /imports/{batchId}/status` 使用 `import:read`；`POST /imports/{batchId}/enrich` 使用 `import:write`。

### 4.2 页面级（Next.js Middleware + Layout）

```typescript
// middleware.ts — 未登录跳转 /login
// (admin)/layout.tsx — 无对应权限跳转 /403

// withPermission HOC
export default withPermission('app_user:read')(AppUsersPage)
```

### 4.3 按钮级（React 组件）

```tsx
<PermissionGuard permission="app_user:ban">
  <Button>封禁用户</Button>
</PermissionGuard>

const { hasPermission } = usePermission()
if (hasPermission('question:delete')) { ... }
```

前端权限列表来源：登录后调用 `GET /auth/me` 获取，缓存到 Zustand。

---

## 五、Super Admin 初始化方案（C4 修订）

### 5.1 安全设计原则

- super_admin 不能通过任何 API 接口创建或自我提升
- 初始化只能通过**服务器端 CLI 脚本**或**DB 直写**完成
- 所有 super_admin 创建必须写入 audit_log（severity=critical）
- 密码**必须从 stdin 读取**，不允许通过 CLI 参数传入（防止落入 shell history）

### 5.2 本地开发环境初始化

```bash
cd admin-backend
npx ts-node src/scripts/init-super-admin.ts --username=admin
# 脚本提示：Enter password: (从 stdin 读取，不回显)
# 脚本提示：Confirm password:
# 写入 audit_log
```

脚本内部逻辑：
1. 检查 DB 中是否已存在 super_admin → 存在则**直接退出**（幂等保护，避免误初始化第二个）
2. 从 stdin 读取密码（隐藏输入）
3. bcrypt 哈希（rounds=12）
4. 创建 admin_user 记录（role_id = super_admin）
5. 写入 audit_log：`{ operatorId: null, action: 'system.init_super_admin', severity: 'critical', ip: '<bootstrap>' }`
6. 打印事务 ID 与 admin_user.id，便于审计

### 5.3 生产环境推荐方案

**方案 A（首选）：SSH + docker exec CLI**

```bash
# SSH 进入生产服务器
ssh production-server

# 通过 docker exec 执行（不暴露任何 HTTP endpoint）
docker exec -it admin-backend \
  npx ts-node src/scripts/init-super-admin.ts --username=<username>
# stdin 输入密码

# 该脚本本身不提供任何 HTTP endpoint
# 脚本会自动检测已存在则退出，幂等
```

**方案 B（已删除，原因见审计报告 C4）**：~~docker-compose 环境变量种子~~ ❌ 严重不安全，**禁止使用**。

**方案 C（备用）：直连 DB 手动写入**

```bash
# 1. 在本地生成密码 hash
npm run hash-password
# 输入密码 → 输出 bcrypt hash

# 2. 连接生产 DB
psql $PRODUCTION_DATABASE_URL

# 3. 手动 INSERT
BEGIN;
INSERT INTO admin_users (username, password_hash, display_name, role_id, is_active, created_at, updated_at)
VALUES (
  'superadmin',
  '$2b$12$...',
  '超级管理员',
  (SELECT id FROM roles WHERE name = 'super_admin'),
  TRUE,
  NOW(),
  NOW()
);

INSERT INTO audit_logs (operator_id, action, resource_type, severity, ip, created_at)
VALUES (LASTVAL(), 'system.manual_super_admin_init', 'system', 'critical', '<manual>', NOW());

COMMIT;
```

### 5.4 安全约束（代码层强制）

```typescript
// admin-users.service.ts

// 1. 任何 API 不得创建/变更为 super_admin
async createAdminUser(dto: CreateAdminUserDto, operator: AdminUser) {
  const role = await this.prisma.role.findUnique({ where: { id: dto.roleId } });
  if (role?.name === 'super_admin') {
    throw new ForbiddenException('super_admin 只能通过 init-super-admin.ts 脚本创建');
  }
  // ... 其他逻辑
}

// 2. 任何 API 不得删除/封禁/修改 super_admin（包括 super_admin 互删）
async deleteAdminUser(id: number, operator: AdminUser) {
  const target = await this.prisma.adminUser.findUnique({
    where: { id }, include: { role: true }
  });
  if (target?.role.name === 'super_admin') {
    throw new ForbiddenException('不可删除 super_admin 账号');
  }
  if (target?.id === operator.id) {
    throw new UnprocessableEntityException('不可删除自己');
  }
  // ...
}

// 3. 任何角色更新不得包含 super_admin
async updateAdminUserRole(id: number, newRoleId: number) {
  const newRole = await this.prisma.role.findUnique({ where: { id: newRoleId } });
  if (newRole?.name === 'super_admin') {
    throw new ForbiddenException('不可通过 API 将用户提升为 super_admin');
  }
  // ...
}
```

---

## 六、JWT 安全设计（C2 修订）

### 6.1 JWT Payload（最小集）

```typescript
{
  sub: number,         // adminUserId
  type: "admin",       // 严格区分小程序 JWT（type=app）
  roleId: number,      // 仅 ID，不放 name
  jti: string,         // UUID，用于黑名单
  iat: number,
  exp: number,
}
```

**严禁**在 Payload 中放：
- `permissions[]`（权限收回失效问题，详见审计报告 C2）
- `role.name`（角色重命名后失效）
- 任何敏感数据（password、email、session_key 等）

### 6.2 Token 生命周期

- Access Token：`2h`
- Refresh Token：`7d`（存储在 HttpOnly + Secure + SameSite=Strict Cookie）
- 登出：将 access token 的 jti 写入 `admin:jwt:blacklist:{jti}`（TTL = 剩余有效期）
- 密码修改：立即更新 `admin:user:nbf:{userId} = now()`，所有签发于此前的 token 失效

### 6.3 用户级强制失效（I9 新增）

```typescript
// 强制踢出某用户的所有会话
await redis.set(`admin:user:nbf:${userId}`, Date.now() / 1000);

// JwtAuthGuard 校验
const nbf = await redis.get(`admin:user:nbf:${userId}`);
if (nbf && jwt.iat < parseInt(nbf)) {
  throw new UnauthorizedException('会话已强制失效，请重新登录');
}
```

应用场景：
- 修改密码 / 重置密码
- 怀疑账号被盗
- 角色变更（敏感时启用）

### 6.4 登录失败限流（I5 修订：双维度）

```
admin:login:fail:ip:{ip}        TTL=10min, threshold=10
admin:login:fail:user:{username} TTL=30min, threshold=5
```

规则：
- 任一维度达到阈值即锁定
- 用户名锁定（30min）优先于 IP 锁定（10min），防止 NAT 出口同事相互锁定
- 登录响应**统一返回**"用户名或密码错误"（防用户名枚举）
- 登录成功清除 `fail:user:{username}`（保留 IP 计数以防撞库）

```typescript
async login(dto: LoginDto, ip: string) {
  const userKey = `admin:login:fail:user:${dto.username}`;
  const ipKey = `admin:login:fail:ip:${ip}`;

  if ((await redis.get(userKey) || 0) >= 5) {
    throw new UnauthorizedException('用户名或密码错误'); // 不暴露锁定
  }
  if ((await redis.get(ipKey) || 0) >= 10) {
    throw new UnauthorizedException('用户名或密码错误');
  }

  const user = await this.prisma.adminUser.findUnique({ where: { username: dto.username } });
  const ok = user && await bcrypt.compare(dto.password, user.passwordHash);

  if (!ok) {
    await redis.incr(userKey); await redis.expire(userKey, 1800);
    await redis.incr(ipKey);   await redis.expire(ipKey, 600);
    throw new UnauthorizedException('用户名或密码错误');
  }

  await redis.del(userKey);
  return this.issueTokens(user);
}
```

---

## 七、权限缓存一致性（I6 修订：role-version 机制）

### 7.1 设计

```
admin:role:version:{roleId}      → uuid（角色每次更新时刷新）
admin:perm:user:{userId}         → { version, permissions[] }，TTL=15min ± 抖动
```

### 7.2 校验流程

```typescript
async getUserPermissions(userId: number): Promise<string[]> {
  const cacheKey = `admin:perm:user:${userId}`;
  const cached = await redis.get(cacheKey); // { version, permissions }

  if (cached) {
    const currentVersion = await redis.get(`admin:role:version:${cached.roleId}`);
    if (cached.version === currentVersion) return cached.permissions;
    // version 不匹配 → 视为缓存失效
  }

  // Cache miss / 失效 → 查 DB
  const { roleId, permissions } = await this.loadFromDB(userId);
  const version = await this.ensureRoleVersion(roleId);
  await redis.set(cacheKey, JSON.stringify({ roleId, version, permissions }),
                  'EX', 900 + Math.floor(Math.random() * 90)); // 15min ± 抖动
  return permissions;
}
```

### 7.3 角色权限变更时

```typescript
async updateRolePermissions(roleId: number, permissionIds: number[]) {
  await this.prisma.$transaction([
    this.prisma.rolePermission.deleteMany({ where: { roleId } }),
    this.prisma.rolePermission.createMany({
      data: permissionIds.map(pid => ({ roleId, permissionId: pid }))
    }),
  ]);

  // 刷新 version → 所有持有该 role 的用户缓存自动失效
  await redis.set(`admin:role:version:${roleId}`, uuid());

  // 写 audit log（critical）
  await this.auditLog.write({
    action: 'role.update_permissions',
    severity: 'critical',
    resourceType: 'role',
    resourceId: roleId,
    detail: { before, after, extra: { affectedUsers: '<count>' } },
  });
}
```

**无需 SCAN，无需枚举所有用户。**

### 7.4 单个用户角色变更

```typescript
await redis.del(`admin:perm:user:${userId}`); // 立即清自己的缓存
// 可选：同时更新 nbf 强制踢出（敏感场景）
```

---

## 八、敏感操作二次验证（预留位）

以下操作未来需引入"重输密码"或"MFA"二次验证：

- 删除 super_admin（虽然代码已禁，但保留位）
- 批量操作 ≥ 50 条
- 修改角色权限绑定
- 导出全量数据

**当前 Phase 不实现**，但 API 设计需预留 `X-Confirm-Password` Header 位置，避免未来加时不兼容。
