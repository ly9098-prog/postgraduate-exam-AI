"""令牌与用户服务纯函数兼容基线。

覆盖 token_service 和 user_service 中可独立测试的纯规则：
- _hash_token：令牌哈希
- _dev_openid：开发环境确定性 openid
"""

from __future__ import annotations

import hashlib

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
