"""DocumentIR Validator tests."""
from __future__ import annotations

from app.core.document_ir import (
    BBox,
    LineIR,
    PageIR,
    RegionIR,
    new_document,
    validate_document_ir,
)


class TestValidateDocumentIR:
    """validate_document_ir() integrity checks."""

    def test_valid_empty_document(self):
        doc = new_document()
        violations = validate_document_ir(doc)
        # Empty doc with schema version mismatch may trigger one violation
        # (empty doc is valid otherwise)
        [v for v in violations if "Schema version" in v]
        non_schema = [v for v in violations if "Schema version" not in v]
        assert len(non_schema) == 0

    def test_single_page_no_regions(self):
        doc = new_document()
        page = PageIR(page_id="p1", page_index=0, width=800, height=600)
        doc.pages = [page]
        violations = validate_document_ir(doc)
        schema_violations = [v for v in violations if "Schema version" not in v]
        assert len(schema_violations) == 0

    def test_duplicate_region_id(self):
        doc = new_document()
        region_a = RegionIR(region_id="r1", region_type="text")
        region_b = RegionIR(region_id="r1", region_type="text")
        page = PageIR(page_id="p1", page_index=0, width=800, height=600,
                      regions=[region_a, region_b])
        doc.pages = [page]
        violations = validate_document_ir(doc)
        dup = [v for v in violations if "Duplicate region_id" in v]
        assert len(dup) >= 1

    def test_confidence_out_of_range(self):
        doc = new_document()
        region = RegionIR(region_id="r1", region_type="text", confidence=1.5)
        page = PageIR(page_id="p1", page_index=0, width=800, height=600,
                      regions=[region])
        doc.pages = [page]
        violations = validate_document_ir(doc)
        conf = [v for v in violations if "confidence out of range" in v]
        assert len(conf) >= 1

    def test_negative_bbox_coordinates(self):
        doc = new_document()
        region = RegionIR(
            region_id="r1", region_type="text",
            bbox=BBox(-10, 0, 100, 50),
        )
        page = PageIR(page_id="p1", page_index=0, width=800, height=600,
                      regions=[region])
        doc.pages = [page]
        violations = validate_document_ir(doc)
        neg = [v for v in violations if "starts negative" in v]
        assert len(neg) >= 1

    def test_bbox_exceeds_page(self):
        doc = new_document()
        region = RegionIR(
            region_id="r1", region_type="text",
            bbox=BBox(0, 0, 900, 50),  # wider than page width (800)
        )
        page = PageIR(page_id="p1", page_index=0, width=800, height=600,
                      regions=[region])
        doc.pages = [page]
        violations = validate_document_ir(doc)
        exceed = [v for v in violations if "exceeds page" in v]
        assert len(exceed) >= 1

    def test_reading_order_references_unknown_region(self):
        doc = new_document()
        page = PageIR(
            page_id="p1", page_index=0, width=800, height=600,
            reading_order=["nonexistent_region"],
        )
        doc.pages = [page]
        violations = validate_document_ir(doc)
        ref = [v for v in violations if "reading_order references" in v]
        assert len(ref) >= 1

    def test_zero_area_bbox(self):
        doc = new_document()
        region = RegionIR(
            region_id="r1", region_type="text",
            bbox=BBox(10, 10, 10, 20),  # x0 == x1 → zero width
        )
        page = PageIR(page_id="p1", page_index=0, width=800, height=600,
                      regions=[region])
        doc.pages = [page]
        violations = validate_document_ir(doc)
        zero = [v for v in violations if "zero/negative area" in v]
        assert len(zero) >= 1

    def test_line_confidence_out_of_range(self):
        doc = new_document()
        line = LineIR(line_id="l1", confidence=-0.5)
        region = RegionIR(region_id="r1", region_type="text", lines=[line])
        page = PageIR(page_id="p1", page_index=0, width=800, height=600,
                      regions=[region])
        doc.pages = [page]
        violations = validate_document_ir(doc)
        conf = [v for v in violations if "confidence out of range" in v]
        assert len(conf) >= 1

    def test_multiple_pages_valid(self):
        doc = new_document()
        page1 = PageIR(page_id="p1", page_index=0, width=800, height=600)
        page2 = PageIR(page_id="p2", page_index=1, width=800, height=600)
        doc.pages = [page1, page2]
        violations = validate_document_ir(doc)
        schema_violations = [v for v in violations if "Schema version" not in v]
        assert len(schema_violations) == 0
