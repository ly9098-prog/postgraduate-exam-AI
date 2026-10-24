"""Real compatibility baseline for worker credential pure functions."""

from __future__ import annotations

import pytest

from app.services.worker_credential_service import (
    constant_time_compare,
    generate_key,
    hash_key,
)


class TestHashKey:
    def test_deterministic(self):
        assert hash_key("test") == hash_key("test")

    def test_different_keys_different_hashes(self):
        assert hash_key("a") != hash_key("b")

    def test_returns_hex_string(self):
        result = hash_key("test")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_empty_string(self):
        result = hash_key("")
        assert len(result) == 64


class TestGenerateKey:
    def test_returns_64_hex_chars(self):
        key = generate_key()
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)

    def test_generates_different_keys(self):
        keys = {generate_key() for _ in range(10)}
        assert len(keys) == 10


class TestConstantTimeCompare:
    def test_equal_strings(self):
        assert constant_time_compare("abc", "abc") is True

    def test_different_strings(self):
        assert constant_time_compare("abc", "abd") is False

    def test_different_lengths(self):
        assert constant_time_compare("ab", "abc") is False

    def test_empty_strings(self):
        assert constant_time_compare("", "") is True
