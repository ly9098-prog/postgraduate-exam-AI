from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from app.core.admin_security import AdminPrincipal, verify_admin_password
from app.models.admin import AdminUser, Role
from app.schemas.admin_users import (
    AdminUserCreateRequest,
    AdminUserResetPasswordRequest,
)
from app.services import admin_user_service
from app.services.admin_user_service import (
    create_admin_user,
    deactivate_admin_user,
    reset_admin_user_password,
)


class _Db:
    def __init__(self, roles=None, users=None):
        self.roles = roles or {}
        self.users = users or {}
        self.added = []
        self.flush = AsyncMock()
        self.refresh = AsyncMock()

    async def get(self, model, item_id):
        if model is Role:
            return self.roles.get(item_id)
        if model is AdminUser:
            return self.users.get(item_id)
        return None

    def add(self, item):
        item.id = 3
        item.created_at = datetime(2026, 5, 29)
        item.updated_at = datetime(2026, 5, 29)
        item.role = self.roles.get(item.role_id)
        self.added.append(item)


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


def _principal(user_id=1):
    user = AdminUser(id=user_id, username="operator", password_hash="hash", is_active=True, role_id=2)
    return AdminPrincipal(user, {})


def _role(role_id=2, name="operator"):
    return Role(id=role_id, name=name, display_name="运营", is_system=False)


def _admin_user(user_id=2, role=None):
    role = role or _role()
    user = AdminUser(
        id=user_id,
        username=f"admin{user_id}",
        password_hash="hash",
        is_active=True,
        role_id=role.id,
        created_at=datetime(2026, 5, 29),
        updated_at=datetime(2026, 5, 29),
    )
    user.role = role
    return user


@pytest.mark.asyncio
async def test_create_admin_user_hashes_password_and_audits(monkeypatch):
    audit = AsyncMock()
    monkeypatch.setattr(admin_user_service, "write_admin_audit", audit)
    db = _Db(roles={2: _role()})

    result = await create_admin_user(
        db,
        AdminUserCreateRequest(username="new-admin", password="new-password", role_id=2),
        _principal(),
    )

    assert result.username == "new-admin"
    assert verify_admin_password("new-password", result.password_hash)
    assert "new-password" not in str(audit.await_args.kwargs["detail"])


@pytest.mark.asyncio
async def test_create_admin_user_rejects_super_admin_role():
    db = _Db(roles={1: _role(1, "super_admin")})

    with pytest.raises(PermissionError, match="禁止分配超级管理员角色"):
        await create_admin_user(
            db,
            AdminUserCreateRequest(username="new-admin", password="new-password", role_id=1),
            _principal(),
        )


@pytest.mark.asyncio
async def test_deactivate_admin_user_rejects_self():
    target = _admin_user(user_id=1)
    db = _Db(users={1: target})

    async def execute(_statement):
        return _Result(target)

    db.execute = execute

    with pytest.raises(ValueError, match="禁止删除自己"):
        await deactivate_admin_user(db, 1, _principal(user_id=1))


@pytest.mark.asyncio
async def test_reset_password_updates_hash_and_nbf(monkeypatch):
    target = _admin_user()
    db = _Db(users={2: target})

    async def execute(_statement):
        return _Result(target)

    db.execute = execute
    audit = AsyncMock()
    nbf = AsyncMock()
    monkeypatch.setattr(admin_user_service, "write_admin_audit", audit)
    monkeypatch.setattr(admin_user_service, "set_admin_user_nbf", nbf)

    await reset_admin_user_password(db, 2, AdminUserResetPasswordRequest(new_password="new-password"), _principal())

    assert verify_admin_password("new-password", target.password_hash)
    nbf.assert_awaited_once_with(2)
    assert "new-password" not in str(audit.await_args.kwargs["detail"])
