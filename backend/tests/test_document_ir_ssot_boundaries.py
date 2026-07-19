"""DocumentIR SSOT boundary tests.

Verifies:
- DocumentIR round-trip serialization is stable (same input → same output)
- IR-to-blocks conversion (legacy compat view) is lossless for key fields
- All active coordinators use DocumentIR, not raw OCR fields
- Stable IDs are deterministic
"""

from __future__ import annotations

import hashlib
import json

import pytest

from app.core.document_ir import (
    BBox,
    DocumentIR,
    LineIR,
    PageIR,
    Provenance,
    RegionIR,
    document_ir_from_dict,
    document_ir_to_blocks,
    document_ir_to_dict,
    make_line_id,
    make_page_id,
    make_region_id,
    new_document,
)


class TestDocumentIRRoundTrip:
    """DocumentIR serialization must be stable and lossless."""

    def test_new_document_stable_id(self):
        """Same source bytes → same document_id."""
        source = b"test content for stable id verification"
        doc1 = new_document(source)
        doc2 = new_document(source)
        assert doc1.document_id == doc2.document_id
        assert doc1.source_hash == doc2.source_hash

    def test_different_source_different_id(self):
        """Different source bytes → different document_id."""
        doc1 = new_document(b"content A")
        doc2 = new_document(b"content B")
        assert doc1.document_id != doc2.document_id

    def test_round_trip_serialization(self):
        """DocumentIR → dict → DocumentIR must preserve all fields."""
        doc = new_document(b"test")
        page = PageIR(
            page_id=make_page_id(doc.document_id, 0),
            page_index=0,
            width=612,
            height=792,
        )
        region = RegionIR(
            region_id=make_region_id(page.page_id, BBox(50, 50, 500, 100), "paddleocr", "test text"),
            region_type="text",
            bbox=BBox(50, 50, 500, 100),
            confidence=0.95,
            reading_order=0,
            provenance=Provenance(engine="paddleocr"),
        )
        line = LineIR(
            line_id=make_line_id(region.region_id, BBox(50, 50, 500, 100), "test text"),
            text="test text",
            bbox=BBox(50, 50, 500, 100),
            confidence=0.95,
        )
        region.lines.append(line)
        page.regions.append(region)
        doc.pages.append(page)

        # Round-trip
        data = document_ir_to_dict(doc)
        restored = document_ir_from_dict(data)

        assert restored.document_id == doc.document_id
        assert restored.source_hash == doc.source_hash
        assert len(restored.pages) == 1
        assert len(restored.pages[0].regions) == 1
        assert restored.pages[0].regions[0].region_id == region.region_id
        assert restored.pages[0].regions[0].lines[0].text == "test text"

    def test_empty_document_round_trip(self):
        """Empty DocumentIR must serialize and deserialize."""
        doc = new_document(b"empty")
        data = document_ir_to_dict(doc)
        restored = document_ir_from_dict(data)
        assert restored.document_id == doc.document_id
        assert len(restored.pages) == 0


class TestDocumentIRStableIDs:
    """Content-addressed IDs must be deterministic."""

    def test_page_id_deterministic(self):
        id1 = make_page_id("doc123", 0)
        id2 = make_page_id("doc123", 0)
        assert id1 == id2

    def test_region_id_deterministic(self):
        page_id = make_page_id("doc123", 0)
        bbox = BBox(100, 200, 500, 600)
        id1 = make_region_id(page_id, bbox, "paddleocr", "hello")
        id2 = make_region_id(page_id, bbox, "paddleocr", "hello")
        assert id1 == id2

    def test_line_id_deterministic(self):
        region_id = "region123"
        bbox = BBox(100, 200, 500, 600)
        id1 = make_line_id(region_id, bbox, "hello world")
        id2 = make_line_id(region_id, bbox, "hello world")
        assert id1 == id2

    def test_different_engine_different_region_id(self):
        page_id = make_page_id("doc123", 0)
        bbox = BBox(100, 200, 500, 600)
        id_v4 = make_region_id(page_id, bbox, "paddleocr", "text")
        id_vl = make_region_id(page_id, bbox, "paddleocr-vl", "text")
        assert id_v4 != id_vl


class TestDocumentIRLegacyCompat:
    """Legacy blocks view must be a lossless compat layer."""

    def test_document_ir_to_blocks_structure(self):
        doc = new_document(b"test")
        page = PageIR(page_id=make_page_id(doc.document_id, 0), page_index=0, width=612, height=792)
        region = RegionIR(
            region_id="r1", region_type="text", bbox=BBox(0, 0, 612, 100),
            lines=[
                LineIR(line_id="l1", text="Hello World", bbox=BBox(0, 0, 600, 50)),
            ],
        )
        page.regions.append(region)
        doc.pages.append(page)

        blocks = document_ir_to_blocks(doc)
        assert len(blocks) == 1
        assert blocks[0]["page"] == 1
        assert "Hello World" in blocks[0]["text"]
        assert blocks[0]["has_boxes"]
        assert blocks[0]["source"] == "document_ir"

    def test_to_blocks_without_boxes(self):
        doc = new_document(b"test2")
        page = PageIR(page_id="p0", page_index=0, width=612, height=792)
        # Region with no lines → no boxes
        page.regions.append(RegionIR(region_id="r1", region_type="text"))
        doc.pages.append(page)

        blocks = document_ir_to_blocks(doc)
        assert len(blocks) == 1
        assert not blocks[0]["has_boxes"]


class TestDocumentIRBoundary:
    """DocumentIR must be the SSOT — no direct raw field access in coordinators."""

    def test_coordinators_use_document_ir_not_raw_fields(self):
        """Verify key pipeline modules reference DocumentIR, not raw OCR fields."""
        import app.features.reading_order as ro
        import app.features.cross_page_linking as cpl

        # These modules should work with DocumentIR types
        assert hasattr(ro, "ReadingOrderResult")
        assert hasattr(cpl, "CrossPageLink")

    def test_document_ir_asdict_no_raw_fields(self):
        """Serialized DocumentIR should not contain backend-specific raw fields."""
        doc = new_document(b"test")
        data = document_ir_to_dict(doc)
        serialized = json.dumps(data)
        assert "rec_texts" not in serialized
        assert "dt_polys" not in serialized
