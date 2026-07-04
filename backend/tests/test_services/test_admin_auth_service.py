from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.admin_security import hash_admin_password, verify_admin_password
from app.core.database import Base
from app.models.admin import AdminUser, AuditLog, Permission, Role, RolePermission
from app.schemas.admin_auth import AdminChangePasswordRequest, AdminLoginRequest
from app.services.admin_auth_service import authenticate_admin, build_admin_login_response, change_admin_password
from app.services.admin_bootstrap_service import ADMIN_PERMISSION_DEFINITIONS, ADMIN_ROLE_PERMISSION_NAMES, ensure_dev_super_admin


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
        self._results = list(result) if isinstance(result, list) else [result]
        self.added = []
        self.commit = AsyncMock()
        self.flush = AsyncMock()

    async def execute(self, _statement):
        return _Result(self._results.pop(0))

    def add(self, item):
        self.added.append(item)


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
    permissions = ["dashboard:read"]
    db = _Db([role, permissions])

    token, refresh_token, returned_user, returned_role, returned_permissions = await build_admin_login_response(db, user)

    assert token
    assert refresh_token
    assert returned_user is user
    assert returned_role is role
    assert returned_permissions == permissions


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


@pytest.mark.asyncio
async def test_ensure_dev_super_admin_initializes_defaults_and_is_idempotent(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'admin-bootstrap.db'}")
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with sessionmaker() as db:
        created = await ensure_dev_super_admin(db, "development")
        await db.commit()

    assert created is True

    async with sessionmaker() as db:
        role = (await db.execute(select(Role).where(Role.name == "super_admin"))).scalar_one()
        admin_role = (await db.execute(select(Role).where(Role.name == "admin"))).scalar_one()
        admin_user = (await db.execute(select(AdminUser).where(AdminUser.username == "admin"))).scalar_one()
        permissions = (await db.execute(select(Permission).order_by(Permission.name.asc()))).scalars().all()
        role_permission_ids = set((await db.execute(select(RolePermission.permission_id).where(RolePermission.role_id == role.id))).scalars().all())
        admin_role_permission_ids = set((await db.execute(select(RolePermission.permission_id).where(RolePermission.role_id == admin_role.id))).scalars().all())
        audits = (await db.execute(select(AuditLog).where(AuditLog.action == "system.init_super_admin"))).scalars().all()

    permission_ids_by_name = {permission.name: permission.id for permission in permissions}
    assert admin_user.role_id == role.id
    assert role.is_system is True
    assert admin_role.is_system is True
    assert admin_role.display_name == "普通管理员"
    assert admin_user.username == "admin"
    assert verify_admin_password("admin", admin_user.password_hash)
    assert len(permissions) == len(ADMIN_PERMISSION_DEFINITIONS)
    assert {permission.name for permission in permissions} == {item["name"] for item in ADMIN_PERMISSION_DEFINITIONS}
    assert role_permission_ids == {permission.id for permission in permissions}
    assert admin_role_permission_ids == {permission_ids_by_name[name] for name in ADMIN_ROLE_PERMISSION_NAMES}
    assert len(audits) == 1
    assert audits[0].severity == "critical"

    async with sessionmaker() as db:
        created_again = await ensure_dev_super_admin(db, "development")
        await db.commit()

    assert created_again is False

    await engine.dispose()


@pytest.mark.asyncio
async def test_ensure_dev_super_admin_skips_production(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'admin-bootstrap-prod.db'}")
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with sessionmaker() as db:
        created = await ensure_dev_super_admin(db, "production")
        await db.commit()

    assert created is False

    async with sessionmaker() as db:
        assert (await db.execute(select(AdminUser))).scalars().all() == []
        assert (await db.execute(select(Role))).scalars().all() == []
        assert (await db.execute(select(AuditLog))).scalars().all() == []

    await engine.dispose()
