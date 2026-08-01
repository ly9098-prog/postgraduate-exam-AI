import json
import time
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException
from fastapi import Response as FastAPIResponse
from fastapi.testclient import TestClient

from app.api.v1 import admin_auth
from app.core.admin_security import (
    REFRESH_COOKIE_KEY,
    AdminPrincipal,
    create_admin_2fa_pending_token,
    create_admin_token,
    delete_refresh_cookie,
    hash_admin_password,
    set_refresh_cookie,
)
from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.admin import AdminUser, Role
from app.services.totp_service import (
    _totp_at,
    generate_backup_codes,
    generate_totp_secret,
    hash_backup_code,
)

client = TestClient(app)


class _FakeDb:
    def __init__(self):
        self.commit = AsyncMock()


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
    assert resp.json()["detail"] == "用户名或密码错误"


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


def test_set_refresh_cookie_uses_consistent_attributes():
    """set_refresh_cookie always produces HttpOnly + correct SameSite + matching Secure per env."""
    response = FastAPIResponse()

    set_refresh_cookie(response, "test-token-value")

    header = response.headers.get("set-cookie", "")
    assert "admin_refresh_token=test-token-value" in header
    assert "HttpOnly" in header
    assert "Path=/api/admin/v1/auth" in header
    assert "Max-Age=" in header
    # No request passed → defaults to production=False for dev
    assert "Secure" not in header or "Secure=false" in header
    # dev env → SameSite=lax
    assert "SameSite=lax" in header


def test_set_refresh_cookie_lax_for_http():
    """SameSite=Lax when secure=False (local HTTP)."""
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


def test_set_refresh_cookie_x_forwarded_proto_http():
    """Secure=false when X-Forwarded-Proto is http."""
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


