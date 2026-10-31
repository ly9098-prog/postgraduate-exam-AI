from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException
from fastapi import Response as FastAPIResponse
from fastapi.testclient import TestClient

from app.api.v1 import admin_auth
from app.core.admin_security import (
    REFRESH_COOKIE_KEY,
    AdminPrincipal,
    PasswordPolicyError,
    create_admin_token,
    delete_refresh_cookie,
    hash_admin_password,
    set_refresh_cookie,
)
from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.admin import AdminUser, Role

client = TestClient(app)


class _FakeDb:
    def __init__(self):
        self.commit = AsyncMock()
        self.add = MagicMock()


async def _override_db():
    yield _FakeDb()


def _role():
    return Role(id=1, name="super_admin", display_name="超级管理员", is_system=True)


def _admin_user(password="old-password"):
    return AdminUser(
        id=1,
        username="admin",
        password_hash=hash_admin_password(password),
        display_name="Admin",
        email="admin@example.com",
        is_active=True,
        role_id=1,
    )


def test_admin_login_success(monkeypatch):
    user = _admin_user()
    role = _role()
    permissions = ["dashboard:read"]
    token = create_admin_token(user)
    refresh_token = "refresh-token"

    monkeypatch.setattr(admin_auth, "authenticate_admin", AsyncMock(return_value=user))
    monkeypatch.setattr(admin_auth, "build_admin_login_response", AsyncMock(return_value=(token, refresh_token, user, role, permissions)))
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.post("/api/admin/v1/auth/login", json={"username": "admin", "password": "old-password"})
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    data = resp.json()
    assert data["access_token"] == token
    assert data["token_type"] == "bearer"
    assert data["user"]["username"] == "admin"
    assert data["role"]["name"] == "super_admin"
    assert data["permissions"] == permissions
    assert resp.cookies.get("admin_refresh_token") == refresh_token
    assert user.last_login_at is not None
    assert user.last_login_ip == "testclient"


def test_admin_login_failure_returns_401(monkeypatch):
    monkeypatch.setattr(admin_auth, "authenticate_admin", AsyncMock(side_effect=ValueError("用户名或密码错误")))
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.post("/api/admin/v1/auth/login", json={"username": "admin", "password": "wrong-password"})
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 401
    error = resp.json()["error"]
    assert error["code"] == "HTTP_401"
    assert error["retryable"] is False
    assert "用户名或密码错误" not in str(resp.json())


