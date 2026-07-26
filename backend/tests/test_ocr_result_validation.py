"""OCR result validation tests — no DB/Paddle required."""

from __future__ import annotations

from app.services.ocr_result_validation import (
    validate_ocr_result,
)


def _make_module_result(**overrides) -> dict:
    """Helper to create a valid ModuleResult dict."""
    result = {
        "schema_version": "1.0",
        "data_type": "DocumentIR",
        "data": _make_document_ir(),
        "error": None,
        "warnings": [],
        "latency_ms": 1234,
        "module_name": "PaddleOCRLocalAdapter",
        "module_version": "1.0.0",
        "backend": "paddleocr",
        "component_fingerprint": "comp-v1",
        "model_fingerprint": "ppocr-v4",
        "confidence_scope": 0.95,
        "trace_id": "trace-001",
    }
    result.update(overrides)
    return result


def _make_document_ir(**overrides) -> dict:
    """Helper to create a valid DocumentIR dict."""
    ir = {
        "schema_version": "1.0",
        "document_id": "doc-001",
        "pages": [
            {
                "page_id": "p1",
                "page_width": 1200,
                "page_height": 1600,
                "reading_order": [{"region_id": "r1"}],
                "cross_page_links": [],
                "regions": [
                    {
                        "region_id": "r1",
                        "region_type": "text",
                        "bbox": {"left": 10, "top": 10, "right": 500, "bottom": 100},
                        "lines": [
                            {
                                "line_id": "l1",
                                "text": "Hello world",
                                "bbox": {"left": 10, "top": 10, "right": 200, "bottom": 30},
                            }
                        ],
                    }
                ],
            }
        ],
    }
    ir.update(overrides)
    return ir


