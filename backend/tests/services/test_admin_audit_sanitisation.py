"""Tests for admin_audit_service sanitisation."""

from app.core.secret_crypto import sanitise_dict


class TestAuditSanitisation:
    def test_flat_dict_sanitises_api_key(self):
        d = {"api_key": "sk-secret-123", "name": "normal-field"}
        result = sanitise_dict(d)
        assert result["api_key"] == "[REDACTED]"
        assert result["name"] == "normal-field"

    def test_nested_dict_recursive(self):
        d = {
            "changes": {
                "api_key_updated": True,
                "api_key": "secret-value",
            }
        }
        result = sanitise_dict(d)
        assert result["changes"]["api_key"] == "[REDACTED]"
        assert result["changes"]["api_key_updated"] is True

    def test_list_of_dicts(self):
        d = {
            "configs": [
                {"api_key": "sk-1"},
                {"api_key": "sk-2"},
            ]
        }
        result = sanitise_dict(d)
        assert result["configs"][0]["api_key"] == "[REDACTED]"
        assert result["configs"][1]["api_key"] == "[REDACTED]"

    def test_token_fields_redacted(self):
        d = {"access_token": "jwt-here", "refresh_token": "refresh-here"}
        result = sanitise_dict(d)
        assert result["access_token"] == "[REDACTED]"
        assert result["refresh_token"] == "[REDACTED]"

    def test_password_fields_redacted(self):
        d = {"password": "p@ss", "password_hash": "$2b$12$xxx"}
        result = sanitise_dict(d)
        assert result["password"] == "[REDACTED]"
        assert result["password_hash"] == "[REDACTED]"

    def test_authorization_redacted(self):
        d = {"authorization": "Bearer sk-xxx"}
        result = sanitise_dict(d)
        assert result["authorization"] == "[REDACTED]"

    def test_embedding_api_key_redacted(self):
        d = {"embedding_api_key": "sk-emb-xxx"}
        result = sanitise_dict(d)
        assert result["embedding_api_key"] == "[REDACTED]"

    def test_non_sensitive_fields_preserved(self):
        d = {
            "model_name": "deepseek-v4",
            "display_name": "DeepSeek",
            "is_enabled": True,
            "sort_order": 1,
            "created_at": "2024-01-01",
        }
        result = sanitise_dict(d)
        assert result == d

    def test_none_input(self):
        assert sanitise_dict(None) is None  # type: ignore[arg-type]

    def test_tuple_handled(self):
        d = {"items": ({"api_key": "secret"},)}
        result = sanitise_dict(d)
        assert result["items"][0]["api_key"] == "[REDACTED]"

    def test_case_insensitive_sensitive_fields(self):
        d = {"API_KEY": "secret", "Api_Key": "secret"}
        result = sanitise_dict(d)
        assert result["API_KEY"] == "[REDACTED]"
        assert result["Api_Key"] == "[REDACTED]"

    def test_api_key_encrypted_redacted(self):
        d = {"api_key_encrypted": "enc:v1:gAAAA...", "name": "test"}
        result = sanitise_dict(d)
        assert result["api_key_encrypted"] == "[REDACTED]"
        assert result["name"] == "test"
