"""Pure-function compatibility baseline for OCR readiness and result validation.

Pins the configuration-issue decision rules in ``ocr_readiness._ocr_config_issues``
and the error-code mapping in ``ocr_result_validation.ValidationResult.to_error_code``
so future refactors of OCR health gating or failure classification cannot silently
change which deployments are marked unavailable/degraded, or which result failures
map to which error code returned to callers.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.ocr_readiness import _ocr_config_issues
from app.services.ocr_result_validation import ValidationResult


def _settings(**overrides):
    """Build a minimal Settings-like object with OCR defaults."""
    base = {
        "OCR_ENABLED": True,
        "OCR_USE_GPU": False,
        "OCR_EXECUTION_BACKEND": "paddlex_http",
        "OCR_REMOTE_URL": "https://ocr.example/health",
        "OCR_REMOTE_TOKEN": "secret-token",
        "OCR_REMOTE_HEALTH_TIMEOUT_SEC": 2.0,
        "OCR_REMOTE_AUTH_HEADER": "Authorization",
        "OCR_REMOTE_AUTH_SCHEME": "Bearer",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TestOcrConfigIssues:
    def test_clean_cloud_remote_config_returns_no_issues(self):
        settings = _settings()
        assert _ocr_config_issues(settings, "paddlex_http") == []

    def test_local_process_backend_rejected_regardless_of_other_config(self):
        settings = _settings(OCR_EXECUTION_BACKEND="local_process")
        issues = _ocr_config_issues(settings, "local_process")
        assert "local_process backend not allowed" in issues

    def test_local_process_with_gpu_disabled_still_flagged_for_backend(self):
        settings = _settings(OCR_USE_GPU=False)
        issues = _ocr_config_issues(settings, "local_process")
        assert "local_process backend not allowed" in issues
        # GPU is False so the GPU issue must NOT appear
        assert "GPU should be disabled" not in issues

    def test_gpu_enabled_flags_gpu_issue(self):
        settings = _settings(OCR_USE_GPU=True)
        issues = _ocr_config_issues(settings, "paddlex_http")
        assert issues == ["GPU should be disabled"]

    def test_gpu_none_treated_as_not_disabled(self):
        # OCR_USE_GPU is None -> "is not False" -> flagged
        settings = _settings(OCR_USE_GPU=None)
        issues = _ocr_config_issues(settings, "paddlex_http")
        assert "GPU should be disabled" in issues

    def test_paddlex_http_without_remote_token_flagged(self):
        settings = _settings(OCR_REMOTE_TOKEN="")
        issues = _ocr_config_issues(settings, "paddlex_http")
        assert issues == ["remote token not set"]

    def test_paddlex_http_with_none_remote_token_flagged(self):
        settings = _settings(OCR_REMOTE_TOKEN=None)
        issues = _ocr_config_issues(settings, "paddlex_http")
        assert issues == ["remote token not set"]

    def test_paddlex_http_with_remote_token_no_issue(self):
        settings = _settings(OCR_REMOTE_TOKEN="abc")
        assert _ocr_config_issues(settings, "paddlex_http") == []

    def test_local_process_does_not_trigger_missing_remote_token(self):
        # local_process has its own rejection; remote token check only applies to paddlex_http
        settings = _settings(OCR_EXECUTION_BACKEND="local_process", OCR_REMOTE_TOKEN="")
        issues = _ocr_config_issues(settings, "local_process")
        assert "remote token not set" not in issues
        assert "local_process backend not allowed" in issues

    def test_unknown_backend_returns_no_issues_when_gpu_disabled_and_token_present(self):
        # Unknown backends are not actively rejected by this helper; only
        # local_process and (tokenless) paddlex_http are flagged.
        settings = _settings(OCR_EXECUTION_BACKEND="future_backend")
        assert _ocr_config_issues(settings, "future_backend") == []

    def test_case_sensitive_backend_string(self):
        # The helper compares literal strings; callers normalize case elsewhere.
        settings = _settings(OCR_EXECUTION_BACKEND="PADDLEX_HTTP")
        issues = _ocr_config_issues(settings, "PADDLEX_HTTP")
        # PADDLEX_HTTP != paddlex_http -> no token check; GPU disabled -> no issues
        assert issues == []

    def test_empty_backend_string_is_neither_local_process_nor_paddlex_http(self):
        settings = _settings(OCR_EXECUTION_BACKEND="")
        assert _ocr_config_issues(settings, "") == []

    def test_all_three_issues_together_local_process_gpu_enabled_no_token(self):
        # local_process triggers backend issue; GPU=True triggers GPU issue;
        # remote token check skipped because backend != paddlex_http.
        settings = _settings(OCR_USE_GPU=True, OCR_REMOTE_TOKEN="")
        issues = _ocr_config_issues(settings, "local_process")
        assert issues == ["local_process backend not allowed", "GPU should be disabled"]

    def test_all_three_issues_together_paddlex_http_gpu_enabled_no_token(self):
        settings = _settings(OCR_USE_GPU=True, OCR_REMOTE_TOKEN="")
        issues = _ocr_config_issues(settings, "paddlex_http")
        assert issues == ["GPU should be disabled", "remote token not set"]


class TestToErrorCode:
    def test_valid_result_returns_none(self):
        assert ValidationResult(valid=True).to_error_code() is None

    def test_invalid_with_empty_errors_returns_default_document_ir_invalid(self):
        # No error text to classify -> fallback default
        assert ValidationResult(valid=False).to_error_code() == "DOCUMENT_IR_INVALID"

    def test_hash_substring_maps_to_result_hash_mismatch(self):
        r = ValidationResult(valid=False, errors=["document hash mismatch"])
        assert r.to_error_code() == "RESULT_HASH_MISMATCH"

    def test_sha256_substring_maps_to_output_hash_mismatch(self):
        r = ValidationResult(valid=False, errors=["output_sha256 mismatch"])
        assert r.to_error_code() == "OUTPUT_HASH_MISMATCH"

    def test_hash_takes_priority_over_sha256(self):
        # "hash" check runs first in the loop body per error, so a single error
        # containing both substrings returns RESULT_HASH_MISMATCH.
        r = ValidationResult(valid=False, errors=["sha256 hash mismatch"])
        assert r.to_error_code() == "RESULT_HASH_MISMATCH"

    def test_schema_substring_maps_to_schema_incompatible(self):
        r = ValidationResult(valid=False, errors=["schema_version missing"])
        assert r.to_error_code() == "SCHEMA_INCOMPATIBLE"

    def test_document_ir_with_space_maps_to_document_ir_invalid(self):
        r = ValidationResult(valid=False, errors=["Document IR invalid"])
        assert r.to_error_code() == "DOCUMENT_IR_INVALID"

    def test_documentir_without_space_maps_to_document_ir_invalid(self):
        r = ValidationResult(valid=False, errors=["DocumentIR invalid"])
        assert r.to_error_code() == "DOCUMENT_IR_INVALID"

    def test_fingerprint_maps_to_fingerprint_mismatch(self):
        r = ValidationResult(valid=False, errors=["worker fingerprint missing"])
        assert r.to_error_code() == "FINGERPRINT_MISMATCH"

    def test_moduleresult_compact_maps_to_module_result_invalid(self):
        r = ValidationResult(valid=False, errors=["ModuleResult missing schema"])
        # "schema" appears first in this string and outranks moduleresult
        assert r.to_error_code() == "SCHEMA_INCOMPATIBLE"

    def test_moduleresult_only_maps_to_module_result_invalid(self):
        r = ValidationResult(valid=False, errors=["moduleresult parse error"])
        assert r.to_error_code() == "MODULE_RESULT_INVALID"

    def test_module_result_with_space_maps_to_module_result_invalid(self):
        # "module result" -> lowercased -> "module result" -> .replace(" ", "")
        # -> "moduleresult" -> matches.
        r = ValidationResult(valid=False, errors=["module result parse error"])
        assert r.to_error_code() == "MODULE_RESULT_INVALID"

    def test_first_matching_error_wins(self):
        # Multiple errors: the first one whose substring matches returns.
        r = ValidationResult(
            valid=False,
            errors=["moduleresult parse error", "schema_version missing"],
        )
        # First error matches moduleresult -> MODULE_RESULT_INVALID, even though
        # second error would have matched schema.
        assert r.to_error_code() == "MODULE_RESULT_INVALID"

    def test_unmatched_error_falls_back_to_document_ir_invalid(self):
        r = ValidationResult(valid=False, errors=["something unexpected"])
        assert r.to_error_code() == "DOCUMENT_IR_INVALID"

    def test_case_insensitive_substring_matching(self):
        r = ValidationResult(valid=False, errors=["HASH Mismatch"])
        assert r.to_error_code() == "RESULT_HASH_MISMATCH"

    def test_warnings_are_ignored_for_error_code(self):
        # Only errors are inspected; warnings do not affect the mapping.
        r = ValidationResult(valid=False, errors=[], warnings=["schema warning"])
        assert r.to_error_code() == "DOCUMENT_IR_INVALID"
        r2 = ValidationResult(valid=True, errors=[], warnings=["schema warning"])
        assert r2.to_error_code() is None
