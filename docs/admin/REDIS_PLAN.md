# Redis 使用规划

> ✅ **2026-09-28 更新**：本规划中的键已全部落地（`admin:perm:*` 以按角色的
> `admin:perm:role:{roleId}` 形式实现，幂等先接入 batch-delete 与 imports 批量 approve/reject）。
> 键空间与失败语义的权威清单见 **[docs/architecture/REDIS_USAGE.md](../architecture/REDIS_USAGE.md) 3.4 节**。
>
> 版本：v2.1（FastAPI 方案确认版） | 状态：历史设计参考（运行时以实现清单为准） | 更新：2026-09-28
> 修订自审计报告 I4（TTL 抖动 + 防穿透锁）、I5（双维度限流）、I6（role-version）、I9（用户级 nbf）
>
> - **变更原因**：2026-05-29 同步 Admin Backend Phase 4 导入管理实现，补充 `admin:ai:batch:{batchId}:task` 最新任务指针，并将 AI enrich 任务 TTL 校正为当前代码使用的 86400 秒。

---

## 一、命名空间规则（严格隔离）

```
小程序端：app:user:{id}:*   /  app:question:*
Admin 端：admin:jwt:*       /  admin:perm:*  /  admin:role:*  /  admin:stats:*
```

**强制约束**：
- Admin 系统所有 key 以 `admin:` 开头
- **禁止**读 / 写小程序端 `app:` 命名空间
- 小程序端同样不读 / 写 `admin:` 命名空间
- Redis 可观测性脚本可跨命名空间，但仅用于运维

---

## 二、Key 设计总表

> 当前实现清单及失败语义以 **[docs/architecture/REDIS_USAGE.md](../architecture/REDIS_USAGE.md) 3.4 节**为准。
> 下表保留原设计目标；实现后的实际键名、有效期和失败语义请以
> `docs/architecture/REDIS_USAGE.md` 3.4 节为准，不要把历史伪代码当作运行时实现。

| 用途 | Key | Value | TTL |
|------|-----|-------|-----|
| JWT 黑名单 | `admin:jwt:blacklist:{jti}` | "1" | 至 token 过期 |
| 用户级强制失效 | `admin:user:nbf:{userId}` | unix_timestamp | 永久（覆盖式） |
| 用户权限缓存 | `admin:perm:user:{userId}` | `{ roleId, version, permissions }` | 15min ± 抖动 |
| 角色权限版本 | `admin:role:version:{roleId}` | uuid | 永久（覆盖式） |
| 登录失败（IP）| `admin:login:fail:ip:{ip}` | counter | 10min |
| 登录失败（账号）| `admin:login:fail:user:{username}` | counter | 30min |
| 在线状态 | `admin:online:{userId}` | `{ lastActiveAt, ip, userAgent }` | 5min |
| OCR 任务 | `admin:ocr:task:{taskId}` | `{ status, progress, result, error }` | 1h |
| AI 任务 | `admin:ai:task:{taskId}` | `{ task_id, batch_id, status, created_at, updated_at, total_count, processed_count, error_message }` | 86400s |
| AI 批次最新任务指针 | `admin:ai:batch:{batchId}:task` | taskId | 86400s |
| Dashboard 统计 | `admin:stats:overview:{date}` | JSON | 5min ± 抖动 |
| 防穿透锁 | `admin:stats:lock:{key}` | uuid | 10s |
| 接口限流 | `admin:ratelimit:{userId}:{endpoint}` | counter | 60s |
| 幂等请求 | `admin:idempotency:{userId}:{key}` | 指纹 + 执行中/已完成响应 | 执行中 1h、完成 10min |
| 全局豁免标识 | `admin:bypass:{sha256(token)}` | meta；经 `X-Admin-Bypass-Token` 请求头使用 | 默认 30d |

---

## 三、详细设计

### 3.1 JWT 黑名单（登出/强制失效）

```
Key:    admin:jwt:blacklist:{jti}
Value:  "1"
TTL:    剩余 token 有效期（精确）
```

**使用场景**：
- 管理员主动登出
- super_admin 强制踢出某 admin 单一会话
- 编辑敏感配置后立即吊销当前 token

**实现**：
```typescript
async blacklistToken(jti: string, exp: number) {
  const ttl = exp - Math.floor(Date.now() / 1000);
  if (ttl <= 0) return;
  await redis.set(`admin:jwt:blacklist:${jti}`, '1', 'EX', ttl);
}
```

### 3.2 用户级强制失效（I9 新增）

