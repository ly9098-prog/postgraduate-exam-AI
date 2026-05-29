from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.api.v1 import admin_auth
from app.core.admin_security import AdminPrincipal, create_admin_token, hash_admin_password
from app.core.database import get_db
from app.main import app
from app.models.admin import AdminUser, Role

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
    token = create_admin_token(user)

    monkeypatch.setattr(admin_auth, "authenticate_admin", AsyncMock(return_value=user))
    monkeypatch.setattr(admin_auth, "build_admin_login_response", AsyncMock(return_value=(token, user, role)))
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


def test_admin_me_returns_current_admin():
    user = _admin_user()

    async def override_current_admin():
        return AdminPrincipal(user, {"jti": "token-id", "exp": 4102444800})

    app.dependency_overrides[admin_auth.get_current_admin] = override_current_admin
    try:
        resp = client.get("/api/admin/v1/auth/me")
    finally:
        app.dependency_overrides.pop(admin_auth.get_current_admin, None)

    assert resp.status_code == 200
    assert resp.json() == {"id": 1, "username": "admin", "roleId": 1, "isActive": True}


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
