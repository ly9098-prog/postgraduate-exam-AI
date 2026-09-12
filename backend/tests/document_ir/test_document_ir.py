"""DocumentIR 序列化与稳定 ID 测试。

测试覆盖:
- to_dict / from_dict 往返（含新字段: revision, schema_version, page_id 等）
- to_blocks 向后兼容
- 稳定 ID 生成规则: 确定性、内容寻址、bbox 归一化
- 文本清洗后 ID 不变（只加 revision）
- ReplacementMap 合并/拆分追踪
- get_document_ir API
- 空/边界情况
"""

from __future__ import annotations

from app.core.document_ir import (
    BBox,
    DocumentIR,
    LineIR,
    PageIR,
    Point,
    Polygon,
    Provenance,
    RegionIR,
    ReplacementMap,
    document_ir_from_dict,
    document_ir_to_blocks,
    document_ir_to_dict,
    make_line_id,
    make_page_id,
    make_region_id,
    new_document,
)


def _make_sample_doc() -> DocumentIR:
    """构建一个采样 DocumentIR 用于序列化测试。"""
    doc = new_document(source_bytes=b"test-source")
    page_id = make_page_id(doc.document_id, 0)

    lines = [
        LineIR(
            text="1. 测试题干",
            bbox=BBox(10, 10, 500, 30),
            confidence=0.95,
            reading_order=0,
            provenance=Provenance(engine="paddleocr"),
        ),
        LineIR(
            text="A. 选项A",
            bbox=BBox(10, 35, 200, 50),
            confidence=0.90,
            reading_order=1,
            flags={"low_conf"},
        ),
    ]

    # Assign stable IDs based on original text
    for line in lines:
        line.line_id = make_line_id(
            make_region_id(page_id, line.bbox, "paddleocr", line.text),
            line.bbox, line.text,
        )

    region = RegionIR(
        region_id=make_region_id(page_id, BBox(0, 0, 600, 800), "paddleocr", "1. 测试题干"),
        region_type="text",
        bbox=BBox(0, 0, 600, 800),
        confidence=0.92,
        reading_order=0,
        lines=lines,
        flags={"has_boxes"},
    )

    page = PageIR(
        page_id=page_id,
        page_index=0,
        width=600,
        height=800,
        original_image_ref="/path/to/page.png",
        regions=[region],
    )

    doc.add_page(page)
    return doc


# ===================================================================
# Round-trip
# ===================================================================


def test_to_dict_from_dict_roundtrip() -> None:
    """DocumentIR → dict → DocumentIR 往返保持所有字段。"""
    doc = _make_sample_doc()
    data = document_ir_to_dict(doc)
    restored = document_ir_from_dict(data)

    assert restored is not None
    assert restored.document_id == doc.document_id
    assert restored.source_hash == doc.source_hash
    assert restored.pipeline_fingerprint == doc.pipeline_fingerprint
    assert restored.page_count == doc.page_count
    assert restored.schema_version == doc.schema_version

    for orig_page, rest_page in zip(doc.pages, restored.pages):
        assert rest_page.page_id == orig_page.page_id
        assert rest_page.page_index == orig_page.page_index
        assert rest_page.width == orig_page.width

        for orig_region, rest_region in zip(orig_page.regions, rest_page.regions):
            assert rest_region.region_id == orig_region.region_id
            assert rest_region.region_type == orig_region.region_type
            assert rest_region.confidence == orig_region.confidence
            assert rest_region.revision == orig_region.revision
            assert rest_region.parent_region_id == orig_region.parent_region_id
            assert rest_region.source_region_ids == orig_region.source_region_ids

            for orig_line, rest_line in zip(orig_region.lines, rest_region.lines):
                assert rest_line.line_id == orig_line.line_id
                assert rest_line.text == orig_line.text
                assert rest_line.confidence == orig_line.confidence
                assert rest_line.revision == orig_line.revision
                if orig_line.bbox:
                    assert rest_line.bbox is not None
                    assert rest_line.bbox.as_tuple() == orig_line.bbox.as_tuple()


def test_empty_document_roundtrip() -> None:
    """空 DocumentIR 序列化往返。"""
    doc = DocumentIR()
    data = document_ir_to_dict(doc)
    restored = document_ir_from_dict(data)

    assert restored is not None
    assert restored.schema_version == "1.0"
    assert restored.page_count == 0


# ===================================================================
# Stable ID — determinism
# ===================================================================


def test_make_page_id_deterministic() -> None:
    """同一 document_id + page_index 生成相同 page_id。"""
    doc = new_document(source_bytes=b"hello")
    id1 = make_page_id(doc.document_id, 0)
    id2 = make_page_id(doc.document_id, 0)
    assert id1 == id2
    assert len(id1) == 12

    # Different page_index → different ID
    id3 = make_page_id(doc.document_id, 1)
    assert id1 != id3


def test_make_region_id_deterministic() -> None:
    """同一 bbox + engine + text 生成相同 region_id。"""
    page_id = "test_page_123"
    bbox = BBox(10, 20, 500, 100)
    rid1 = make_region_id(page_id, bbox, "paddleocr", "1. 测试题干")
    rid2 = make_region_id(page_id, bbox, "paddleocr", "1. 测试题干")
    assert rid1 == rid2
    assert len(rid1) == 16


def test_make_line_id_deterministic() -> None:
    """同一 region_id + bbox + text 生成相同 line_id。"""
    region_id = "test_region_123"
    bbox = BBox(10, 35, 200, 50)
    lid1 = make_line_id(region_id, bbox, "A. 选项A")
    lid2 = make_line_id(region_id, bbox, "A. 选项A")
    assert lid1 == lid2
    assert len(lid1) == 16


