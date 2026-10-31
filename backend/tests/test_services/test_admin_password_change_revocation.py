import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.core.time_utils import unix_timestamp, utcnow
from app.schemas.admin_auth import AdminChangePasswordRequest
from app.services import admin_auth_service


def test_password_change_watermark_uses_change_time_not_acting_token_iat(monkeypatch):
    captured = {}

    async def fake_set_nbf(user_id, timestamp=None):
        captured["timestamp"] = timestamp

    monkeypatch.setattr(admin_auth_service, "set_admin_user_nbf", fake_set_nbf)
    monkeypatch.setattr(admin_auth_service, "verify_admin_password", lambda *_: True)
    monkeypatch.setattr(admin_auth_service, "validate_admin_password_strength", lambda *_: None)
    monkeypatch.setattr(admin_auth_service, "hash_admin_password", lambda *_: "hashed")
    monkeypatch.setattr(admin_auth_service, "write_admin_audit", AsyncMock())

    user = SimpleNamespace(id=7, username="admin", password_hash="old")
    db = SimpleNamespace(commit=AsyncMock())
    old_iat = int(unix_timestamp(utcnow())) - 3600
    operator = SimpleNamespace(token_payload={"iat": old_iat})
    data = AdminChangePasswordRequest(old_password="Old-Passw0rd!x", new_password="New-Passw0rd!x9")

    before = int(unix_timestamp(utcnow()))
    asyncio.run(admin_auth_service.change_admin_password(db, user, data, operator=operator))

    assert captured["timestamp"] is not None
    assert captured["timestamp"] > before
    assert captured["timestamp"] > old_iat + 1
