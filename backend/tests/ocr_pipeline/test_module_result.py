"""ModuleResult tests — construction, validation, serialization, raw sanitization."""
from __future__ import annotations

import pytest

from app.core.document_ir import (
    DocumentIR,
    document_ir_from_dict,
    document_ir_to_dict,
    new_document,
)
from app.core.module_result import (
    AdapterCapabilities,
    ModuleError,
    ModuleResult,
)

# ===========================================================================
# ModuleError
# ===========================================================================


class TestModuleError:
    def test_minimal_error(self):
        err = ModuleError(code="TEST_ERROR", message="Something went wrong")
        assert err.code == "TEST_ERROR"
        assert err.recoverable is False

    def test_error_with_details(self):
        err = ModuleError(code="OCR_TIMEOUT", message="timeout", details={"timeout_s": 30})
        assert err.details is not None

    def test_retryable_timeout(self):
        err = ModuleError(code="OCR_TIMEOUT", message="timeout", category="network", retryable=True)
        assert err.retryable is True
        assert err.category == "network"


# ===========================================================================
# ModuleResult — validation
# ===========================================================================


class TestModuleResultValidation:
    """success()/failure() constructors with invariant enforcement."""

    def test_success_requires_data(self):
        with pytest.raises(ValueError, match="data must be non-None"):
            ModuleResult.success(data=None)  # type: ignore

    def test_failure_requires_error(self):
        with pytest.raises(ValueError, match="error must be non-None"):
            ModuleResult.failure(error=None)  # type: ignore

    def test_success_valid_state(self):
        result = ModuleResult.success(data={"key": "val"}, module_name="test")
        assert result.is_success
        assert not result.is_failure
        assert result.data == {"key": "val"}
        assert result.error is None

    def test_failure_valid_state(self):
        err = ModuleError(code="ERR", message="fail")
        result = ModuleResult.failure(error=err, module_name="test")
        assert result.is_failure
        assert not result.is_success
        assert result.data is None
        assert result.error is not None

    def test_confidence_in_range(self):
        result = ModuleResult.success(data="ok", confidence=0.5)
        assert result.confidence == 0.5

    def test_confidence_out_of_range_raises(self):
        with pytest.raises(ValueError, match="confidence must be in"):
            ModuleResult.success(data="ok", confidence=1.5)

    def test_negative_latency_raises(self):
        with pytest.raises(ValueError, match="latency_ms must be >= 0"):
            ModuleResult(data="ok", latency_ms=-1)

    def test_both_data_and_error_raises(self):
        err = ModuleError(code="ERR", message="fail")
        with pytest.raises(ValueError, match="cannot both be non-None"):
            ModuleResult(data="something", error=err)

    def test_neither_data_nor_error_raises(self):
        with pytest.raises(ValueError, match="either data or error"):
            ModuleResult(data=None, error=None)


# ===========================================================================
# ModuleResult — properties
# ===========================================================================


class TestModuleResultProperties:
    def test_is_success(self):
        result = ModuleResult.success(data="test")
        assert result.is_success

    def test_is_failure(self):
        result = ModuleResult.failure(ModuleError(code="E", message="e"))
        assert result.is_failure

    def test_data_type_inferred(self):
        result = ModuleResult.success(data=42)
        assert result.data_type == "int"


# ===========================================================================
# ModuleResult — raw sanitization
# ===========================================================================


class TestRawSanitization:
    def test_sensitive_fields_redacted(self):
        raw = {"text": "hello", "token": "sk-abc123", "authorization": "Bearer xxx"}
        result = ModuleResult.success(data="ok", raw=raw)
        assert result.raw["token"] == "[REDACTED]"
        assert result.raw["authorization"] == "[REDACTED]"
        assert result.raw["text"] == "hello"

    def test_sensitive_values_redacted(self):
        raw = {"key": "my-api-key-value-here"}
        result = ModuleResult.success(data="ok", raw=raw)
        assert result.raw["key"] == "[REDACTED]"

    def test_raw_truncation(self):
        # Create raw data that exceeds 100KB
        large_raw = {"data": "x" * 200 * 1024}
        result = ModuleResult.success(data="ok", raw=large_raw)
        # Should be truncated
        assert result.raw_truncated is True
        assert result.raw_sha256 is not None
        # Result should still be valid JSON
        assert isinstance(result.raw, dict)

    def test_small_raw_not_truncated(self):
        raw = {"small": "data"}
        result = ModuleResult.success(data="ok", raw=raw)
        assert result.raw_truncated is False
        assert result.raw["small"] == "data"

    def test_raw_none_ok(self):
        result = ModuleResult.success(data="ok", raw=None)
        assert result.raw is None
        assert result.raw_sha256 is None
        assert result.raw_truncated is False

    def test_nested_sensitive_redaction(self):
        raw = {"config": {"api_key": "sk-xxx", "token": "abc"}, "data": [{"credential": "secret"}]}
        result = ModuleResult.success(data="ok", raw=raw)
        assert result.raw["config"]["api_key"] == "[REDACTED]"
        assert result.raw["config"]["token"] == "[REDACTED]"
        assert result.raw["data"][0]["credential"] == "[REDACTED]"


