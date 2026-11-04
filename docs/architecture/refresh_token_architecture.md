# Refresh Token 系统架构

> 解决三个长期问题：依赖 wx.login() 续签、无服务端吊销能力、python-jose 停止维护

---

## 问题定义

### 问题 1：每次续签都依赖微信 API

当前每次 token 续签（含主动续签）都调用 `wx.login()` → 后端调 `jscode2session`。
微信 API 不可用时续签失败，用户被登出。

### 问题 2：无服务端吊销能力

30 天 JWT 是无状态的，无法单独吊销某用户的 token。
如果用户设备丢失或被封禁，最长 30 天内 token 仍有效。

### 问题 3：`python-jose` 包停止维护

jose 库最后更新于 2021 年，存在潜在安全风险。需迁移到活跃维护的 PyJWT。

---

## 设计决策

### 决策 1：JWT 保持 30 天，不缩短

与审计建议相反，决定保持 30 天 JWT 不变。理由：
- 30 天 JWT 是天然缓存 —— 即使 DB / 刷新端点临时故障，现有 JWT 仍正常工作
- `一次登录、长期使用` 目标不倒退
- Refresh token 的作用不是缩短 JWT 寿命，而是：
  1. **提供吊销能力**（主要目的）
  2. 避免 wx.login() 的微信 API 外部依赖（次要目的）

### 决策 2：Opaque refresh token，DB 存储，90 天有效

- 明文 64 hex chars (`secrets.token_hex(32)`, 256-bit 熵)
- 服务端只存 SHA-256 哈希（即使 DB 泄露也无法还原）
- 每次 refresh 做旋转（吊销旧 token + 签发新 token）
- 回退：refresh token 无效/过期 → 降级到 wx.login() 全量重认证

### 决策 3：吊销依赖 refresh token，放弃 `token_valid_from`

审计指出 `token_valid_from` 需要 `iat` 声明且部署顺序复杂（需 30 天过渡期）。
简化方案：吊销 refresh token 即可达到"用户下次续签时必须重新认证"的效果。
不足：现有 JWT 在剩余有效期内仍可用。对于考研刷题场景，30 天的最大窗口可接受。

### 决策 4：迁移 `python-jose` → `PyJWT 2.x`

API 基本兼容，需注意：
- `jwt.encode()` 在 pyjwt 2.8.0 返回 `str`，无需 `.decode()`
- 异常基类为 `PyJWTError` 而非 `JWTError`
- `cryptography` 依赖不可移除（passlib bcrypt 使用）

---

## 数据模型

```python
class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```

索引：`user_id`（按用户查找）+ `token_hash`（按令牌查找）+ `expires_at`（清理过期令牌）。

---

## API 设计

### `POST /api/v1/auth/login`（改造）

请求不变。响应新增 `refresh_token` 字段：

```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "expires_at": 1800000000,
  "refresh_token": "a1b2c3d4...64hex",
  "user": { "id": 1, "nickname": "test", ... }
}
```

### `POST /api/v1/auth/refresh`（新增）

请求：
```json
{
  "refresh_token": "a1b2c3d4..."
}
```

响应：`access_token`（新）+ `expires_at`（新）+ `refresh_token`（旋转后的新令牌）+ `user`。

### `POST /api/v1/auth/login` 内部逻辑

1. `wx.login()` → `jscode2session`（如常）
2. 创建/查找用户（如常）
3. 签发 JWT（如常，30 天）
4. **新增**：调用 `token_service.create_refresh_token(db, user.id)` → 插入 RefreshToken 行
5. 返回 `(access_token, expires_at, refresh_token_raw, user)`

### `POST /api/v1/auth/refresh` 内部逻辑

1. `token_hash = sha256(request.refresh_token)`
2. 查 `refresh_tokens WHERE token_hash = ?`
3. 校验：未过期、未吊销
4. **旋转**：先 INSERT 新 RefreshToken，再 UPDATE 旧行设 `revoked_at=now()`
   - INSERT → UPDATE 顺序：即使第二步失败，旧 token 仍有效
5. 签发新 JWT（`create_token(user_id)`）
6. 返回 `(access_token, expires_at, new_refresh_token_raw)`

### **60 秒宽限期**

在 `POST /auth/refresh` 中，如果 token_hash 匹配的行 `revoked_at IS NOT NULL`
但 `revoked_at > now() - 60s`，视为有效。
解决两个客户端同时使用同一 refresh token 导致的竞争条件。

---

## 小程序端改造

### storage.js

```javascript
const KEYS = {
  TOKEN: 'token',
  USER: 'user',
  TOKEN_EXPIRES_AT: 'token_expires_at',
  REFRESH_TOKEN: 'refresh_token',  // new
}
```

### api.js `_refreshToken()`

改为两级策略：