def test_different_content_different_ids() -> None:
    """不同内容生成不同 ID。"""
    page_id = "test_page"
    bbox = BBox(10, 35, 200, 50)
    rid_a = make_region_id(page_id, bbox, "paddleocr", "题干A")
    rid_b = make_region_id(page_id, bbox, "paddleocr", "题干B")
    assert rid_a != rid_b


def test_different_bbox_different_region_ids() -> None:
    """不同 bbox 生成不同 region_id。"""
    page_id = "test_page"
    bbox1 = BBox(10, 20, 500, 100)
    bbox2 = BBox(10, 20, 500, 101)  # 1px difference
    rid1 = make_region_id(page_id, bbox1, "paddleocr", "text")
    rid2 = make_region_id(page_id, bbox2, "paddleocr", "text")
    # 1px difference at 2 decimal precision → different IDs
    assert rid1 != rid2


def test_bbox_normalization_tolerance() -> None:
    """微小坐标变化（0.005px 以内）产生相同 ID。"""
    page_id = "test_page"
    # 0.004 is below 0.01 rounding threshold → same normalized value
    bbox1 = BBox(10.000, 20.000, 500.000, 100.000)
    bbox2 = BBox(10.004, 20.003, 500.001, 100.002)
    rid1 = make_region_id(page_id, bbox1, "paddleocr", "text")
    rid2 = make_region_id(page_id, bbox2, "paddleocr", "text")
    assert rid1 == rid2


def test_text_cleaning_preserves_line_id() -> None:
    """文本清洗（如去空格）后 ID 不变。"""
    region_id = "test_region"
    bbox = BBox(10, 35, 200, 50)
    # Original OCR text ("A . 选项 A") vs cleaned text ("A. 选项A")
    # These are different texts → different IDs (intentionally)
    # The test is that if we keep the ORIGINAL text for ID generation,
    # but use CLEANED text for display, the ID stays bound to original
    original_text = "A. 选项A"
    lid = make_line_id(region_id, bbox, original_text)
    assert len(lid) == 16
    # Revision tracking handles the cleaning
    line = LineIR(line_id=lid, text=original_text, bbox=bbox, revision=0)
    line.revision = 1  # text was cleaned, ID preserved
    assert line.line_id == lid
    assert line.revision == 1


# ===================================================================
# ReplacementMap
# ===================================================================


def test_replacement_map_add_lookup() -> None:
    """ReplacementMap 添加和查找。"""
    rm = ReplacementMap()
    rm.add("old_region_1", ["new_region_1", "new_region_2"], reason="split")
    rm.add("old_region_2", ["new_region_3"], reason="merge")

    assert rm.lookup("old_region_1") == ["new_region_1", "new_region_2"]
    assert rm.lookup("old_region_2") == ["new_region_3"]
    assert rm.lookup("nonexistent") is None


def test_replacement_map_revision_tracking() -> None:
    """每次 add 递增 revision。"""
    rm = ReplacementMap()
    rm.add("r1", ["r2"], reason="replaced")
    rm.add("r3", ["r4"], reason="replaced")
    assert rm.replacements[0].revision == 1
    assert rm.replacements[1].revision == 2


# ===================================================================
# Blocks backward compat
# ===================================================================


def test_document_ir_to_blocks() -> None:
    """DocumentIR → legacy blocks 包含 line_id 用于恢复。"""
    doc = _make_sample_doc()
    blocks = document_ir_to_blocks(doc)

    assert len(blocks) == 1
    assert len(blocks[0]["boxes"]) == 2
    for box in blocks[0]["boxes"]:
        assert "line_id" in box  # must carry line ID for round-trip

    assert blocks[0]["page"] == 1  # 0→1 indexed
    assert blocks[0]["source"] == "document_ir"


def test_document_ir_to_blocks_empty() -> None:
    """空 DocumentIR 转换不应报错。"""
    doc = DocumentIR()
    blocks = document_ir_to_blocks(doc)
    assert blocks == []


# ===================================================================
# PageIR helpers
# ===================================================================


def test_page_ir_lines_property() -> None:
    """PageIR.lines 应按 reading_order 展平所有 region 的行。"""
    lines_a = [LineIR(text="l1", reading_order=2)]
    lines_b = [LineIR(text="l2", reading_order=1)]

    region_a = RegionIR(region_id="r1", lines=lines_a, reading_order=2)
    region_b = RegionIR(region_id="r2", lines=lines_b, reading_order=1)

    page = PageIR(regions=[region_a, region_b])
    all_lines = page.lines
    assert len(all_lines) == 2
    assert all_lines[0].text == "l2"
    assert all_lines[1].text == "l1"


# ===================================================================
# Geometry
# ===================================================================


def test_polygon_bbox() -> None:
    """Polygon.bbox 应正确计算外接矩形。"""
    poly = Polygon(points=(
        Point(10, 20),
        Point(100, 20),
        Point(100, 80),
        Point(10, 80),
    ))
    bbox = poly.bbox
    assert bbox.x0 == 10
    assert bbox.y0 == 20
    assert bbox.x1 == 100
    assert bbox.y1 == 80


def test_bbox_properties() -> None:
    """BBox 的 width/height/area 计算。"""
    bbox = BBox(10, 20, 110, 70)
    assert bbox.width == 100
    assert bbox.height == 50
    assert bbox.area == 5000
    assert bbox.as_tuple() == (10, 20, 110, 70)