```
Key:    admin:user:nbf:{userId}
Value:  unix_timestamp（秒）
TTL:    永久（每次密码修改 / 强制下线时覆盖）
```

**使用场景**：
- 修改密码 → 所有签发于此前的 token 全部失效
- 怀疑账号被盗 → 一键吊销该用户全部会话
- 角色变更（敏感模式）

**实现**：
```typescript
async forceLogoutUser(userId: number) {
  await redis.set(`admin:user:nbf:${userId}`, Math.floor(Date.now() / 1000));
}

// JwtAuthGuard 校验
const nbfStr = await redis.get(`admin:user:nbf:${userId}`);
if (nbfStr && jwt.iat < parseInt(nbfStr)) {
  throw new UnauthorizedException('会话已强制失效，请重新登录');
}
```

### 3.3 用户权限缓存（I6 修订：含 role version）

```
Key:    admin:perm:user:{userId}
Value:  { roleId, version, permissions: string[] }
TTL:    900s ± 90s 抖动（避免雪崩）
```

**实现**：
```typescript
async getUserPermissions(userId: number): Promise<string[]> {
  const cacheKey = `admin:perm:user:${userId}`;
  const cached = await redis.get(cacheKey);

  if (cached) {
    const data = JSON.parse(cached);
    const currentVersion = await redis.get(`admin:role:version:${data.roleId}`);
    if (data.version === currentVersion) return data.permissions;
    // version 不匹配 → 失效
  }

  // 加载并缓存
  const user = await this.prisma.adminUser.findUnique({
    where: { id: userId },
    include: { role: { include: { permissions: { include: { permission: true } } } } },
  });
  const permissions = user.role.permissions.map(rp => rp.permission.name);
  const version = await this.ensureRoleVersion(user.roleId);
  
  const ttl = 900 + Math.floor(Math.random() * 90);  // ± 抖动
  await redis.set(cacheKey, JSON.stringify({ roleId: user.roleId, version, permissions }), 'EX', ttl);
  return permissions;
}
```

### 3.4 角色权限版本号

```
Key:    admin:role:version:{roleId}
Value:  uuid（每次角色权限变更时刷新）
TTL:    永久（覆盖式）
```

**实现**：
```typescript
async ensureRoleVersion(roleId: number): Promise<string> {
  const key = `admin:role:version:${roleId}`;
  let version = await redis.get(key);
  if (!version) {
    version = uuidv4();
    await redis.set(key, version);
  }
  return version;
}

async bumpRoleVersion(roleId: number) {
  await redis.set(`admin:role:version:${roleId}`, uuidv4());
}
```

**触发时机**：
- 角色权限绑定变更（add/remove permission）
- 角色被删除（version 设为特殊值 `_deleted_`）

### 3.5 登录失败限流（I5 修订：双维度）

```
Key1:  admin:login:fail:ip:{ip}        TTL=600   threshold=10
Key2:  admin:login:fail:user:{username} TTL=1800 threshold=5
```

**规则**：
- 任一维度达阈值即拒绝登录
- 用户名维度更严格（防针对性撞库）
- IP 维度兼顾防代理池与 NAT 共享出口
- 登录响应**统一返回**"用户名或密码错误"，不暴露锁定状态（防用户名枚举）
- 登录成功 → 清 `fail:user:{username}`（IP 计数保留以防扫号）

```typescript
async login(dto: LoginDto, ip: string) {
  const userKey = `admin:login:fail:user:${dto.username}`;
  const ipKey = `admin:login:fail:ip:${ip}`;

  const userFails = parseInt(await redis.get(userKey) || '0');
  const ipFails = parseInt(await redis.get(ipKey) || '0');
  if (userFails >= 5 || ipFails >= 10) {
    throw new UnauthorizedException('用户名或密码错误');
  }

  const user = await this.prisma.adminUser.findUnique({ where: { username: dto.username } });
  const ok = user?.isActive && await bcrypt.compare(dto.password, user.passwordHash);

  if (!ok) {
    await this.incFails(userKey, 1800);
    await this.incFails(ipKey, 600);
    throw new UnauthorizedException('用户名或密码错误');
  }

  await redis.del(userKey);
  return this.issueTokens(user);
}

private async incFails(key: string, ttl: number) {
  const count = await redis.incr(key);
  if (count === 1) await redis.expire(key, ttl);
}
```

### 3.6 在线状态

```
Key:    admin:online:{userId}
Value:  { lastActiveAt, ip, userAgent }
TTL:    300（每次请求自动续期）
```

**用途**：
- Dashboard 显示"当前在线管理员"
- 审计辅助信息

### 3.7 OCR / AI 任务状态