```javascript
async function _refreshToken() {
  // 1st try: use refresh token
  const refreshToken = storage.get(KEYS.REFRESH_TOKEN)
  if (refreshToken) {
    const header = { 'Content-Type': 'application/json' }
    const res = await _rawRequest('POST', '/auth/refresh', { refresh_token: refreshToken }, header)
    if (res.statusCode === 200 && res.data && res.data.access_token) {
      storage.set(KEYS.TOKEN, res.data.access_token)
      storage.set(KEYS.TOKEN_EXPIRES_AT, res.data.expires_at)
      storage.set(KEYS.REFRESH_TOKEN, res.data.refresh_token)  // rotated
      if (res.data.user) {
        storage.set(KEYS.USER, res.data.user)
      }
      return res.data.access_token
    }
    // Refresh token invalid → clear it, fall through to wx.login
    storage.remove(KEYS.REFRESH_TOKEN)
  }

  // Fallback: full re-auth via wx.login
  const code = await _wxLogin()
  const header = { 'Content-Type': 'application/json' }
  const res = await _rawRequest('POST', '/auth/login', { code }, header)
  if (res.statusCode !== 200 || !res.data || !res.data.access_token) {
    throw new Error('刷新 token 失败')
  }
  storage.set(KEYS.TOKEN, res.data.access_token)
  storage.set(KEYS.TOKEN_EXPIRES_AT, res.data.expires_at)
  storage.set(KEYS.REFRESH_TOKEN, res.data.refresh_token)  // save new RT
  if (res.data.user) {
    storage.set(KEYS.USER, res.data.user)
  }
  return res.data.access_token
}
```

### auth.js

- `wechatLogin()`: 存储 `data.refresh_token` 到 storage
- `loginDirect(token, user, expiresAt, refreshToken)`: 新增第四参数存储 refresh_token
- `logout()`: 清除 `REFRESH_TOKEN`

---

## 实施阶段

### Phase 1：JWT 库迁移

**改动文件：**

| 文件 | 改动 |
|------|------|
| `requirements.txt` | `python-jose[cryptography]==3.3.0` → `pyjwt==2.8.0` |
| `core/security.py` | import + 异常类 |
| `core/admin_security.py` | import + 异常类 |

**验证：** 后端启动 + 登录流程通过。功能完全不变。

---

### Phase 2：Refresh Token 全链路

**改动文件（后端）：**

| 文件 | 改动 |
|------|------|
| `models/refresh_token.py` | **新文件** — RefreshToken 模型 |
| Alembic migration | 建 `refresh_tokens` 表 |
| `alembic/env.py` | 导入 RefreshToken |
| `services/token_service.py` | **新文件** — 生成/验证/吊销/旋转 |
| `schemas/user.py` | `TokenResponse` 加 `refresh_token`，新增 `RefreshRequest` |
| `api/v1/auth.py` | 改造 `POST /auth/login` + 新增 `POST /auth/refresh` |

**改动文件（小程序）：**

| 文件 | 改动 |
|------|------|
| `utils/storage.js` | `KEYS.REFRESH_TOKEN` |
| `utils/api.js` | `_refreshToken()` 两级策略，401 处理清 RT |
| `utils/auth.js` | `wechatLogin()`/`logout()`/`loginDirect()` 管理 RT |
| `pages/login/login.js` | dev 登录传入 `data.refresh_token` |

---

## 回归检查项

1. **首次登录**：JWT + refresh_token 均返回，用户正常进首页
2. **正常使用**：30 天内 JWT 有效，不触发 refresh，行为不变
3. **29 天后主动续签**：`ensureValidToken` 触发 → 用 refresh token 换新 JWT → 不走 wx.login()
4. **Refresh token 过期（90 天不打开）**：`/auth/refresh` 401 → 降级 wx.login() → 用户无感
5. **并发 401**：`_refreshing` 锁 + 服务端 60s 宽限期 → 仅一次实际 refresh
6. **管理员吊销**：设 `revoked_at` → 用户下次续签 fallback 到 wx.login()
7. **开发模式**：`_dev_openid` 流程不变，refresh token 跟随正常流程
8. **wx.login() 失败**：两级都失败 → 保持现有行为（弹错误、留在登录页）

---

## 相关链接

- [[docs/architecture/SYSTEM_ARCHITECTURE.md|SYSTEM_ARCHITECTURE]] — 系统架构
- [[docs/architecture/PRODUCTION_ARCH.md|PRODUCTION_ARCH]] — 生产架构
- [[docs/architecture/API_ROUTER_STRUCTURE.md|API_ROUTER_STRUCTURE]] — 路由结构
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/architecture/IDENTITY_SECURITY_COMPATIBILITY.md|IDENTITY_SECURITY_COMPATIBILITY]] — 身份与安全兼容