def test_admin_me_rejects_app_token():
    from app.core.security import create_token

    token = create_token(1)

    resp = client.get("/api/admin/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 401


def test_admin_me_returns_current_admin(monkeypatch):
    user = _admin_user()
    role = _role()
    permissions = ["dashboard:read"]

    async def override_current_admin():
        return AdminPrincipal(user, {"jti": "token-id", "exp": 4102444800})

    monkeypatch.setattr(admin_auth, "get_admin_me_response", AsyncMock(return_value={"user": user, "role": role, "permissions": permissions}))
    app.dependency_overrides[admin_auth.get_current_admin] = override_current_admin
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.get("/api/admin/v1/auth/me")
    finally:
        app.dependency_overrides.pop(admin_auth.get_current_admin, None)
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    assert resp.json()["user"]["username"] == "admin"
    assert resp.json()["role"]["name"] == "super_admin"
    assert resp.json()["permissions"] == permissions


def test_admin_logout_blacklists_token(monkeypatch):
    user = _admin_user()
    payload = {"jti": "token-id", "exp": 4102444800}
    blacklist = AsyncMock()

    async def override_current_admin():
        return AdminPrincipal(user, payload)

    monkeypatch.setattr(admin_auth, "blacklist_admin_token", blacklist)
    app.dependency_overrides[admin_auth.get_current_admin] = override_current_admin
    try:
        resp = client.post("/api/admin/v1/auth/logout")
    finally:
        app.dependency_overrides.pop(admin_auth.get_current_admin, None)

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    blacklist.assert_awaited_once_with("token-id", 4102444800)


def test_admin_change_password_success(monkeypatch):
    user = _admin_user()
    change_password = AsyncMock()

    async def override_current_admin():
        return AdminPrincipal(user, {"jti": "token-id", "exp": 4102444800})

    monkeypatch.setattr(admin_auth, "change_admin_password", change_password)
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[admin_auth.get_current_admin] = override_current_admin
    try:
        resp = client.post(
            "/api/admin/v1/auth/change-password",
            json={"old_password": "old-password", "new_password": "new-password"},
        )
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(admin_auth.get_current_admin, None)

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    change_password.assert_awaited_once()


# ── Cookie helper tests ──


def test_set_refresh_cookie_uses_consistent_attributes(monkeypatch):
    """set_refresh_cookie always produces HttpOnly + correct SameSite + matching Secure per env."""
    monkeypatch.setattr(settings, "APP_ENV", "development")
    response = FastAPIResponse()

    set_refresh_cookie(response, "test-token-value")

    header = response.headers.get("set-cookie", "")
    assert "admin_refresh_token=test-token-value" in header
    assert "HttpOnly" in header
    assert "Path=/api/admin/v1/auth" in header
    assert "Max-Age=" in header
    # Explicitly run the development branch independent of the local .env
    assert "Secure" not in header or "Secure=false" in header
    # dev env → SameSite=lax
    assert "SameSite=lax" in header


def test_set_refresh_cookie_lax_for_http(monkeypatch):
    """SameSite=Lax when secure=False (local HTTP)."""
    monkeypatch.setattr(settings, "APP_ENV", "development")
    response = FastAPIResponse()
    request = MagicMock()
    request.url.scheme = "http"

    set_refresh_cookie(response, "test", request=request)
    header = response.headers.get("set-cookie", "")
    assert "Secure" not in header
    assert "SameSite=lax" in header


def test_set_refresh_cookie_none_for_https():
    """SameSite=None + Secure when request is HTTPS."""
    response = FastAPIResponse()
    request = MagicMock()
    request.url.scheme = "https"

    set_refresh_cookie(response, "test", request=request)
    header = response.headers.get("set-cookie", "")
    assert "Secure" in header
    assert "SameSite=none" in header


def test_set_refresh_cookie_x_forwarded_proto():
    """Secure=true when X-Forwarded-Proto: https is set (nginx proxy)."""
    response = FastAPIResponse()
    request = MagicMock()
    request.url.scheme = "http"  # backend sees HTTP from nginx proxy
    request.headers = {"x-forwarded-proto": "https"}

    set_refresh_cookie(response, "test", request=request)
    header = response.headers.get("set-cookie", "")
    assert "Secure" in header
    assert "SameSite=none" in header


def test_set_refresh_cookie_x_forwarded_proto_http(monkeypatch):
    """Secure=false when X-Forwarded-Proto is http."""
    monkeypatch.setattr(settings, "APP_ENV", "development")
    response = FastAPIResponse()
    request = MagicMock()
    request.url.scheme = "http"
    request.headers = {"x-forwarded-proto": "http"}

    set_refresh_cookie(response, "test", request=request)
    header = response.headers.get("set-cookie", "")
    assert "Secure" not in header
    assert "SameSite=lax" in header


def test_delete_refresh_cookie_matches_set_attributes():
    """delete_refresh_cookie sends matching HttpOnly / SameSite / Path."""
    response = FastAPIResponse()

    delete_refresh_cookie(response)

    header = response.headers.get("set-cookie", "")
    assert REFRESH_COOKIE_KEY in header
    assert "HttpOnly" in header
    assert "Path=/api/admin/v1/auth" in header
    assert "Max-Age=0" in header


def test_refresh_cookie_secure_in_production_env(monkeypatch):
    """When no request is given and APP_ENV=production, Secure=true."""
    monkeypatch.setattr(settings, "APP_ENV", "production")
    response = FastAPIResponse()

    set_refresh_cookie(response, "prod-token")

    header = response.headers.get("set-cookie", "")
    assert REFRESH_COOKIE_KEY in header
    assert "Secure" in header
    assert "HttpOnly" in header


def test_refresh_cookie_not_secure_in_development_env(monkeypatch):
    """When no request is given and APP_ENV=development, Secure=false."""
    monkeypatch.setattr(settings, "APP_ENV", "development")
    response = FastAPIResponse()

    set_refresh_cookie(response, "dev-token")

    header = response.headers.get("set-cookie", "")
    assert REFRESH_COOKIE_KEY in header
    assert "Secure" not in header or "Secure=false" in header
    assert "HttpOnly" in header


# ── Login sets refresh cookie ──


def test_admin_login_sets_refresh_cookie(monkeypatch):
    """Login response includes properly configured refresh cookie."""
    user = _admin_user()
    role = _role()
    permissions = ["dashboard:read"]
    token = create_admin_token(user)
    refresh_token = "test-refresh-token"

    monkeypatch.setattr(admin_auth, "authenticate_admin", AsyncMock(return_value=user))
    monkeypatch.setattr(admin_auth, "build_admin_login_response", AsyncMock(return_value=(token, refresh_token, user, role, permissions)))
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.post("/api/admin/v1/auth/login", json={"username": "admin", "password": "old-password"})
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    cookie_header = resp.headers.get("set-cookie", "")
    assert "admin_refresh_token=test-refresh-token" in cookie_header
    assert "HttpOnly" in cookie_header
    assert "Path=/api/admin/v1/auth" in cookie_header


# ── Refresh sets cookie ──


def test_admin_refresh_returns_token(monkeypatch):
    """Refresh endpoint reads cookie and returns new access token + re-sets cookie."""
    user = _admin_user()
    role = _role()
    permissions = ["dashboard:read"]
    token = create_admin_token(user)

    monkeypatch.setattr(admin_auth, "consume_admin_refresh_token", AsyncMock(return_value=user))
    monkeypatch.setattr(admin_auth, "build_admin_login_response", AsyncMock(return_value=(token, "new-refresh-token", user, role, permissions)))
    monkeypatch.setattr(admin_auth, "decode_admin_refresh_token", MagicMock(return_value={"sub": "1", "type": "admin_refresh"}))

    app.dependency_overrides[get_db] = _override_db
    try:
        refresh_client = TestClient(app)
        refresh_client.cookies.set(
            REFRESH_COOKIE_KEY, "valid-refresh-token", path="/api/admin/v1/auth"
        )
        resp = refresh_client.post("/api/admin/v1/auth/refresh")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    data = resp.json()
    assert data["access_token"] == token
    # Response should also set a refresh cookie
    cookie_header = resp.headers.get("set-cookie", "")
    assert REFRESH_COOKIE_KEY in cookie_header
    assert "HttpOnly" in cookie_header
    assert "Path=/api/admin/v1/auth" in cookie_header


def test_admin_refresh_missing_cookie_returns_401():
    """Refresh without cookie returns 401."""
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.post("/api/admin/v1/auth/refresh")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 401


def test_admin_refresh_invalid_token_returns_401(monkeypatch):
    """Refresh with invalid/expired token returns 401."""
    monkeypatch.setattr(admin_auth, "decode_admin_refresh_token", MagicMock(side_effect=HTTPException(status_code=401, detail="Invalid or expired token")))

    app.dependency_overrides[get_db] = _override_db
    try:
        refresh_client = TestClient(app)
        refresh_client.cookies.set(
            REFRESH_COOKIE_KEY, "garbage-token", path="/api/admin/v1/auth"
        )
        resp = refresh_client.post("/api/admin/v1/auth/refresh")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 401


# ── Logout deletes cookie ──


def test_admin_logout_deletes_refresh_cookie(monkeypatch):
    """Logout response sends cookie deletion with matching path."""
    user = _admin_user()
    payload = {"jti": "token-id", "exp": 4102444800}
    blacklist = AsyncMock()

    async def override_current_admin():
        return AdminPrincipal(user, payload)

    monkeypatch.setattr(admin_auth, "blacklist_admin_token", blacklist)
    app.dependency_overrides[admin_auth.get_current_admin] = override_current_admin
    try:
        resp = client.post("/api/admin/v1/auth/logout")
    finally:
        app.dependency_overrides.pop(admin_auth.get_current_admin, None)

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    blacklist.assert_awaited_once_with("token-id", 4102444800)

    cookie_header = resp.headers.get("set-cookie", "")
    assert REFRESH_COOKIE_KEY in cookie_header
    assert "Max-Age=0" in cookie_header
    assert "Path=/api/admin/v1/auth" in cookie_header


# ── Bootstrap simulation: refresh after losing in-memory token ──


def test_admin_bootstrap_refresh_after_token_loss(monkeypatch):
    """Simulate page refresh: lost in-memory token, refresh via cookie recovers session."""
    user = _admin_user()
    role = _role()
    permissions = ["dashboard:read"]
    token = create_admin_token(user)

    monkeypatch.setattr(admin_auth, "consume_admin_refresh_token", AsyncMock(return_value=user))
    monkeypatch.setattr(admin_auth, "build_admin_login_response", AsyncMock(return_value=(token, "new-refresh-token", user, role, permissions)))
    monkeypatch.setattr(admin_auth, "decode_admin_refresh_token", MagicMock(return_value={"sub": "1", "type": "admin_refresh"}))

    app.dependency_overrides[get_db] = _override_db
    try:
        # No Authorization header (simulates lost in-memory token).
        # Only the refresh cookie is present.
        refresh_client = TestClient(app)
        refresh_client.cookies.set(
            REFRESH_COOKIE_KEY, "valid-refresh-token", path="/api/admin/v1/auth"
        )
        resp = refresh_client.post("/api/admin/v1/auth/refresh")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    data = resp.json()
    assert data["access_token"] == token
    assert data["role"]["name"] == "super_admin"


# ── 账号级登录锁定 ──


def _ip_rate_key(username: str = "admin") -> str:
    import hashlib

    identity = f"testclient|{username.strip().lower()}"
    return "admin:login:fail:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


def test_login_consecutive_failures_set_account_lock(monkeypatch):
    """Repeated failures on the same account set the temporary lock flag."""
    import asyncio

    from app.core.cache import cache

    monkeypatch.setattr(admin_auth, "authenticate_admin", AsyncMock(side_effect=ValueError("用户名或密码错误")))
    app.dependency_overrides[get_db] = _override_db
    asyncio.run(cache.delete_strict(_ip_rate_key("admin")))
    try:
        for _ in range(settings.ADMIN_LOGIN_MAX_FAILURES):
            client.post("/api/admin/v1/auth/login", json={"username": "admin", "password": "x"})
    finally:
        app.dependency_overrides.pop(get_db, None)

    locked = asyncio.run(cache.get_strict("admin:login:account_lock:admin"))
    asyncio.run(cache.delete_strict("admin:login:account_fail:admin"))
    asyncio.run(cache.delete_strict("admin:login:account_lock:admin"))
    asyncio.run(cache.delete_strict(_ip_rate_key("admin")))
    assert locked is not None


def test_login_blocked_when_account_locked(monkeypatch):
    """Locked accounts are rejected before any credential comparison."""
    import asyncio

    from app.core.cache import cache

    authenticate = AsyncMock(side_effect=ValueError("用户名或密码错误"))
    monkeypatch.setattr(admin_auth, "authenticate_admin", authenticate)
    app.dependency_overrides[get_db] = _override_db
    asyncio.run(cache.set_strict("admin:login:account_lock:admin", 1, ttl=900))
    try:
        resp = client.post("/api/admin/v1/auth/login", json={"username": "admin", "password": "x"})
    finally:
        asyncio.run(cache.delete_strict("admin:login:account_lock:admin"))
        asyncio.run(cache.delete_strict("admin:login:account_fail:admin"))
        asyncio.run(cache.delete_strict(_ip_rate_key("admin")))
        app.dependency_overrides.pop(get_db, None)

    authenticate.assert_not_awaited()
    assert resp.status_code == 429
    error = resp.json()["error"]
    assert error["code"] == "HTTP_429"
    assert error["retryable"] is True
    assert "临时锁定" not in str(resp.json())


def test_login_locked_account_rejects_even_with_correct_password(monkeypatch):
    """The lock throttles guessing: no verification, even for a valid credential."""
    import asyncio

    from app.core.cache import cache

    authenticate = AsyncMock(return_value=object())
    monkeypatch.setattr(admin_auth, "authenticate_admin", authenticate)
    app.dependency_overrides[get_db] = _override_db
    asyncio.run(cache.set_strict("admin:login:account_lock:admin", 1, ttl=900))
    try:
        resp = client.post("/api/admin/v1/auth/login", json={"username": "admin", "password": "right"})
    finally:
        asyncio.run(cache.delete_strict("admin:login:account_lock:admin"))
        asyncio.run(cache.delete_strict("admin:login:account_fail:admin"))
        asyncio.run(cache.delete_strict(_ip_rate_key("admin")))
        app.dependency_overrides.pop(get_db, None)

    authenticate.assert_not_awaited()
    assert resp.status_code == 429


# ── 密码策略 ──


def test_change_password_weak_password_returns_400(monkeypatch):
    """PasswordPolicyError from the service is surfaced as 400, not 401."""

    async def override_current_admin():
        return AdminPrincipal(_admin_user(), {"jti": "token-id", "exp": 4102444800})

    async def _weak(*args, **kwargs):
        raise PasswordPolicyError("密码需包含大写字母")

    monkeypatch.setattr(admin_auth, "change_admin_password", _weak)
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[admin_auth.get_current_admin] = override_current_admin
    try:
        resp = client.post(
            "/api/admin/v1/auth/change-password",
            json={"old_password": "old-password", "new_password": "lowercasepassword12"},
        )
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(admin_auth.get_current_admin, None)

    assert resp.status_code == 400
    error = resp.json()["error"]
    assert error["code"] == "HTTP_400"
    assert error["retryable"] is False
    assert "大写" not in str(resp.json())


