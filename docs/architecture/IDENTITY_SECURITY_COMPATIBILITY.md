# Identity, auth and RBAC compatibility baseline

Reviewed: 2026-10-24, phase 0. This baseline covers the shared token boundaries and dependency contracts below. It is not a claim that every Admin page, WeChat login flow, Redis outage, production browser session, or external provider has been verified.

## 1. Identity domains

| Boundary | Authoritative implementation | Contract |
| --- | --- | --- |
| User access JWT | `backend/app/core/security.py` | `type=user_access`, user audience, user-scoped HMAC key, `sub/iat` integer checks, account-wide `user:jwt:nbf:{id}` denial. |
| Admin access JWT | `backend/app/core/admin_security.py` | `type=admin`, admin audience, admin-scoped HMAC key, `roleId`, per-`jti` blacklist and account-wide `admin:user:nbf:{id}` denial. |
| Admin refresh JWT | Same admin module | `type=admin_refresh`, HttpOnly cookie scoped to `/api/admin/v1/auth`, one-time `admin:refresh:used:{jti}` consumption. |
| User opaque refresh token | `backend/app/services/token_service.py` | Stored hash, account-state check, one-shot rotation and revocation. |
| App user with admin grant | `security.require_app_permission` | Requires the App user binding to an active Admin role; only local-import `dev_` users may bypass RBAC. |

The two JWT families use different token types, audiences and derived keys. User access, admin access and admin refresh tokens are rejected by the other decoders. This is a compatibility boundary: moving an endpoint between Public and Admin prefixes must not reuse the other dependency.

## 2. Auth state and failure behavior

- User and Admin authentication check strict cache state (`nbf`, blacklist and refresh consumption) before DB identity. `CacheUnavailableError` becomes HTTP 503; it never degrades to an unauthenticated bypass.
- User access rejects deleted and banned accounts. Admin access additionally requires `AdminUser.is_active`. User refresh checks deletion/ban before rotating; Admin refresh re-loads the active admin and atomically claims its `jti`.
- Logout paths retain their existing semantics: users revoke all opaque refresh tokens and set account-wide JWT `nbf`; Admin logout blacklists the current access token, blacklists a supplied refresh token when decodable, and deletes the matching cookie.
- Admin login enforces trusted browser origin, IP+username and account-level failure counters/locks. Correct credentials can clear an account lock; Redis/auth state failures fail closed.
- Admin refresh cookies are HttpOnly, path-scoped, and Secure/SameSite=None on HTTPS or production; deletion uses matching attributes. Password policy and bcrypt's 72-byte bound remain unchanged.

## 3. Route registration and authorization matrix

- Public routes are aggregated by `backend/app/api/v1/router.py`; Admin routes by `backend/app/api/admin/router.py`; both are mounted without an outer prefix. Every Admin path is therefore defined with `/api/admin/v1/...` by its feature router and checked by `test_api_router_integrity.py`.
- `get_current_admin` + `require_permissions` is the normal Admin authorization dependency; `require_roles` is retained for deliberate super-admin and legacy exam publish role gates. App-user admin capabilities use `require_app_permission`, never an Admin JWT dependency.
- `GET/DELETE /api/v1/cache/*` and `POST /api/v1/sync/import` are historical path-prefix exceptions: they are mounted under Public registration but execute with Admin principal and RBAC (`cache:*` or `sync:write`). They must not be cited as evidence that Public user JWTs can clear cache or import question sync packages.
- Current route scan found no other Public feature router importing `admin_security`; Admin role and permission gates are concentrated in `/api/admin/v1`, the two historical exceptions above, and Public app-user admin capabilities.

## 4. Redis-dependent auxiliary behavior

Role permissions use role-versioned cache entries (`admin:role:version:{roleId}` and `admin:perm:role:{roleId}`). Version misses/unavailability fall back to DB. Role mutation bumps the version only as recorded by the existing Admin Redis regressions; observability, rate limiting and idempotency do not bypass JWT or RBAC.

Admin online presence is best-effort after authentication. Rate limit, bypass token and idempotency details remain owned by `REDIS_USAGE.md` and `admin_guards.py`; this baseline does not claim a real Redis outage/recovery test.

## 5. Admin browser client boundary

The Admin client keeps the access token in `sessionStorage`, restores it before bootstrap, validates it through `/auth/me`, and rotates the HttpOnly refresh cookie only when that token is absent/expired. Concurrent 401s share one refresh; refresh itself is never retried; explicit token changes and expiry clear both store and state.

The browser must still send cookies under the same Admin API origin and trusted browser origin policy. This static/unit boundary is not production browser acceptance.

## 6. Evidence and remaining gaps

Regression matrix:

```bash
cd backend
APP_ENV=test APP_SECRET=ci-refactor-test-secret-not-production \
DATABASE_URL=sqlite+aiosqlite:///:memory: \
.venv/bin/python -m pytest \
  tests/test_api/test_identity_boundary_matrix.py \
  tests/test_api/test_api_router_integrity.py \
  tests/test_api/test_admin_auth.py \
  tests/core/test_security_regressions.py \
  tests/test_services/test_dev_permissions.py \
  -q --tb=short
```

Result on 2026-10-24: 42 passed, including router integrity. New `test_identity_boundary_matrix.py` covers cross-domain token rejection, strict-cache fail-closed behavior, partial permission denial, and the `/api/v1/cache` historical-prefix gate.

Still unverified/unfinished:

- No real WeChat `jscode2session`, real-device login, production Admin browser login/role exit, external OCR/AI, Redis outage, multi-worker auth replay, or backup restore exercise in this baseline.
- This is not a recommendation to move `/api/v1/cache` or `/api/v1/sync` in this refactor. Any URL compatibility migration is a separate API/versioning decision.
- `re_pending` re-review workspace/rollback and `practice_service.use_leitner` TODO(V3) remain explicit non-goals of this baseline.
