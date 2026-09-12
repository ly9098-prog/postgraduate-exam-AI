from __future__ import annotations

import asyncio
import socket
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import jwt
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Keep these unit tests independent from a concrete async database driver.
from fastapi import HTTPException

from app.core.cache import cache
from app.core.config import settings

settings.APP_SECRET = "test-only-" + "x" * 64
from app.core.security import decode_token_payload, issue_user_token, set_user_nbf
from app.core.time_utils import utcnow
from app.schemas.question import QuestionPublicResponse
from app.services import safe_remote_fetch, token_service
from app.services.safe_remote_fetch import UnsafeRemoteURLError, validate_remote_url
from app.services.storage_backend import StorageBackend


def _addr(ip: str, port: int = 443):
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return (family, socket.SOCK_STREAM, 6, "", (ip, port))


def test_private_and_mixed_dns_answers_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        safe_remote_fetch.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [_addr("127.0.0.1")],
    )
    with pytest.raises(UnsafeRemoteURLError):
        validate_remote_url("https://example.test/resource")

    monkeypatch.setattr(
        safe_remote_fetch.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [_addr("93.184.216.34"), _addr("10.0.0.7")],
    )
    with pytest.raises(UnsafeRemoteURLError):
        validate_remote_url("https://example.test/resource")


def test_redirect_target_is_revalidated_before_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(host: str, port: int, **kwargs):
        if host == "public.example":
            return [_addr("93.184.216.34", port)]
        return [_addr("127.0.0.1", port)]

    class FakeResponse:
        status = 302

        def getheader(self, name: str, default=None):
            values = {
                "Location": "https://127.0.0.1/internal",
                "Content-Type": "text/plain",
            }
            return values.get(name, default)

        def read(self, size: int = -1) -> bytes:
            return b""

    class FakeConnection:
        def __init__(self, hostname: str, resolved_ip: str, port: int, timeout: float):
            assert hostname == "public.example"
            assert resolved_ip == "93.184.216.34"

        def request(self, *args, **kwargs) -> None:
            return None

        def getresponse(self) -> FakeResponse:
            return FakeResponse()

        def close(self) -> None:
            return None

    monkeypatch.setattr(safe_remote_fetch.socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(safe_remote_fetch, "_PinnedHTTPSConnection", FakeConnection)

    with pytest.raises(UnsafeRemoteURLError):
        safe_remote_fetch.request_remote_bytes(
            "https://public.example/start",
            max_bytes=1024,
            follow_redirects=True,
            max_redirects=2,
        )


def test_storage_upload_key_blocks_traversal() -> None:
    for value in ("../secret", "a/../../secret", "/absolute", "C:\\secret", "a\\b"):
        with pytest.raises(ValueError):
            StorageBackend._validated_upload_key(value)
    assert StorageBackend._validated_upload_key("2026/07/image.png") == "2026/07/image.png"


def test_student_question_schema_never_serializes_answer() -> None:
    source = SimpleNamespace(
        id=1,
        subject_id=1,
        subject="math",
        question_type="single_choice",
        content={"text": "1+1=?"},
        options={"A": "1", "B": "2"},
        answer="B",
        analysis="because",
        knowledge_points=[],
        difficulty=1,
        source=None,
        year=None,
        image_url=None,
    )
    payload = QuestionPublicResponse.model_validate(source).model_dump()
    assert "answer" not in payload
    assert "analysis" not in payload


def test_admin_shaped_jwt_cannot_be_used_as_user_token() -> None:
    now = int(utcnow().timestamp())
    token = jwt.encode(
        {
            "sub": "1",
            "type": "admin",
            "iss": settings.JWT_ISSUER,
            "aud": settings.ADMIN_JWT_AUDIENCE,
            "jti": "test-admin-token",
            "iat": now,
            "exp": now + 60,
        },
        settings.APP_SECRET,
        algorithm="HS256",
    )
    with pytest.raises(HTTPException) as exc:
        decode_token_payload(token)
    assert exc.value.status_code == 401


def test_new_user_token_is_not_blocked_by_same_second_logout_marker() -> None:
    user_id = 987654321

    async def run() -> None:
        await set_user_nbf(user_id)
        token, _ = await issue_user_token(user_id)
        payload = decode_token_payload(token)
        marker = await cache.get_strict(f"user:jwt:nbf:{user_id}")
        assert int(payload["iat"]) >= int(marker)
        await cache.delete_strict(f"user:jwt:nbf:{user_id}")

    asyncio.run(run())


def test_revoked_refresh_token_has_no_grace_window(monkeypatch: pytest.MonkeyPatch) -> None:
    record = SimpleNamespace(
        expires_at=utcnow() + timedelta(days=1),
        revoked_at=utcnow(),
    )

    class Result:
        def scalar_one_or_none(self):
            return record

    class FakeDB:
        async def execute(self, statement):
            return Result()

    assert asyncio.run(token_service.verify_refresh_token(FakeDB(), "raw-token")) is None


def test_refresh_rotation_rejects_already_consumed_token() -> None:
    class Result:
        rowcount = 0

    class FakeDB:
        rolled_back = False

        async def execute(self, statement):
            return Result()

        async def rollback(self):
            self.rolled_back = True

    db = FakeDB()
    current = SimpleNamespace(
        id=1,
        user_id=10,
        expires_at=utcnow() + timedelta(days=1),
    )
    with pytest.raises(ValueError):
        asyncio.run(token_service.rotate_refresh_token(db, current))
    assert db.rolled_back is True
