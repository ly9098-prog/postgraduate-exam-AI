"""Tests for app.core.secret_crypto — Fernet encryption with versioned envelopes."""

from __future__ import annotations

import os

import pytest
from cryptography.fernet import Fernet

from app.core.secret_crypto import (
    ENCRYPTED_PREFIX,
    SecretDecryptionError,
    SecretEncryptionError,
    SecretEnvelopeVersionError,
    decrypt_secret,
    encrypt_secret,
    is_encrypted_secret,
    is_mask_placeholder,
    is_sensitive_field,
    parse_secret_envelope,
    sanitise_dict,
)

TEST_API_KEY = "sk-test-do-not-use-123456"

# Generate a valid Fernet key for tests
TEST_FERNET_KEY = Fernet.generate_key().decode()
WRONG_FERNET_KEY = Fernet.generate_key().decode()


# ── Helpers ──


def _set_key(key: str | None):
    """Set AI_CONFIG_ENCRYPT_KEY for the duration of a test."""
    if key is None:
        os.environ.pop("AI_CONFIG_ENCRYPT_KEY", None)
    else:
        os.environ["AI_CONFIG_ENCRYPT_KEY"] = key
    # Reload module-level cached settings
    from app.core import config as core_config
    core_config.settings.AI_CONFIG_ENCRYPT_KEY = key or ""


# ── Encrypt / Decrypt round-trip ──


class TestEncryptDecrypt:
    def setup_method(self):
        _set_key(TEST_FERNET_KEY)

    def teardown_method(self):
        _set_key(None)

    def test_round_trip(self):
        cipher = encrypt_secret(TEST_API_KEY)
        assert cipher.startswith(ENCRYPTED_PREFIX)
        assert cipher != TEST_API_KEY
        plain = decrypt_secret(cipher)
        assert plain == TEST_API_KEY

    def test_same_plaintext_different_ciphertext(self):
        """Fernet is non-deterministic — same input produces different output."""
        c1 = encrypt_secret(TEST_API_KEY)
        c2 = encrypt_secret(TEST_API_KEY)
        assert c1 != c2
        assert decrypt_secret(c1) == decrypt_secret(c2) == TEST_API_KEY

    def test_ciphertext_does_not_contain_plaintext(self):
        cipher = encrypt_secret(TEST_API_KEY)
        assert TEST_API_KEY not in cipher

    def test_empty_plaintext_raises(self):
        with pytest.raises(SecretEncryptionError, match="Cannot encrypt empty"):
            encrypt_secret("")

    def test_encrypted_secret_check(self):
        cipher = encrypt_secret(TEST_API_KEY)
        assert is_encrypted_secret(cipher) is True
        assert is_encrypted_secret("") is False
        assert is_encrypted_secret("random-text") is False

    def test_decrypt_empty_raises(self):
        with pytest.raises(SecretDecryptionError, match="empty"):
            decrypt_secret("")

    def test_decrypt_no_prefix_raises(self):
        with pytest.raises(SecretDecryptionError, match="not a recognised"):
            decrypt_secret("plaintext-key")


# ── Missing / invalid key ──


class TestKeyErrors:
    def teardown_method(self):
        _set_key(None)

    def test_missing_key_encrypt_raises(self):
        _set_key(None)
        with pytest.raises(SecretEncryptionError, match="not configured"):
            encrypt_secret(TEST_API_KEY)

    def test_missing_key_decrypt_raises(self):
        _set_key(None)
        with pytest.raises(SecretEncryptionError, match="not configured"):
            decrypt_secret(f"{ENCRYPTED_PREFIX}dummy")

    def test_invalid_key_encrypt_raises(self):
        _set_key("not-a-valid-key")
        with pytest.raises(SecretEncryptionError, match="invalid"):
            encrypt_secret(TEST_API_KEY)


# ── Wrong key / data corruption ──


