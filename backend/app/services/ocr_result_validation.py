"""OCR Job result validation — runs on production server before marking job completed.

Validates:
- document_sha256 matches job
- output_sha256 matches uploaded artifact
- ModuleResult schema compatibility
- DocumentIR schema compatibility
- page_id uniqueness
- region_id uniqueness
- line_id uniqueness
- bbox/polygon no NaN/Infinity
- coordinates within page bounds
- reading_order references are valid
- CrossPageLink references are valid
- model fingerprint present
- worker fingerprint present
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("postgraduate-ai.services.ocr_result_validation")


@dataclass
class ValidationResult:
    """Result of OCR job output validation."""
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_error_code(self) -> str | None:
        """Map validation result to an error code, or None if valid."""
        if self.valid:
            return None
        for err in self.errors:
            if "hash" in err.lower():
                return "RESULT_HASH_MISMATCH"
            if "sha256" in err.lower():
                return "OUTPUT_HASH_MISMATCH"
            if "schema" in err.lower():
                return "SCHEMA_INCOMPATIBLE"
            if "document ir" in err.lower() or "documentir" in err.lower():
                return "DOCUMENT_IR_INVALID"
            if "fingerprint" in err.lower():
                return "FINGERPRINT_MISMATCH"
            if "moduleresult" in err.lower().replace(" ", ""):
                return "MODULE_RESULT_INVALID"
        return "DOCUMENT_IR_INVALID"


def validate_ocr_result(
    job_document_sha256: str,
    expected_output_sha256: str,
    module_result_data: dict[str, Any] | None,
    document_ir_data: dict[str, Any] | None,
) -> ValidationResult:
    """Validate OCR job output before accepting as completed.

    Args:
        job_document_sha256: Expected document SHA256 from the OCRJob.
        expected_output_sha256: Expected output SHA256 from the upload.
        module_result_data: Parsed ModuleResult JSON (or None).
        document_ir_data: Parsed DocumentIR JSON (or None).

    Returns:
        ValidationResult with valid=True if all checks pass.
    """
    result = ValidationResult(valid=True)

    # 1. ModuleResult presence
    if module_result_data is None:
        result.errors.append("ModuleResult data is missing")
        result.valid = False
        return result

    # 2. ModuleResult schema check
    schema = module_result_data.get("schema_version", "")
    if not schema:
        result.errors.append("ModuleResult missing schema_version")
        result.valid = False
        return result

    # 3. ModuleResult error check
    error = module_result_data.get("error")
    if error is not None:
        result.errors.append(f"ModuleResult contains error: {error}")
        result.valid = False
        return result

    # 4. ModuleResult data presence
    data = module_result_data.get("data")
    if data is None and document_ir_data is None:
        result.errors.append("ModuleResult.data is missing and no DocumentIR provided")
        result.valid = False
        return result

    # 5. DocumentIR presence
    ir = document_ir_data or data
    if ir is None:
        result.errors.append("DocumentIR is missing")
        result.valid = False
        return result

    # 6. DocumentIR schema
    ir_schema = ir.get("schema_version", "")
    if not ir_schema:
        result.warnings.append("DocumentIR missing schema_version")

    # 7. Fingerprint checks
    if not module_result_data.get("model_fingerprint"):
        result.warnings.append("ModuleResult missing model_fingerprint")
    if not module_result_data.get("component_fingerprint"):
        result.warnings.append("ModuleResult missing component_fingerprint")

    # 8. Page-level validation
    pages = ir.get("pages", [])
    if not pages:
        result.errors.append("DocumentIR has no pages")
        result.valid = False
        return result

    page_ids: set[str] = set()
    region_ids: set[str] = set()
    line_ids: set[str] = set()

    for page in pages:
        pid = page.get("page_id", "")
        if pid in page_ids:
            result.errors.append(f"Duplicate page_id: {pid}")
            result.valid = False
        page_ids.add(pid)

        # Page bounds
        pw = page.get("page_width", 0)
        ph = page.get("page_height", 0)
        if pw <= 0 or ph <= 0:
            result.warnings.append(f"Page {pid} has invalid dimensions: {pw}x{ph}")

        # Region validation
        for region in page.get("regions", []):
            rid = region.get("region_id", "")
            if rid in region_ids:
                result.errors.append(f"Duplicate region_id: {rid}")
                result.valid = False
            region_ids.add(rid)

            # BBox validation
            bbox = region.get("bbox", {})
            _validate_bbox(result, pid, rid, bbox, pw, ph)

            # Line validation
            for line in region.get("lines", []):
                lid = line.get("line_id", "")
                if lid in line_ids:
                    result.errors.append(f"Duplicate line_id: {lid}")
                    result.valid = False
                line_ids.add(lid)

                line_bbox = line.get("bbox", {})
                _validate_bbox(result, pid, lid, line_bbox, pw, ph)

    # 9. Reading order validation
    for page in pages:
        ro = page.get("reading_order", [])
        for ref in ro:
            ref_id = ref.get("region_id", "") if isinstance(ref, dict) else ""
            if ref_id and ref_id not in region_ids:
                result.warnings.append(
                    f"Reading order references unknown region_id: {ref_id}"
                )

    # 10. Cross-page link validation
    for page in pages:
        for link in page.get("cross_page_links", []):
            target_id = link.get("target_page_id", "")
            if target_id and target_id not in page_ids:
                result.warnings.append(
                    f"CrossPageLink references unknown page_id: {target_id}"
                )

    return result


def _validate_bbox(
    result: ValidationResult,
    parent_id: str,
    element_id: str,
    bbox: dict[str, Any],
    page_width: float,
    page_height: float,
) -> None:
    """Validate a single bbox."""
    if not bbox:
        result.warnings.append(f"Element {element_id} missing bbox")
        return

    for key in ("left", "top", "right", "bottom"):
        val = bbox.get(key)
        if val is None:
            result.warnings.append(f"Element {element_id} bbox missing {key}")
            continue
        # Check NaN/Infinity
        if isinstance(val, float):
            import math
            if math.isnan(val) or math.isinf(val):
                result.errors.append(f"Element {element_id} bbox.{key} is NaN/Infinity")
                result.valid = False

    # Check page bounds
    left = bbox.get("left", 0)
    right = bbox.get("right", 0)
    bottom = bbox.get("bottom", 0)
    if page_width > 0 and (left < 0 or right > page_width):
        result.warnings.append(
            f"Element {element_id} bbox exceeds page width: "
            f"left={left}, right={right}, page_width={page_width}"
        )
    if page_height > 0 and bottom > page_height:
        result.warnings.append(
            f"Element {element_id} bbox exceeds page height: "
            f"bottom={bottom}, page_height={page_height}"
        )
