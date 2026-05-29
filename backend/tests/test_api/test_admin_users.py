from datetime import datetime
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.api.v1 import admin_users
from app.core.admin_security import AdminPrincipal, get_current_admin
from app.core.database import get_db
from app.main import app
from app.models.admin import AdminUser, Role

client = TestClient(app)


class _Db:
    def __init__(self):
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.refresh = AsyncMock()

    async def execute(self, _statement):
        class _Scalars:
            def all(self):
                return [
                    "admin-user:read",
                    "admin-user:create",
                    "admin-user:update",
                    "admin-user:delete",
                    "admin-user:force-logout",
                    "admin-user:reset-password",
                ]

        class _Result:
            def scalars(self):
                return _Scalars()

        return _Result()


async def _override_db():
    yield _Db()


def _principal():
    user = AdminUser(id=1, username="admin", password_hash="hash", is_active=True, role_id=1)
    return AdminPrincipal(user, {"jti": "token-id", "exp": 4102444800})


async def _allow():
    return _principal()


def _role(role_id=2, name="operator"):
    return Role(id=role_id, name=name, display_name="运营", is_system=False)


def _admin_user(user_id=2, role=None):
    now = datetime(2026, 5, 29)
    user = AdminUser(
        id=user_id,
        username=f"admin{user_id}",
        password_hash="hash",
        display_name="Admin",
        email=f"admin{user_id}@example.com",
        is_active=True,
        role_id=(role.id if role else 2),
        created_at=now,
        updated_at=now,
    )
    user.role = role or _role()
    return user


def test_list_admin_users(monkeypatch):
    monkeypatch.setattr(admin_users, "list_admin_users", AsyncMock(return_value=([_admin_user()], 1)))
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.get("/api/admin/v1/admin-users")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["username"] == "admin2"


def test_get_admin_user_detail(monkeypatch):
    monkeypatch.setattr(admin_users, "get_admin_user_detail", AsyncMock(return_value=_admin_user()))
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.get("/api/admin/v1/admin-users/2")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["role"]["name"] == "operator"


def test_create_admin_user_rejects_super_admin(monkeypatch):
    monkeypatch.setattr(admin_users, "create_admin_user", AsyncMock(side_effect=PermissionError("禁止分配超级管理员角色")))
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.post(
            "/api/admin/v1/admin-users",
            json={"username": "new-admin", "password": "new-password", "role_id": 1},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 403


def test_patch_admin_user_rejects_self_role_change(monkeypatch):
    monkeypatch.setattr(admin_users, "update_admin_user", AsyncMock(side_effect=ValueError("禁止修改自己的角色")))
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.patch("/api/admin/v1/admin-users/1", json={"role_id": 2})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 422


def test_delete_admin_user_rejects_self(monkeypatch):
    monkeypatch.setattr(admin_users, "deactivate_admin_user", AsyncMock(side_effect=ValueError("禁止删除自己")))
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.delete("/api/admin/v1/admin-users/1")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 422


def test_force_logout_rejects_super_admin(monkeypatch):
    monkeypatch.setattr(admin_users, "force_logout_admin_user", AsyncMock(side_effect=PermissionError("禁止操作超级管理员")))
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.post("/api/admin/v1/admin-users/2/force-logout")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 403


def test_reset_password_success(monkeypatch):
    reset_password = AsyncMock()
    monkeypatch.setattr(admin_users, "reset_admin_user_password", reset_password)
    app.dependency_overrides[get_current_admin] = _allow
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.post("/api/admin/v1/admin-users/2/reset-password", json={"new_password": "new-password"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    reset_password.assert_awaited_once()
