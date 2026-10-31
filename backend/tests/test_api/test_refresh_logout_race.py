import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.v1 import auth as auth_api
from app.schemas.user import RefreshRequest


def _setup(monkeypatch, marker_values):
    user = SimpleNamespace(id=5, deleted_at=None, is_banned=False)
    result = MagicMock()
    result.scalar_one_or_none.return_value = user
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    revoke = AsyncMock()
    issue = AsyncMock(return_value=("jwt", 123))
    markers = iter(marker_values)
    monkeypatch.setattr(auth_api.token_service, "verify_refresh_token", AsyncMock(return_value=SimpleNamespace(user_id=5)))
    monkeypatch.setattr(auth_api.token_service, "rotate_refresh_token", AsyncMock(return_value="new-refresh"))
    monkeypatch.setattr(auth_api.token_service, "revoke_all_user_tokens", revoke)
    monkeypatch.setattr(auth_api, "read_user_nbf", AsyncMock(side_effect=lambda _uid: next(markers)))
    monkeypatch.setattr(auth_api, "issue_user_token", issue)
    monkeypatch.setattr(auth_api.user_service, "get_user_response", AsyncMock(return_value={"id": 5}))
    return db, revoke, issue


def test_refresh_fails_when_logout_marker_advances_during_rotation(monkeypatch):
    db, revoke, issue = _setup(monkeypatch, [None, 1700000001])
    with pytest.raises(HTTPException) as exc:
        asyncio.run(auth_api.refresh(RefreshRequest(refresh_token="o" * 40), db=db))
    assert exc.value.status_code == 401
    revoke.assert_awaited_once()
    issue.assert_not_awaited()


def test_refresh_succeeds_when_marker_unchanged(monkeypatch):
    db, revoke, issue = _setup(monkeypatch, [1700000000, 1700000000])
    asyncio.run(auth_api.refresh(RefreshRequest(refresh_token="o" * 40), db=db))
    revoke.assert_not_awaited()
    issue.assert_awaited_once()
