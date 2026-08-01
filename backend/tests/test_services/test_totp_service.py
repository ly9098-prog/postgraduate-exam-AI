"""Tests for the stdlib TOTP implementation (totp_service.py)."""

from __future__ import annotations

from app.services.totp_service import (
    _hotp,
    generate_backup_codes,
    generate_totp_secret,
    hash_backup_code,
    otpauth_uri,
    verify_backup_code,
    verify_totp,
)


class TestRfcVectors:
    """RFC 6238 Appendix B vectors (SHA-1, 8 digits)."""

    # key bytes = ASCII "12345678901234567890"
    KEY = b"12345678901234567890"
    VECTORS = [
        (59, "94287082"),
        (1111111109, "07081804"),
        (1111111111, "14050471"),
        (1234567890, "89005924"),
        (2000000000, "69279037"),
    ]

    def test_hotp_matches_rfc_vectors(self):
        for t, expected in self.VECTORS:
            assert _hotp(self.KEY, t // 30, digits=8) == expected


class TestVerifyTotp:
    def test_accepts_current_code(self):
        secret = generate_totp_secret()
        from app.services.totp_service import _totp_at

        code = _totp_at(secret, 1234567890.0)
        assert verify_totp(secret, code, now=1234567890.0)

    def test_rejects_wrong_code(self):
        secret = generate_totp_secret()
        assert not verify_totp(secret, "000000", now=1234567890.0)

    def test_accepts_code_one_step_ago(self):
        # Window of 1 covers previous step.
        secret = generate_totp_secret()
        from app.services.totp_service import _totp_at

        code = _totp_at(secret, 1234567890.0 - 30)
        assert verify_totp(secret, code, now=1234567890.0)

    def test_rejects_code_two_steps_ago_outside_window(self):
        secret = generate_totp_secret()
        from app.services.totp_service import _totp_at

        code = _totp_at(secret, 1234567890.0 - 60)
        assert not verify_totp(secret, code, now=1234567890.0, window=1)
        # But accepted with a wider window.
        assert verify_totp(secret, code, now=1234567890.0, window=2)

    def test_rejects_non_numeric_and_wrong_length(self):
        secret = generate_totp_secret()
        assert not verify_totp(secret, "abcdef")
        assert not verify_totp(secret, "12345")
        assert not verify_totp(secret, "1234567")

    def test_rejects_empty_secret(self):
        assert not verify_totp("", "123456")

    def test_verify_uses_current_time_by_default(self):
        # No error when called without an explicit timestamp.
        secret = generate_totp_secret()
        from app.services.totp_service import _totp_at

        assert verify_totp(secret, _totp_at(secret, __import__("time").time()))


class TestBackupCodes:
    def test_generate_returns_unique_expected_count(self):
        codes = generate_backup_codes(8)
        assert len(codes) == 8
        assert len(set(codes)) == 8
        for c in codes:
            assert len(c) == 10

    def test_verify_matches_and_consumes(self):
        codes = generate_backup_codes(4)
        hashes = [hash_backup_code(c) for c in codes]
        matched, remaining = verify_backup_code(codes[2], hashes)
        assert matched is True
        assert len(remaining) == 3
        assert hashes[2] not in remaining

    def test_verify_missing_code_does_not_consume(self):
        hashes = [hash_backup_code(c) for c in generate_backup_codes(2)]
        matched, remaining = verify_backup_code("ZZZZZZZZZZ", hashes)
        assert matched is False
        assert remaining == hashes

    def test_verify_case_insensitive(self):
        codes = generate_backup_codes(1)
        hashes = [hash_backup_code(codes[0])]
        matched, _ = verify_backup_code(codes[0].lower(), hashes)
        assert matched is True

    def test_verify_empty_input(self):
        assert verify_backup_code("", []) == (False, [])


class TestSecretAndUri:
    def test_generate_secret_is_32_base32_chars(self):
        secret = generate_totp_secret()
        assert len(secret) == 32
        assert set(secret) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")

    def test_otpauth_uri_shape(self):
        uri = otpauth_uri("ABC234", "admin")
        assert uri.startswith("otpauth://totp/")
        assert "secret=ABC234" in uri
        assert "issuer=" in uri
        assert "digits=6" in uri
        assert "period=30" in uri
