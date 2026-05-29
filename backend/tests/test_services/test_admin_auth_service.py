from unittest.mock import AsyncMock

import pytest

from app.core.admin_security import hash_admin_password, verify_admin_password
from app.models.admin import AdminUser, Role
from app.schemas.admin_auth import AdminChangePasswordRequest, AdminLoginRequest
from app.services.admin_auth_service import authenticate_admin, build_admin_login_response, change_admin_password


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar_one(self):
        return self._value

    def scalars(self):
        class _Scalars:
            def __init__(self, value):
                self._value = value

            def all(self):
                return self._value

        return _Scalars(self._value)


class _Db:
    def __init__(self, result):
        self._result = result
        self.commit = AsyncMock()

    async def execute(self, _statement):
        return _Result(self._result)


@pytest.mark.asyncio
async def test_authenticate_admin_accepts_valid_password():
    user = AdminUser(id=1, username="admin", password_hash=hash_admin_password("secret"), is_active=True, role_id=1)
    db = _Db(user)

    result = await authenticate_admin(db, AdminLoginRequest(username="admin", password="secret"))

    assert result is user


@pytest.mark.asyncio
async def test_authenticate_admin_rejects_invalid_password():
    user = AdminUser(id=1, username="admin", password_hash=hash_admin_password("secret"), is_active=True, role_id=1)
    db = _Db(user)

    with pytest.raises(ValueError, match="用户名或密码错误"):
        await authenticate_admin(db, AdminLoginRequest(username="admin", password="wrong"))


@pytest.mark.asyncio
async def test_build_admin_login_response_returns_token_and_role(monkeypatch):
    user = AdminUser(id=1, username="admin", password_hash=hash_admin_password("secret"), is_active=True, role_id=1)
    role = Role(id=1, name="super_admin", display_name="超级管理员", is_system=True)
    db = _Db(role)

    token, returned_user, returned_role = await build_admin_login_response(db, user)

    assert token
    assert returned_user is user
    assert returned_role is role


@pytest.mark.asyncio
async def test_change_admin_password_updates_hash_and_nbf(monkeypatch):
    user = AdminUser(id=1, username="admin", password_hash=hash_admin_password("secret"), is_active=True, role_id=1)
    db = _Db(None)
    set_nbf = AsyncMock()
    monkeypatch.setattr("app.services.admin_auth_service.set_admin_user_nbf", set_nbf)

    await change_admin_password(db, user, AdminChangePasswordRequest(old_password="secret", new_password="new-secret"))

    assert verify_admin_password("new-secret", user.password_hash)
    set_nbf.assert_awaited_once_with(user.id)
    db.commit.assert_awaited_once()