```
Key:    admin:ocr:task:{taskId}
Value:  { status: pending|processing|done|failed, progress, result, error }
TTL:    3600

Key:    admin:ai:task:{taskId}
Value:  { task_id, batch_id, status, created_at, updated_at, total_count, processed_count, error_message }
TTL:    86400

Key:    admin:ai:batch:{batchId}:task
Value:  taskId（该导入批次最新 AI enrich 任务）
TTL:    86400
```

**用途**：前端轮询任务进度。

**Phase 4 实现说明（2026-05-29）**：
- `/api/admin/v1/imports/{batchId}/enrich` 当前写入 `admin:ai:task:{taskId}`，并用 `admin:ai:batch:{batchId}:task` 保存批次到最新任务的指针。
- `/api/admin/v1/imports/{batchId}/status` 先读取批次指针，再读取任务 payload；任一 key 不存在时返回任务不存在。
- 当前 enrich 只创建 `pending` 状态与审计日志，不代表 AI worker 已实际处理完成；不得据此绕过 `question_imports + 人工确认`。

### 3.8 Dashboard 统计缓存（Phase 5 实现，2026-05-29）

```
Key:    admin:dashboard:overview
Value:  JSON
TTL:    300 ± 30 抖动

Key:    admin:dashboard:overview:lock
Value:  uuid
TTL:    10
```

**实现 stale-while-revalidate**：
```typescript
async getOverview() {
  const key = "admin:dashboard:overview";
  const cached = await cache.get(key);

  if (cached) return cached;

  const lockKey = `${key}:lock`;
  const lockValue = uuid4().hex;
  const locked = await cache.acquire_lock(lockKey, lockValue, ttl=10);
  if (!locked) {
    await sleep(100);
    const retry = await cache.get(key);
    if (retry) return retry;
    return await compute_dashboard_overview(db);
  }

  try {
    const data = await compute_dashboard_overview(db);
    await cache.set(key, data, ttl=cache.jitter_ttl(300, 0.1));
    return data;
  } finally {
    await cache.release_lock(lockKey, lockValue);
  }
}
```

**实现说明**：
- **更新时间**：2026-05-29
- **变更原因**：同步 Phase 5 FastAPI Dashboard 实现与实际 Redis/cache key。
- 当前 FastAPI 实现为请求触发缓存 + 防穿透锁，不依赖 BullMQ 主动刷新。
- Redis 不可用时 `cache` 静默降级，接口直接查 DB，不影响核心功能。
- `cache.get_stats()` 提供 `hits` / `misses` / `hit_rate` / `enabled`，由 Dashboard overview 返回。
- `release_lock` 当前通过读取锁值后删除实现，未使用 Lua 原子释放；生产如需严格锁释放语义需后续单独实现。

### 3.9 接口限流

```
Key:    admin:ratelimit:{userId}:{endpoint}
Value:  counter
TTL:    60s（滑动窗口）
```

**规则**：
- 普通接口：60 req/min
- 批量操作接口：10 req/min
- 统计接口：30 req/min
- super_admin：放宽 2x

### 3.10 幂等请求缓存（O4）

```
Key:    admin:idempotency:{userId}:{key}
Value:  { fingerprint, state: pending | complete, response? }
TTL:    执行中 3600s；已完成 600s
```

**规则**：
- 仅用于关键写操作（如 batch-approve / batch-reject）。
- 同一 userId + Idempotency-Key + 方法/路径/请求体重复请求在完成后返回相同结果；执行中返回 409，不同请求复用同键返回 409。
- Redis 不可用时，关键批量写 / 关键幂等写接口返回 503；如个别接口选择降级执行，必须在接口文档明确“不提供幂等保证”。

### 3.11 全局豁免名单（O9）

```
Key:    admin:bypass:{tokenHash}
Value:  { type: "monitor" | "internal", note }
TTL:    自定义
```

**用途**：内部监控系统、健康检查等不计入限流。

**强制约束**：
- bypass token 只能豁免接口限流，不能跳过 JWT 认证、RBAC 权限或 audit_log 写入。
- 仅允许观测类 allowlist（dashboard overview/daily 和 redis online）使用，不得对批量写等普通后台接口开放。
- 创建 / 删除 bypass token 属于 critical 操作，必须写 audit_log。

---

## 四、Redis 模块封装（NestJS）

