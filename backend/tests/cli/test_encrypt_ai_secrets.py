"""Tests for CLI encrypt_ai_secrets migration tool."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet

TEST_FERNET_KEY = Fernet.generate_key().decode()


class TestCategorise:
    def test_empty(self):
        from app.cli.encrypt_ai_secrets import _categorise
        assert _categorise("") == "empty"

    def test_enc_v1(self):
        from app.cli.encrypt_ai_secrets import _categorise
        assert _categorise("enc:v1:token") == "enc_v1"

    def test_enc_unknown(self):
        from app.cli.encrypt_ai_secrets import _categorise
        assert _categorise("enc:v99:token") == "enc_unknown"

    def test_legacy_fernet(self):
        from app.cli.encrypt_ai_secrets import _categorise
        assert _categorise("gAAAAABtesttoken") == "legacy_fernet"

    def test_plaintext(self):
        from app.cli.encrypt_ai_secrets import _categorise
        assert _categorise("sk-raw-key") == "plaintext"


class TestMigrateValue:
    def setup_method(self):
        import os
        os.environ["AI_CONFIG_ENCRYPT_KEY"] = TEST_FERNET_KEY
        from app.core.config import settings
        settings.AI_CONFIG_ENCRYPT_KEY = TEST_FERNET_KEY

    def teardown_method(self):
        import os
        os.environ.pop("AI_CONFIG_ENCRYPT_KEY", None)
        from app.core.config import settings
        settings.AI_CONFIG_ENCRYPT_KEY = ""

    def test_plaintext_gets_encrypted(self):
        from app.cli.encrypt_ai_secrets import _migrate_value
        from app.core.secret_crypto import ENCRYPTED_PREFIX, decrypt_secret

        result = _migrate_value("sk-raw-plaintext", TEST_FERNET_KEY)
        assert result.startswith(ENCRYPTED_PREFIX)
        decrypted = decrypt_secret(result)
        assert decrypted == "sk-raw-plaintext"

    def test_legacy_fernet_reencrypted(self):
        from cryptography.fernet import Fernet
        from app.cli.encrypt_ai_secrets import _migrate_value
        from app.core.secret_crypto import ENCRYPTED_PREFIX, decrypt_secret

        f = Fernet(TEST_FERNET_KEY.encode())
        legacy_token = f.encrypt(b"sk-legacy-value").decode()
        assert not legacy_token.startswith("enc:")  # purely legacy

        result = _migrate_value(legacy_token, TEST_FERNET_KEY)
        assert result.startswith(ENCRYPTED_PREFIX)
        decrypted = decrypt_secret(result)
        assert decrypted == "sk-legacy-value"

    def test_enc_v1_valid_skipped(self):
        from app.core.secret_crypto import encrypt_secret
        from app.cli.encrypt_ai_secrets import _migrate_value

        encrypted = encrypt_secret("sk-already-encrypted")
        result = _migrate_value(encrypted, TEST_FERNET_KEY)
        assert result == encrypted  # unchanged

    def test_enc_v1_empty_raises(self):
        from app.cli.encrypt_ai_secrets import _migrate_value

        with pytest.raises(ValueError, match="empty"):
            _migrate_value("enc:v1:", TEST_FERNET_KEY)

    def test_legacy_wrong_key_raises(self):
        from cryptography.fernet import Fernet

        wrong_key = Fernet.generate_key().decode()
        f = Fernet(wrong_key.encode())
        legacy_token = f.encrypt(b"some-value").decode()

        from app.cli.encrypt_ai_secrets import _migrate_value
        from cryptography.fernet import InvalidToken

        # Different key — can't decrypt legacy token
        with pytest.raises(InvalidToken):
            _migrate_value(legacy_token, Fernet.generate_key().decode())

    def test_enc_v1_corrupted_raises(self):
        from app.cli.encrypt_ai_secrets import _migrate_value

        with pytest.raises(Exception):
            _migrate_value("enc:v1:not-valid-base64!!!", TEST_FERNET_KEY)


class TestCountPending:
    def test_counts_correctly(self):
        from app.cli.encrypt_ai_secrets import _count_pending

        rows = [
            (1, "enc:v1:sometoken"),  # skip
            (2, "sk-plaintext"),       # count
            (3, None),                 # skip
            (4, "gAAAAlegacy"),        # count
        ]
        assert _count_pending(rows, 1) == 2


@pytest.mark.skip(reason="CLI main() needs DB — test with mocked DB")
class TestCLIMain:
    """Full CLI integration tests require database access."""
    pass