class TestOcrResultValidation:
    """Test production-side OCR result validation."""

    def test_valid_result_passes(self):
        result = validate_ocr_result(
            job_document_sha256="a" * 64,
            expected_output_sha256="b" * 64,
            module_result_data=_make_module_result(),
            document_ir_data=None,
        )
        assert result.valid
        assert len(result.errors) == 0

    def test_missing_module_result_fails(self):
        result = validate_ocr_result(
            job_document_sha256="a" * 64,
            expected_output_sha256="b" * 64,
            module_result_data=None,
            document_ir_data=None,
        )
        assert not result.valid
        assert any("ModuleResult data is missing" in e for e in result.errors)

    def test_module_result_with_error_fails(self):
        mr = _make_module_result(error="OCR failed")
        result = validate_ocr_result(
            job_document_sha256="a" * 64,
            expected_output_sha256="b" * 64,
            module_result_data=mr,
            document_ir_data=None,
        )
        assert not result.valid
        assert any("ModuleResult contains error" in e for e in result.errors)

    def test_missing_schema_version_warns(self):
        mr = _make_module_result()
        mr.pop("schema_version", None)
        result = validate_ocr_result(
            job_document_sha256="a" * 64,
            expected_output_sha256="b" * 64,
            module_result_data=mr,
            document_ir_data=None,
        )
        assert not result.valid

    def test_missing_document_ir_data_fails(self):
        mr = _make_module_result()
        mr["data"] = None  # explicitly remove data
        result = validate_ocr_result(
            job_document_sha256="a" * 64,
            expected_output_sha256="b" * 64,
            module_result_data=mr,
            document_ir_data=None,
        )
        assert not result.valid

    def test_empty_pages_fails(self):
        ir = _make_document_ir(pages=[])
        mr = _make_module_result(data=ir)
        result = validate_ocr_result(
            job_document_sha256="a" * 64,
            expected_output_sha256="b" * 64,
            module_result_data=mr,
            document_ir_data=None,
        )
        assert not result.valid

    def test_duplicate_page_id_fails(self):
        ir = _make_document_ir(
            pages=[
                {"page_id": "p1", "page_width": 1200, "page_height": 1600,
                 "reading_order": [], "cross_page_links": [], "regions": []},
                {"page_id": "p1", "page_width": 1200, "page_height": 1600,
                 "reading_order": [], "cross_page_links": [], "regions": []},
            ]
        )
        mr = _make_module_result(data=ir)
        result = validate_ocr_result(
            job_document_sha256="a" * 64,
            expected_output_sha256="b" * 64,
            module_result_data=mr,
            document_ir_data=None,
        )
        assert not result.valid

    def test_duplicate_region_id_fails(self):
        ir = _make_document_ir(
            pages=[
                {
                    "page_id": "p1", "page_width": 1200, "page_height": 1600,
                    "reading_order": [], "cross_page_links": [],
                    "regions": [
                        {"region_id": "r1", "region_type": "text",
                         "bbox": {"left": 0, "top": 0, "right": 100, "bottom": 50},
                         "lines": []},
                        {"region_id": "r1", "region_type": "text",
                         "bbox": {"left": 0, "top": 0, "right": 100, "bottom": 50},
                         "lines": []},
                    ],
                }
            ]
        )
        mr = _make_module_result(data=ir)
        result = validate_ocr_result(
            job_document_sha256="a" * 64,
            expected_output_sha256="b" * 64,
            module_result_data=mr,
            document_ir_data=None,
        )
        assert not result.valid

    def test_bbox_nan_fails(self):
        ir = _make_document_ir(
            pages=[
                {
                    "page_id": "p1", "page_width": 1200, "page_height": 1600,
                    "reading_order": [], "cross_page_links": [],
                    "regions": [
                        {
                            "region_id": "r1", "region_type": "text",
                            "bbox": {"left": float("nan"), "top": 0, "right": 100, "bottom": 50},
                            "lines": [],
                        }
                    ],
                }
            ]
        )
        mr = _make_module_result(data=ir)
        result = validate_ocr_result(
            job_document_sha256="a" * 64,
            expected_output_sha256="b" * 64,
            module_result_data=mr,
            document_ir_data=None,
        )
        assert not result.valid

    def test_bbox_infinity_fails(self):
        ir = _make_document_ir(
            pages=[
                {
                    "page_id": "p1", "page_width": 1200, "page_height": 1600,
                    "reading_order": [], "cross_page_links": [],
                    "regions": [
                        {
                            "region_id": "r1", "region_type": "text",
                            "bbox": {"left": 0, "top": 0, "right": float("inf"), "bottom": 50},
                            "lines": [],
                        }
                    ],
                }
            ]
        )
        mr = _make_module_result(data=ir)
        result = validate_ocr_result(
            job_document_sha256="a" * 64,
            expected_output_sha256="b" * 64,
            module_result_data=mr,
            document_ir_data=None,
        )
        assert not result.valid

    def test_missing_fingerprint_warns(self):
        mr = _make_module_result(model_fingerprint=None, component_fingerprint=None)
        result = validate_ocr_result(
            job_document_sha256="a" * 64,
            expected_output_sha256="b" * 64,
            module_result_data=mr,
            document_ir_data=None,
        )
        assert result.valid  # warnings don't fail
        assert len(result.warnings) >= 2

    def test_reading_order_unknown_region_warns(self):
        ir = _make_document_ir(
            pages=[
                {
                    "page_id": "p1", "page_width": 1200, "page_height": 1600,
                    "reading_order": [{"region_id": "nonexistent"}],
                    "cross_page_links": [],
                    "regions": [
                        {"region_id": "r1", "region_type": "text",
                         "bbox": {"left": 0, "top": 0, "right": 100, "bottom": 50},
                         "lines": []},
                    ],
                }
            ]
        )
        mr = _make_module_result(data=ir)
        result = validate_ocr_result(
            job_document_sha256="a" * 64,
            expected_output_sha256="b" * 64,
            module_result_data=mr,
            document_ir_data=None,
        )
        assert result.valid  # warning only

    def test_document_ir_from_separate_source(self):
        """Test with document_ir_data provided separately from module_result_data."""
        ir = _make_document_ir()
        mr = _make_module_result(data={"some": "metadata"})
        result = validate_ocr_result(
            job_document_sha256="a" * 64,
            expected_output_sha256="b" * 64,
            module_result_data=mr,
            document_ir_data=ir,
        )
        assert result.valid

    def test_validation_error_code_mapping(self):
        result = validate_ocr_result(
            job_document_sha256="a" * 64,
            expected_output_sha256="b" * 64,
            module_result_data=None,
            document_ir_data=None,
        )
        assert result.to_error_code() == "MODULE_RESULT_INVALID"

        result2 = validate_ocr_result(
            job_document_sha256="a" * 64,
            expected_output_sha256="b" * 64,
            module_result_data=_make_module_result(error="boom"),
            document_ir_data=None,
        )
        assert result2.to_error_code() == "MODULE_RESULT_INVALID"