class TestDecryptErrors:
    def setup_method(self):
        _set_key(TEST_FERNET_KEY)

    def teardown_method(self):
        _set_key(None)

    def test_wrong_key_raises(self):
        cipher = encrypt_secret(TEST_API_KEY)
        _set_key(WRONG_FERNET_KEY)
        with pytest.raises(SecretDecryptionError, match="Failed to decrypt"):
            decrypt_secret(cipher)

    def test_corrupted_token_raises(self):
        bad = f"{ENCRYPTED_PREFIX}corrupted-base64!!!"
        with pytest.raises(SecretDecryptionError):
            decrypt_secret(bad)

    def test_does_not_return_empty_string(self):
        """Decryption failure must never return '' to masquerade as 'not configured'."""
        # Encrypt with one key, try to decrypt with wrong key
        _set_key(TEST_FERNET_KEY)
        cipher = encrypt_secret(TEST_API_KEY)
        _set_key(WRONG_FERNET_KEY)
        with pytest.raises(SecretDecryptionError):
            decrypt_secret(cipher)

    def test_does_not_return_original(self):
        """Decryption failure must never return the original string."""
        with pytest.raises(SecretDecryptionError):
            decrypt_secret("some-plaintext")


# ── Envelope parsing ──


class TestEnvelopeParsing:
    def setup_method(self):
        _set_key(TEST_FERNET_KEY)

    def teardown_method(self):
        _set_key(None)

    def test_parse_v1(self):
        cipher = encrypt_secret(TEST_API_KEY)
        env = parse_secret_envelope(cipher)
        assert env.version == "v1"
        assert env.token
        assert env.raw == cipher

    def test_parse_unknown_version(self):
        with pytest.raises(SecretEnvelopeVersionError, match="Unsupported encryption version.*v2"):
            parse_secret_envelope("enc:v2:sometoken")

    def test_parse_no_version(self):
        with pytest.raises(SecretEnvelopeVersionError, match="no version"):
            parse_secret_envelope("enc:")

    def test_parse_no_prefix_raises_value_error(self):
        with pytest.raises(ValueError, match="not a recognised"):
            parse_secret_envelope("raw-plaintext")


# ── Mask placeholder detection ──


class TestMaskPlaceholder:
    def test_basic_masks(self):
        assert is_mask_placeholder("****") is True
        assert is_mask_placeholder("********") is True
        assert is_mask_placeholder("******") is True

    def test_masks_with_whitespace(self):
        assert is_mask_placeholder(" ****") is True
        assert is_mask_placeholder("**** ") is True

    def test_not_masks(self):
        assert is_mask_placeholder(None) is False
        assert is_mask_placeholder("") is False
        assert is_mask_placeholder("sk-real-key") is False
        assert is_mask_placeholder("***") is False  # less than 4 asterisks
        assert is_mask_placeholder("a***") is False


# ── Sensitive field detection ──


class TestSensitiveField:
    def test_api_key_fields(self):
        assert is_sensitive_field("api_key") is True
        assert is_sensitive_field("API_KEY") is True
        assert is_sensitive_field("embedding_api_key") is True
        assert is_sensitive_field("api_key_encrypted") is True

    def test_token_fields(self):
        assert is_sensitive_field("access_token") is True
        assert is_sensitive_field("refresh_token") is True

    def test_auth_fields(self):
        assert is_sensitive_field("authorization") is True
        assert is_sensitive_field("proxy_authorization") is True

    def test_password_fields(self):
        assert is_sensitive_field("password") is True
        assert is_sensitive_field("password_hash") is True

    def test_non_sensitive(self):
        assert is_sensitive_field("display_name") is False
        assert is_sensitive_field("model_name") is False
        assert is_sensitive_field("sort_order") is False
        assert is_sensitive_field("created_at") is False


# ── Sanitise dict (recursive) ──


class TestSanitiseDict:
    def test_flat_dict(self):
        d = {"api_key": "secret-123", "name": "test"}
        result = sanitise_dict(d)
        assert result["api_key"] == "[REDACTED]"
        assert result["name"] == "test"

    def test_nested_dict(self):
        d = {"changes": {"api_key_updated": True, "api_key": "secret"}}
        result = sanitise_dict(d)
        assert result["changes"]["api_key"] == "[REDACTED]"
        assert result["changes"]["api_key_updated"] is True

    def test_list_of_dicts(self):
        d = {"items": [{"api_key": "s1"}, {"api_key": "s2"}]}
        result = sanitise_dict(d)
        assert result["items"][0]["api_key"] == "[REDACTED]"
        assert result["items"][1]["api_key"] == "[REDACTED]"

    def test_tuple(self):
        d = {"creds": ({"api_key": "secret"},)}
        result = sanitise_dict(d)
        assert result["creds"][0]["api_key"] == "[REDACTED]"

    def test_none(self):
        assert sanitise_dict(None) is None  # type: ignore[arg-type]