```typescript
@Injectable()
export class RedisService {
  private client: Redis;
  private readonly logger = new Logger(RedisService.name);

  // 通用工具
  async get<T = unknown>(key: string): Promise<T | null>
  async set(key: string, value: unknown, ttlSeconds?: number): Promise<void>
  async del(...keys: string[]): Promise<number>
  async incr(key: string): Promise<number>
  async expire(key: string, ttl: number): Promise<void>

  // 抖动 TTL 工具
  jitter(base: number, percent = 0.1): number {
    const variance = base * percent;
    return base + Math.floor((Math.random() * 2 - 1) * variance);
  }

  // JWT
  async blacklistToken(jti: string, exp: number): Promise<void>
  async isTokenBlacklisted(jti: string): Promise<boolean>
  async setUserNbf(userId: number, timestamp: number): Promise<void>
  async getUserNbf(userId: number): Promise<number | null>

  // 权限缓存
  async getPermissionCache(userId: number): Promise<CachedPerm | null>
  async setPermissionCache(userId: number, data: CachedPerm): Promise<void>
  async clearPermissionCache(userId: number): Promise<void>
  async getRoleVersion(roleId: number): Promise<string>
  async bumpRoleVersion(roleId: number): Promise<void>

  // 登录限流
  async incrementLoginFail(username: string, ip: string): Promise<void>
  async checkLoginLocked(username: string, ip: string): Promise<boolean>
  async clearLoginFail(username: string): Promise<void>

  // 任务状态
  async setTaskStatus(type: 'ocr'|'ai', taskId: string, status: object): Promise<void>
  async getTaskStatus(type: 'ocr'|'ai', taskId: string): Promise<object | null>

  // 防穿透锁
  async tryLock(key: string, ttl?: number): Promise<string | null>  // 返回 lockId
  async releaseLock(key: string, lockId: string): Promise<void>

  // 限流
  async checkRateLimit(userId: number, endpoint: string, limit: number): Promise<boolean>
}
```

**降级策略**：
- Redis 连接失败 → 权限缓存改为每次查 DB；普通限流可跳过
- 关键批量写 / 关键幂等写依赖 `admin:idempotency:{userId}:{key}`，Redis 不可用时返回 503，避免重复提交造成不一致
- bypass token 不参与 JWT/RBAC 降级，Redis 不可用时视为无豁免
- **不影响**核心只读与非幂等依赖业务功能
- 连续 30s 失败 → 触发告警（log + Sentry）

---

## 五、与小程序端 Redis 的关系

小程序端当前使用：
```python
# backend/app/core/cache_client.py
await cache.set(key, value, ttl)
await cache.get(key)
await cache.delete(pattern)
```

Admin 端与之**完全独立**：
- 共享同一 Redis 实例（节省运维成本）
- 命名空间严格隔离（不互相读写）
- 任一方挂掉，另一方不受影响（连接独立）

---

## 六、运维与可观测性

- Dashboard 统计页展示 Redis 连接状态、命中率、内存使用
- 使用 `redis.info('stats')` 获取 `keyspace_hits` / `keyspace_misses`
- RedisService 每个方法记录耗时（>100ms 打 warning，>500ms 打 error）
- 监控 BullMQ 队列长度（audit-log queue 积压超 1000 条触发告警）
- 定期 SCAN 扫描 admin: 命名空间，统计 key 数量与内存占用
- **禁止**生产环境使用 `KEYS pattern` 命令（必须用 SCAN）

---

## 七、不变式（Invariants）

1. 任何 admin: 命名空间外的 key 一律不可读写
2. 所有 TTL 缓存必须加 ±10% 抖动（除单次性 lock）
3. 任何"通过 SCAN 枚举所有用户清缓存"的实现都是错误的（应用 role-version 机制）
4. JWT Payload 中绝不包含 permissions 数组
5. 登录响应不暴露锁定状态（防用户名枚举）
6. 防穿透锁释放必须用 Lua 校验 lockId 原子性（防止误释放他人锁）
7. bypass token 只豁免限流，绝不豁免 JWT/RBAC/audit_log
8. 关键批量写 / 关键幂等写在 Redis 不可用时必须 503 或明确声明无幂等保证

---

## 相关链接

- [[docs/admin/ADMIN_ARCHITECTURE.md|ADMIN_ARCHITECTURE]] — 管理端架构
- [[docs/admin/ADMIN_API_SPEC.md|ADMIN_API_SPEC]] — 管理 API 合约
- [[docs/admin/DB_SCHEMA_ADMIN.md|DB_SCHEMA_ADMIN]] — 管理端数据模型
- [[docs/admin/RBAC_RULES.md|RBAC_RULES]] — RBAC 与身份域
- [[docs/admin/AUDIT_LOG.md|AUDIT_LOG]] — 审计记录