# ===========================================================================
# ModuleResult — codec
# ===========================================================================


class TestModuleResultCodec:
    def test_encode_decode_success_roundtrip(self):
        from app.core.module_result import register_codec

        # Register a simple codec for dict data
        register_codec("dict", encoder=lambda d: d, decoder=lambda d: d)

        original = ModuleResult.success(
            data={"msg": "hello"},
            data_type="dict",
            module_name="test",
            confidence=0.95,
            latency_ms=10.5,
        )
        encoded = original.encode()
        decoded = ModuleResult.decode(encoded)

        assert decoded.is_success
        assert decoded.data == {"msg": "hello"}
        assert decoded.confidence == 0.95
        assert decoded.latency_ms == 10.5
        assert decoded.module_name == "test"

    def test_encode_decode_failure_roundtrip(self):
        err = ModuleError(code="ERR", message="fail", category="system")
        original = ModuleResult.failure(error=err, module_name="test", latency_ms=5.0)

        encoded = original.encode()
        decoded = ModuleResult.decode(encoded)

        assert decoded.is_failure
        assert decoded.error is not None
        assert decoded.error.code == "ERR"
        assert decoded.latency_ms == 5.0

    def test_encode_decode_document_ir(self):
        """Full roundtrip with DocumentIR typed data."""

        doc = new_document()
        from app.core.document_ir import register_codec
        try:
            register_codec("DocumentIR", encoder=document_ir_to_dict, decoder=document_ir_from_dict)
        except Exception:
            pass  # already registered

        result = ModuleResult.success(
            data=doc,
            data_type="DocumentIR",
            data_schema_version=doc.schema_version,
            module_name="test",
        )
        encoded = result.encode()
        decoded = ModuleResult.decode(encoded)

        assert decoded.is_success
        assert decoded.data_type == "DocumentIR"
        assert isinstance(decoded.data, DocumentIR)

    def test_encode_preserves_warnings(self):
        result = ModuleResult.success(data="ok", warnings=["warning 1", "warning 2"])
        encoded = result.encode()
        decoded = ModuleResult.decode(encoded)
        assert decoded.warnings == ["warning 1", "warning 2"]


# ===========================================================================
# AdapterCapabilities
# ===========================================================================


class TestAdapterCapabilities:
    def test_minimal_defaults(self):
        cap = AdapterCapabilities(backend="test", adapter_type="ocr")
        assert cap.backend == "test"
        assert cap.adapter_type == "ocr"
        assert cap.text is False
        assert cap.offline is False
        assert isinstance(cap.layout_labels, tuple)
        assert isinstance(cap.supported_mime_types, tuple)

    def test_full_spec(self):
        cap = AdapterCapabilities(
            backend="paddleocr-vl",
            adapter_type="ocr",
            text=True,
            bbox=True,
            layout=True,
            layout_labels=("text", "code", "formula"),
            region_types=("text", "code", "formula"),
            supported_devices=("cpu", "cuda"),
            multipage=False,
            requires_network=True,
        )
        assert cap.backend == "paddleocr-vl"
        assert cap.text is True
        assert "formula" in cap.layout_labels
        assert "cuda" in cap.supported_devices

    def test_frozen_prevents_mutation(self):
        cap = AdapterCapabilities(backend="test", adapter_type="ocr")
        with pytest.raises(Exception):
            cap.backend = "changed"  # type: ignore

    def test_tuple_immutability(self):
        cap = AdapterCapabilities(
            backend="test", adapter_type="ocr", layout_labels=("a", "b"),
        )
        with pytest.raises(Exception):
            cap.layout_labels += ("c",)  # type: ignore
