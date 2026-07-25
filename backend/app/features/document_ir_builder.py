"""DocumentIR 构建器 — 从旧版 OCR blocks 格式构建 DocumentIR。

将 ``pipeline_orchestrator._blocks_to_document_ir()`` 提取为独立模块，
使 adapter/coordinator 无需 import legacy orchestrator 即可构建 DocumentIR。
"""

from __future__ import annotations

from typing import Any


def blocks_to_document_ir(
    blocks: list[dict],
    *,
    pipeline_id: str = "",
    engine: str = "paddleocr",
    source_bytes: bytes | None = None,
) -> Any | None:
    """Convert OCR blocks into a ``DocumentIR``.

    Each distinct page in *blocks* becomes a ``PageIR`` with one
    ``RegionIR(region_type="text")`` per block, containing line-level
    text and bounding box information.

    Args:
        blocks: OCR blocks from the legacy pipeline.
        pipeline_id: Pipeline trace ID.
        engine: OCR engine name (for Provenance).
        source_bytes: Original source bytes (for stable document ID).

    Returns:
        ``DocumentIR`` or ``None`` if the document_ir module is unavailable.
    """
    try:
        from app.core.document_ir import (
            BBox,
            DocumentIR,
            LineIR,
            PageIR,
            Provenance,
            RegionIR,
            make_line_id_from_bbox,
            make_page_id,
            make_region_id_from_bbox,
            new_document,
        )
    except ImportError:
        return None

    if not blocks:
        return None

    effective_source = source_bytes
    if effective_source is None and pipeline_id:
        effective_source = pipeline_id.encode("utf-8")

    doc = new_document(source_bytes=effective_source)
    doc.pipeline_fingerprint = pipeline_id

    # Group blocks by page
    page_blocks: dict[int, list[dict]] = {}
    for b in blocks:
        pid = b.get("page", 1)
        page_blocks.setdefault(pid, []).append(b)

    for page_idx in sorted(page_blocks):
        page_b = page_blocks[page_idx]
        pw = page_b[0].get("page_width", 0)
        ph = page_b[0].get("page_height", 0)

        zero_based_idx = page_idx - 1
        page_id = make_page_id(doc.document_id, zero_based_idx)

        regions: list[RegionIR] = []
        for bi, b in enumerate(page_b):
            text = b.get("normalized_text") or b.get("text", "")
            boxes = b.get("boxes", []) or []
            lines: list[LineIR] = []
            for li, box_entry in enumerate(boxes):
                bbox_coords = box_entry.get("bbox")
                bbox = BBox(*bbox_coords) if bbox_coords and len(bbox_coords) == 4 else None
                conf = box_entry.get("conf", 1.0)
                low_conf = box_entry.get("low_conf", False)
                flags: set[str] = set()
                if low_conf:
                    flags.add("low_conf")

                line_text = ""
                if li < len(text.split("\n")):
                    line_text = text.split("\n")[li]

                if bi < len(regions):
                    region_id_for_line = regions[bi].region_id
                else:
                    region_id_for_line = ""

                lines.append(LineIR(
                    line_id=(
                        make_line_id_from_bbox(region_id_for_line, bbox, line_text)
                        if region_id_for_line
                        else f"p{zero_based_idx}r{bi}l{li}"
                    ),
                    text=line_text,
                    bbox=bbox,
                    confidence=conf,
                    flags=flags,
                    provenance=Provenance(engine=engine),
                ))

            b.get("source", "ocr")
            region_flags: set[str] = set()
            if b.get("has_boxes"):
                region_flags.add("has_boxes")
            if b.get("_ocr_boxes_failed"):
                region_flags.add("boxes_failed")

            block_bbox = BBox(0, 0, pw, ph) if pw and ph else None
            region_id = make_region_id_from_bbox(page_id, block_bbox, engine, text)

            region = RegionIR(
                region_id=region_id,
                region_type="text",
                bbox=block_bbox,
                lines=lines,
                flags=region_flags,
                provenance=Provenance(engine=engine),
            )
            for line in region.lines:
                if not line.line_id or not line.line_id.startswith(region_id):
                    line.line_id = make_line_id_from_bbox(region_id, line.bbox, line.text)
            regions.append(region)

        doc.add_page(PageIR(
            page_id=page_id,
            page_index=zero_based_idx,
            width=pw,
            height=ph,
            regions=regions,
        ))

    return doc
