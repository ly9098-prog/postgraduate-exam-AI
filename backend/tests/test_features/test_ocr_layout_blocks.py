"""Compatibility contract for image OCR layout blocks."""

from __future__ import annotations

from app.features.ocr_layout_blocks import build_pre_extracted_ocr_blocks


PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000d4944415478da63fcffff3f0300050201f4a2f2e"
    "70000000049454e44ae426082"
)


def test_line_geometry_becomes_ordered_blocks():
    result = {
        "engine_fingerprint": "fingerprint",
        "lines": [
            {"text": "01. 题干", "bbox": [1, 2, 3, 4], "confidence": 0.9},
            {"text": "", "bbox": [5, 6, 7, 8]},
            {"text": "A. 选项", "conf": 0.7},
            "invalid",
        ],
    }

    blocks = build_pre_extracted_ocr_blocks(
        image_bytes=PNG_1X1,
        cleaned_text="unused",
        ocr_result=result,
    )

    assert [block["block_index"] for block in blocks] == [0, 2]
    assert blocks[0]["text"] == "01. 题干"
    assert blocks[0]["boxes"] == [
        {"bbox": [1, 2, 3, 4], "conf": 0.9, "text": "01. 题干"}
    ]
    assert blocks[0] | {"has_boxes": True} == {
        **blocks[0],
        "has_boxes": True,
        "page": 1,
        "page_width": 1,
        "page_height": 1,
        "source": "ocr",
        "engine_fingerprint": "fingerprint",
    }
    assert blocks[1]["has_boxes"] is False
    assert blocks[1]["boxes"] == []


def test_non_geometric_result_uses_single_fallback_block():
    result = {
        "engine_fingerprint": "fallback-fingerprint",
        "lines": [],
        "boxes": [{"bbox": [1, 2, 3, 4], "conf": 0.8}],
    }

    blocks = build_pre_extracted_ocr_blocks(
        image_bytes=PNG_1X1,
        cleaned_text="cleaned OCR text",
        ocr_result=result,
    )

    assert blocks == [
        {
            "page": 1,
            "block_index": 0,
            "text": "cleaned OCR text",
            "boxes": [{"bbox": [1, 2, 3, 4], "conf": 0.8}],
            "page_width": 1,
            "page_height": 1,
            "source": "ocr",
            "has_boxes": True,
            "engine_fingerprint": "fallback-fingerprint",
        }
    ]
