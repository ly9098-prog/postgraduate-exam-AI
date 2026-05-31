from types import SimpleNamespace

import pytest

from app.core import security
from app.models.user import User
from app.services import user_service


class _ForbiddenDb:
    async def execute(self, _statement):
        raise AssertionError("local dev user should bypass RBAC query")


@pytest.mark.asyncio
async def test_require_app_permission_allows_local_dev_user(monkeypatch):
    monkeypatch.setattr(security.settings, "APP_ENV", "development")
    dependency = security.require_app_permission("import:read")
    user = SimpleNamespace(id=1, openid="dev_1234567890abcdef")

    result = await dependency(current_user=user, db=_ForbiddenDb())

    assert result is user


@pytest.mark.asyncio
async def test_require_app_permission_does_not_bypass_non_dev_user(monkeypatch):
    monkeypatch.setattr(security.settings, "APP_ENV", "development")
    dependency = security.require_app_permission("import:read")
    user = SimpleNamespace(id=1, openid="real-openid")

    with pytest.raises(AssertionError):
        await dependency(current_user=user, db=_ForbiddenDb())


@pytest.mark.asyncio
async def test_get_user_response_marks_local_dev_user_super_admin(monkeypatch):
    monkeypatch.setattr(user_service.settings, "APP_ENV", "development")
    user = User(id=1, openid="dev_1234567890abcdef", nickname="Dev")

    response = await user_service.get_user_response(_ForbiddenDb(), user)

    assert response.is_admin is True
    assert response.role == "super_admin"
    assert response.role_name == "super_admin"
    assert response.permissions == ["*"]
