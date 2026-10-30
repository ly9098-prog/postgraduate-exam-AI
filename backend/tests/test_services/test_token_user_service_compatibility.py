"""令牌/用户纯规则与隔离请求端口的兼容基线。

覆盖 token_service 和 user_service 中可独立测试的纯规则：
- _hash_token：令牌哈希
- _dev_openid：开发环境确定性 openid
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api.v1 import auth as routes
from app.models.user import User
from app.schemas.user import RefreshRequest, UserResponse, UserUpdate, WechatLogin
from app.services import token_service, user_service
from app.services.token_service import _hash_token
from app.services.user_service import _dev_openid


class TestHashToken:
    """_hash_token 使用 SHA-256 哈希令牌。"""

    def test_known_value(self) -> None:
        raw = "test-token-123"
        expected = hashlib.sha256(raw.encode()).hexdigest()
        assert _hash_token(raw) == expected

    def test_deterministic(self) -> None:
        raw = "same-token"
        assert _hash_token(raw) == _hash_token(raw)

    def test_different_inputs_different_hashes(self) -> None:
        assert _hash_token("token-a") != _hash_token("token-b")

    def test_returns_hex_string(self) -> None:
        result = _hash_token("some-token")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_empty_string(self) -> None:
        expected = hashlib.sha256(b"").hexdigest()
        assert _hash_token("") == expected


class TestDevOpenid:
    """_dev_openid 从 code 生成确定性开发环境 openid。"""

    def test_known_value(self) -> None:
        code = "test-code"
        expected = "dev_" + hashlib.md5(code.encode()).hexdigest()[:16]
        assert _dev_openid(code) == expected

    def test_deterministic(self) -> None:
        assert _dev_openid("same-code") == _dev_openid("same-code")

    def test_different_codes_different_openids(self) -> None:
        assert _dev_openid("code-a") != _dev_openid("code-b")

    def test_prefix(self) -> None:
        result = _dev_openid("any-code")
        assert result.startswith("dev_")

    def test_length(self) -> None:
        result = _dev_openid("any-code")
        # "dev_" (4) + md5 hex first 16 chars
        assert len(result) == 4 + 16


def _user(**changes):
    return User(id=17, openid="unit-openid", nickname="Ada", is_banned=False, **changes)


@pytest.mark.asyncio
async def test_login_protocol_preserves_rate_clear_token_and_profile_order(monkeypatch):
    calls = []
    user = _user()

    async def login(db, code):
        calls.append(("login", code))
        return "access-test", 123456, user

    async def clear(key):
        calls.append(("clear", key))

    async def refresh(db, user_id):
        calls.append(("refresh", user_id))
        return "r" * 32

    async def profile(db, actual):
        assert actual is user
        calls.append(("profile", actual.id))
        return UserResponse(id=actual.id)

    monkeypatch.setattr(routes.cache, "get_strict", AsyncMock(return_value=0))
    monkeypatch.setattr(routes.cache, "delete_strict", clear)
    monkeypatch.setattr(user_service, "wechat_login", login)
    monkeypatch.setattr(token_service, "create_refresh_token", refresh)
    monkeypatch.setattr(user_service, "get_user_response", profile)
    actual = await routes.login(
        WechatLogin(code="test-code"),
        SimpleNamespace(client=SimpleNamespace(host="127.0.0.1")),
        object(),
    )
    assert [item[0] for item in calls] == ["login", "clear", "refresh", "profile"]
    assert actual.access_token == "access-test"
    assert actual.refresh_token == "r" * 32
    assert actual.user.id == 17


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user_state", "status", "revoked"),
    [("missing", 401, False), ("deleted", 401, True), ("banned", 403, True)],
)
async def test_refresh_checks_account_before_consuming_token(
    monkeypatch, user_state, status, revoked
):
    user = None if user_state == "missing" else _user()
    if user_state == "deleted":
        user.deleted_at = "deleted-marker"
    if user_state == "banned":
        user.is_banned = True
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: user))
    )
    monkeypatch.setattr(
        token_service,
        "verify_refresh_token",
        AsyncMock(return_value=SimpleNamespace(user_id=17)),
    )
    rotate = AsyncMock()
    revoke = AsyncMock()
    monkeypatch.setattr(token_service, "rotate_refresh_token", rotate)
    monkeypatch.setattr(token_service, "revoke_all_user_tokens", revoke)
    with pytest.raises(HTTPException) as failure:
        await routes.refresh(RefreshRequest(refresh_token="r" * 32), db)
    assert failure.value.status_code == status
    rotate.assert_not_awaited()
    assert revoke.await_count == int(revoked)


@pytest.mark.asyncio
async def test_refresh_consumes_before_issuing_access_token(monkeypatch):
    calls = []
    user = _user()
    record = SimpleNamespace(user_id=17)
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: user))
    )

    async def rotate(actual_db, actual_record):
        assert actual_db is db and actual_record is record
        calls.append("rotate")
        return "new-refresh"

    async def issue(user_id):
        calls.append("issue")
        return "new-access", 456

    async def profile(actual_db, actual_user):
        calls.append("profile")
        return UserResponse(id=actual_user.id)

    monkeypatch.setattr(
        token_service, "verify_refresh_token", AsyncMock(return_value=record)
    )
    monkeypatch.setattr(token_service, "rotate_refresh_token", rotate)
    monkeypatch.setattr(routes, "issue_user_token", issue)
    monkeypatch.setattr(user_service, "get_user_response", profile)
    actual = await routes.refresh(RefreshRequest(refresh_token="r" * 32), db)
    assert calls == ["rotate", "issue", "profile"]
    assert (actual.access_token, actual.refresh_token) == ("new-access", "new-refresh")


@pytest.mark.asyncio
async def test_avatar_route_closes_input_before_storage_and_projection(monkeypatch):
    calls = []
    user = _user()

    async def close():
        calls.append("close")

    async def replace(db, actual_user, data):
        assert actual_user is user and data == b"synthetic"
        calls.append("replace")
        return user

    async def profile(db, actual_user):
        calls.append("profile")
        return UserResponse(id=17)

    file = SimpleNamespace(read=AsyncMock(return_value=b"synthetic"), close=close)
    monkeypatch.setattr(user_service, "replace_user_avatar", replace)
    monkeypatch.setattr(user_service, "get_user_response", profile)
    actual = await routes.upload_my_avatar(file, object(), user)
    assert actual.id == 17 and calls == ["close", "replace", "profile"]
    file.read.assert_awaited_once_with(routes.MAX_AVATAR_UPLOAD_BYTES + 1)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw", "status"), [(b"", 400), (b"x" * (5 * 1024 * 1024 + 1), 413)]
)
async def test_avatar_rejects_empty_or_oversize_without_storage(
    monkeypatch, raw, status
):
    file = SimpleNamespace(read=AsyncMock(return_value=raw), close=AsyncMock())
    replace = AsyncMock()
    monkeypatch.setattr(user_service, "replace_user_avatar", replace)
    with pytest.raises(HTTPException) as failure:
        await routes.upload_my_avatar(file, object(), _user())
    assert failure.value.status_code == status
    file.close.assert_awaited_once()
    replace.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status"), [(ValueError("image"), 422), (RuntimeError("store"), 503)]
)
async def test_avatar_storage_errors_keep_protocol_mapping(monkeypatch, error, status):
    file = SimpleNamespace(read=AsyncMock(return_value=b"synthetic"), close=AsyncMock())
    monkeypatch.setattr(
        user_service, "replace_user_avatar", AsyncMock(side_effect=error)
    )
    with pytest.raises(HTTPException) as failure:
        await routes.upload_my_avatar(file, object(), _user())
    assert failure.value.status_code == status
    file.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_avatar_commit_failure_rolls_back_and_removes_only_new_object(
    monkeypatch,
):
    user = _user(avatar_url="old-avatar")
    db = SimpleNamespace(
        commit=AsyncMock(side_effect=ValueError("commit")),
        refresh=AsyncMock(),
        rollback=AsyncMock(),
    )
    storage = SimpleNamespace(
        upload=AsyncMock(return_value="new-avatar"), delete=AsyncMock()
    )
    monkeypatch.setattr(user_service, "_normalize_avatar_bytes", lambda raw: b"jpeg")
    monkeypatch.setattr(user_service, "get_user_avatar_storage", lambda: storage)
    old_delete = AsyncMock()
    monkeypatch.setattr(user_service, "delete_user_avatar_file", old_delete)
    with pytest.raises(ValueError, match="commit"):
        await user_service.replace_user_avatar(db, user, b"synthetic")
    key, normalized = storage.upload.await_args.args
    assert key.startswith("17/") and key.endswith(".jpg") and normalized == b"jpeg"
    db.rollback.assert_awaited_once()
    storage.delete.assert_awaited_once_with("new-avatar")
    old_delete.assert_not_awaited()
    db.refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_avatar_old_object_cleanup_follows_durable_profile(monkeypatch):
    calls = []
    user = _user(avatar_url="old-avatar")

    async def commit():
        calls.append("commit")

    async def refresh(actual_user):
        assert actual_user is user
        calls.append("refresh")

    async def delete(url, *, storage):
        assert url == "old-avatar"
        calls.append("old-delete")

    db = SimpleNamespace(commit=commit, refresh=refresh)
    storage = SimpleNamespace(upload=AsyncMock(return_value="new-avatar"))
    monkeypatch.setattr(user_service, "_normalize_avatar_bytes", lambda raw: b"jpeg")
    monkeypatch.setattr(user_service, "get_user_avatar_storage", lambda: storage)
    monkeypatch.setattr(user_service, "delete_user_avatar_file", delete)
    assert await user_service.replace_user_avatar(db, user, b"synthetic") is user
    assert calls == ["commit", "refresh", "old-delete"]


@pytest.mark.asyncio
async def test_profile_update_uses_current_user_and_normalized_nickname(monkeypatch):
    user = _user()
    update = AsyncMock(return_value=user)
    projection = AsyncMock(return_value=UserResponse(id=17))
    monkeypatch.setattr(user_service, "update_user", update)
    monkeypatch.setattr(user_service, "get_user_response", projection)
    db = object()
    actual = await routes.update_me(UserUpdate(nickname="  Ada  Lovelace  "), db, user)
    update.assert_awaited_once_with(db, 17, "Ada Lovelace")
    projection.assert_awaited_once_with(db, user)
    assert actual.id == 17


@pytest.mark.asyncio
async def test_logout_revocation_precedes_access_invalidation(monkeypatch):
    calls = []

    async def revoke(db, user_id):
        calls.append(("refresh-revoke", user_id))

    async def invalidate(user_id):
        calls.append(("access-invalidate", user_id))

    monkeypatch.setattr(token_service, "revoke_all_user_tokens", revoke)
    monkeypatch.setattr(routes, "set_user_nbf", invalidate)
    assert await routes.logout(object(), _user()) == {"message": "已退出登录"}
    assert calls == [("refresh-revoke", 17), ("access-invalidate", 17)]