def test_refresh_cookie_not_secure_in_development_env():
    """When no request is given and APP_ENV=development, Secure=false."""
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
        resp = client.post(
            "/api/admin/v1/auth/refresh",
            cookies={"admin_refresh_token": "valid-refresh-token"},
        )
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
        resp = client.post(
            "/api/admin/v1/auth/refresh",
            cookies={"admin_refresh_token": "garbage-token"},
        )
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
        resp = client.post(
            "/api/admin/v1/auth/refresh",
            cookies={"admin_refresh_token": "valid-refresh-token"},
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    data = resp.json()
    assert data["access_token"] == token
    assert data["role"]["name"] == "super_admin"


# ── TOTP 2FA ──


class _UserDb:
    """Fake AsyncSession with execute()/get() returning a single admin user."""

    def __init__(self, user):
        self.user = user
        self.commit = AsyncMock()

    async def execute(self, *args, **kwargs):
        result = MagicMock()
        result.scalar_one_or_none.return_value = self.user
        return result

    async def get(self, model, pk):
        return self.user


def _override_user_db(user):
    db = _UserDb(user)

    async def _gen():
        yield db

    return _gen


def _2fa_user(*, enabled: bool = True):
    user = _admin_user()
    user.totp_secret = generate_totp_secret()
    user.totp_enabled = enabled
    user.totp_confirmed_at = datetime.now() if enabled else None
    return user


def _override_current_admin(user):
    async def _dep():
        return AdminPrincipal(user, {"jti": "token-id", "exp": 4102444800})

    return _dep


def _valid_code(user) -> str:
    return _totp_at(user.totp_secret, time.time())


class Test2faLoginGate:
    def test_login_returns_pending_when_2fa_enabled(self, monkeypatch):
        user = _2fa_user(enabled=True)
        role = _role()
        permissions = ["dashboard:read"]
        monkeypatch.setattr(admin_auth, "authenticate_admin", AsyncMock(return_value=user))
        monkeypatch.setattr(
            admin_auth, "build_admin_login_response",
            AsyncMock(return_value=("tok", "rt", user, role, permissions)),
        )
        app.dependency_overrides[get_db] = _override_db
        try:
            resp = client.post("/api/admin/v1/auth/login", json={"username": "admin", "password": "old-password"})
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 200
        data = resp.json()
        assert data["two_factor_required"] is True
        assert data["pending_token"]
        assert data["access_token"] is None
        # No session cookie is set until the second factor completes.
        assert "admin_refresh_token=" not in resp.headers.get("set-cookie", "")

    def test_login_full_tokens_when_2fa_disabled(self, monkeypatch):
        user = _2fa_user(enabled=False)
        role = _role()
        permissions = ["dashboard:read"]
        token = create_admin_token(user)
        monkeypatch.setattr(admin_auth, "authenticate_admin", AsyncMock(return_value=user))
        monkeypatch.setattr(
            admin_auth, "build_admin_login_response",
            AsyncMock(return_value=(token, "rt", user, role, permissions)),
        )
        app.dependency_overrides[get_db] = _override_db
        try:
            resp = client.post("/api/admin/v1/auth/login", json={"username": "admin", "password": "old-password"})
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 200
        assert resp.json()["two_factor_required"] is False
        assert resp.json()["access_token"] == token


class Test2faVerify:
    def test_verify_with_valid_totp_succeeds(self, monkeypatch):
        user = _2fa_user(enabled=True)
        role = _role()
        permissions = ["dashboard:read"]
        token = create_admin_token(user)
        pending = create_admin_2fa_pending_token(user)
        monkeypatch.setattr(
            admin_auth, "build_admin_login_response",
            AsyncMock(return_value=(token, "new-refresh", user, role, permissions)),
        )
        app.dependency_overrides[get_db] = _override_user_db(user)
        try:
            resp = client.post(
                "/api/admin/v1/auth/2fa/verify",
                json={"pending_token": pending, "code": _valid_code(user)},
            )
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"] == token
        assert data["two_factor_required"] is False
        assert "admin_refresh_token=new-refresh" in resp.headers.get("set-cookie", "")
        assert user.last_login_at is not None

    def test_verify_with_wrong_code_rejected(self, monkeypatch):
        user = _2fa_user(enabled=True)
        pending = create_admin_2fa_pending_token(user)
        app.dependency_overrides[get_db] = _override_user_db(user)
        try:
            resp = client.post(
                "/api/admin/v1/auth/2fa/verify",
                json={"pending_token": pending, "code": "000000"},
            )
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 401

    def test_verify_with_backup_code_consumes_it(self, monkeypatch):
        user = _2fa_user(enabled=True)
        codes = generate_backup_codes(4)
        user.totp_backup_codes = json.dumps([hash_backup_code(c) for c in codes])
        hashes_before = json.loads(user.totp_backup_codes)
        pending = create_admin_2fa_pending_token(user)
        monkeypatch.setattr(
            admin_auth, "build_admin_login_response",
            AsyncMock(return_value=(create_admin_token(user), "rt", user, _role(), [])),
        )
        app.dependency_overrides[get_db] = _override_user_db(user)
        try:
            resp = client.post(
                "/api/admin/v1/auth/2fa/verify",
                json={"pending_token": pending, "code": codes[1]},
            )
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 200
        hashes_after = json.loads(user.totp_backup_codes)
        assert len(hashes_after) == len(hashes_before) - 1
        assert hashes_before[1] not in hashes_after

    def test_verify_pending_token_is_single_use(self, monkeypatch):
        user = _2fa_user(enabled=True)
        pending = create_admin_2fa_pending_token(user)
        monkeypatch.setattr(
            admin_auth, "build_admin_login_response",
            AsyncMock(return_value=(create_admin_token(user), "rt", user, _role(), [])),
        )
        app.dependency_overrides[get_db] = _override_user_db(user)
        try:
            first = client.post(
                "/api/admin/v1/auth/2fa/verify",
                json={"pending_token": pending, "code": _valid_code(user)},
            )
            second = client.post(
                "/api/admin/v1/auth/2fa/verify",
                json={"pending_token": pending, "code": _valid_code(user)},
            )
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert first.status_code == 200
        assert second.status_code == 401

    def test_verify_with_invalid_pending_token_rejected(self, monkeypatch):
        app.dependency_overrides[get_db] = _override_user_db(_2fa_user())
        try:
            resp = client.post(
                "/api/admin/v1/auth/2fa/verify",
                json={"pending_token": "garbage", "code": "123456"},
            )
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 401


class Test2faLifecycle:
    def test_setup_returns_secret_and_persists(self, monkeypatch):
        user = _2fa_user(enabled=False)
        app.dependency_overrides[get_db] = _override_user_db(user)
        app.dependency_overrides[admin_auth.get_current_admin] = _override_current_admin(user)
        try:
            resp = client.get("/api/admin/v1/auth/2fa/setup")
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(admin_auth.get_current_admin, None)

        assert resp.status_code == 200
        data = resp.json()
        assert data["secret"] == user.totp_secret
        assert data["otpauth_uri"].startswith("otpauth://totp/")
        assert data["already_enabled"] is False

    def test_setup_rejected_when_already_enabled(self, monkeypatch):
        user = _2fa_user(enabled=True)
        app.dependency_overrides[get_db] = _override_user_db(user)
        app.dependency_overrides[admin_auth.get_current_admin] = _override_current_admin(user)
        try:
            resp = client.get("/api/admin/v1/auth/2fa/setup")
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(admin_auth.get_current_admin, None)

        assert resp.status_code == 409

    def test_confirm_enables_2fa_and_returns_backup_codes(self, monkeypatch):
        user = _2fa_user(enabled=False)
        monkeypatch.setattr(admin_auth, "write_admin_audit", AsyncMock())
        app.dependency_overrides[get_db] = _override_user_db(user)
        app.dependency_overrides[admin_auth.get_current_admin] = _override_current_admin(user)
        try:
            resp = client.post(
                "/api/admin/v1/auth/2fa/confirm",
                json={"code": _valid_code(user)},
            )
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(admin_auth.get_current_admin, None)

        assert resp.status_code == 200
        backup_codes = resp.json()["backup_codes"]
        assert len(backup_codes) == 8
        assert user.totp_enabled is True
        assert user.totp_confirmed_at is not None
        assert user.totp_backup_codes is not None

    def test_confirm_rejects_wrong_code(self, monkeypatch):
        user = _2fa_user(enabled=False)
        app.dependency_overrides[get_db] = _override_user_db(user)
        app.dependency_overrides[admin_auth.get_current_admin] = _override_current_admin(user)
        try:
            resp = client.post(
                "/api/admin/v1/auth/2fa/confirm",
                json={"code": "000000"},
            )
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(admin_auth.get_current_admin, None)

        assert resp.status_code == 401
        assert user.totp_enabled is False

    def test_confirm_without_pending_secret_rejected(self, monkeypatch):
        user = _2fa_user(enabled=False)
        user.totp_secret = None
        app.dependency_overrides[get_db] = _override_user_db(user)
        app.dependency_overrides[admin_auth.get_current_admin] = _override_current_admin(user)
        try:
            resp = client.post(
                "/api/admin/v1/auth/2fa/confirm",
                json={"code": "123456"},
            )
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(admin_auth.get_current_admin, None)

        assert resp.status_code == 409

    def test_disable_clears_2fa(self, monkeypatch):
        user = _2fa_user(enabled=True)
        monkeypatch.setattr(admin_auth, "write_admin_audit", AsyncMock())
        app.dependency_overrides[get_db] = _override_user_db(user)
        app.dependency_overrides[admin_auth.get_current_admin] = _override_current_admin(user)
        try:
            resp = client.post(
                "/api/admin/v1/auth/2fa/disable",
                json={"code": _valid_code(user)},
            )
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(admin_auth.get_current_admin, None)

        assert resp.status_code == 200
        assert user.totp_enabled is False
        assert user.totp_secret is None
        assert user.totp_backup_codes is None

    def test_disable_rejects_wrong_code(self, monkeypatch):
        user = _2fa_user(enabled=True)
        app.dependency_overrides[get_db] = _override_user_db(user)
        app.dependency_overrides[admin_auth.get_current_admin] = _override_current_admin(user)
        try:
            resp = client.post(
                "/api/admin/v1/auth/2fa/disable",
                json={"code": "000000"},
            )
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(admin_auth.get_current_admin, None)

        assert resp.status_code == 401
        assert user.totp_enabled is True
