from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from app.core.admin_security import AdminPrincipal
from app.models.admin import AdminUser
from app.models.user import User
from app.schemas.admin_app_users import AdminAppUserBanRequest, AdminAppUserUpdateRequest
from app.services import admin_app_user_service
from app.services.admin_app_user_service import ban_app_user, unban_app_user, update_app_user


class _Db:
    def __init__(self, user):
        self.user = user

    async def get(self, _model, _id):
        return self.user


def _principal():
    user = AdminUser(id=9, username="operator", password_hash="hash", is_active=True, role_id=2)
    return AdminPrincipal(user, {})


def _user():
    return User(
        id=1,
        openid="openid",
        nickname="旧昵称",
        is_banned=False,
        created_at=datetime(2026, 5, 29),
        updated_at=datetime(2026, 5, 29),
    )


@pytest.mark.asyncio
async def test_update_app_user_writes_audit(monkeypatch):
    user = _user()
    audit = AsyncMock()
    monkeypatch.setattr(admin_app_user_service, "write_admin_audit", audit)

    result = await update_app_user(_Db(user), 1, AdminAppUserUpdateRequest(nickname="新昵称"), _principal())

    assert result.nickname == "新昵称"
    detail = audit.await_args.kwargs["detail"]
    assert detail == {"before": {"nickname": "旧昵称"}, "after": {"nickname": "新昵称"}}


@pytest.mark.asyncio
async def test_ban_app_user_sets_fields_and_audit(monkeypatch):
    user = _user()
    audit = AsyncMock()
    monkeypatch.setattr(admin_app_user_service, "write_admin_audit", audit)

    result = await ban_app_user(_Db(user), 1, AdminAppUserBanRequest(reason="违规"), _principal())

    assert result.is_banned is True
    assert result.banned_reason == "违规"
    assert result.banned_by == 9
    assert result.banned_at is not None
    assert audit.await_args.kwargs["severity"] == "critical"


@pytest.mark.asyncio
async def test_unban_app_user_clears_fields(monkeypatch):
    user = _user()
    user.is_banned = True
    user.banned_reason = "违规"
    user.banned_at = datetime(2026, 5, 29)
    user.banned_by = 9
    audit = AsyncMock()
    monkeypatch.setattr(admin_app_user_service, "write_admin_audit", audit)

    result = await unban_app_user(_Db(user), 1, _principal())

    assert result.is_banned is False
    assert result.banned_reason is None
    assert result.banned_at is None
    assert result.banned_by is None
    assert audit.await_args.kwargs["detail"]["after"] == {"is_banned": False, "banned_reason": None, "banned_at": None, "banned_by": None}
