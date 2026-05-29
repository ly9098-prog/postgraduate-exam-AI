from datetime import datetime
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.api.v1 import admin_app_users
from app.core.admin_security import AdminPrincipal, get_current_admin
from app.core.database import get_db
from app.main import app
from app.models.admin import AdminUser
from app.models.user import User

client = TestClient(app)


class _Db:
    def __init__(self):
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.refresh = AsyncMock()

    async def execute(self, _statement):
        class _Scalars:
            def all(self):
                return ["app-user:read", "app-user:write", "app-user:ban"]

        class _Result:
            def scalars(self):
                return _Scalars()

        return _Result()


async def _override_db():
    yield _Db()


def _principal():
    user = AdminUser(id=1, username="admin", password_hash="hash", is_active=True, role_id=1)
    return AdminPrincipal(user, {"jti": "token-id", "exp": 4102444800})


def _app_user(user_id=1, banned=False):
    now = datetime(2026, 5, 29)
    return User(
        id=user_id,
        openid=f"openid-{user_id}",
        nickname="用户",
        avatar_url=None,
        is_banned=banned,
        banned_reason="违规" if banned else None,
        banned_at=now if banned else None,
        banned_by=1 if banned else None,
        created_at=now,
        updated_at=now,
    )


async def _allow_read():
    return _principal()


async def _allow_write():
    return _principal()


async def _allow_ban():
    return _principal()


def test_list_app_users(monkeypatch):
    monkeypatch.setattr(admin_app_users, "list_app_users", AsyncMock(return_value=([_app_user()], 1)))
    app.dependency_overrides[get_current_admin] = _allow_read
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.get("/api/admin/v1/app-users")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["openid"] == "openid-1"


def test_get_app_user_detail(monkeypatch):
    detail = _app_user().__dict__ | {"practice_count": 3, "wrong_count": 1, "recent_active_at": None}
    monkeypatch.setattr(admin_app_users, "get_app_user_detail", AsyncMock(return_value=detail))
    app.dependency_overrides[get_current_admin] = _allow_read
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.get("/api/admin/v1/app-users/1")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["practice_count"] == 3


def test_patch_app_user(monkeypatch):
    patch_user = AsyncMock(return_value=_app_user())
    monkeypatch.setattr(admin_app_users, "update_app_user", patch_user)
    app.dependency_overrides[get_current_admin] = _allow_write
    app.dependency_overrides[get_db] = _override_db
    try:
        resp = client.patch("/api/admin/v1/app-users/1", json={"nickname": "新昵称"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    patch_user.assert_awaited_once()


def test_ban_and_unban_app_user(monkeypatch):
    monkeypatch.setattr(admin_app_users, "ban_app_user", AsyncMock(return_value=_app_user(banned=True)))
    monkeypatch.setattr(admin_app_users, "unban_app_user", AsyncMock(return_value=_app_user(banned=False)))
    app.dependency_overrides[get_current_admin] = _allow_ban
    app.dependency_overrides[get_db] = _override_db
    try:
        ban_resp = client.post("/api/admin/v1/app-users/1/ban", json={"reason": "违规"})
        unban_resp = client.post("/api/admin/v1/app-users/1/unban")
    finally:
        app.dependency_overrides.clear()

    assert ban_resp.status_code == 200
    assert ban_resp.json()["is_banned"] is True
    assert unban_resp.status_code == 200
    assert unban_resp.json()["is_banned"] is False


def test_list_app_users_requires_permission():
    resp = client.get("/api/admin/v1/app-users")

    assert resp.status_code in {401, 403}
