"""Table-region recovery facade.

Backward-compatible entry points now delegate to the canonical structured-table
engine in :mod:`app.features.table_structure`.
"""

from __future__ import annotations

from typing import Any

from app.features.table_structure import (
    deduplicate_table_segments,
    restore_tables_from_source,
)


def detect_table_candidate(text: str) -> dict:
    """Detect and restore table candidates from OCR text.

    The legacy return keys remain available.  ``tables`` contains canonical
    ``table.v2`` segments and is the preferred output.
    """
    tables = restore_tables_from_source(text, source_format="auto")
    confidence = max(
        (float(table.get("confidence") or 0.0) for table in tables), default=0.0
    )
    signals: list[str] = []
    for table in tables:
        signals.extend(table.get("signals") or [])
    markdown = tables[0].get("markdown") if tables else None
    return {
        "is_table": bool(tables),
        "signals": list(dict.fromkeys(signals)),
        "confidence": round(confidence, 3),
        "markdown": markdown,
        "tables": tables,
    }


def detect_tables_in_blocks(blocks: list[dict]) -> list[dict]:
    """Restore canonical tables from normalized OCR/VL blocks."""
    tables: list[dict] = []
    for block in blocks or []:
        page = int(block.get("page") or block.get("page_index") or 1)
        bbox = block.get("bbox")
        coordinate_space = block.get("coordinate_space")
        confidence = block.get("confidence")
        region_id = block.get("region_id")

        candidates: list[Any] = []
        block_type = str(block.get("type") or block.get("label") or "").lower()
        if block_type in {"table", "table_image", "table_caption"}:
            candidates.append(block)
        for key in ("vl_layout_blocks", "layout_blocks", "table_blocks"):
            value = block.get(key)
            if isinstance(value, list):
                candidates.extend(
                    item
                    for item in value
                    if isinstance(item, dict)
                    and str(item.get("type") or item.get("label") or "").lower()
                    in {"table", "table_image"}
                )
        if not candidates:
            text = str(block.get("normalized_text") or block.get("text") or "").strip()
            if text:
                candidates.append(text)

        for candidate in candidates:
            restored = restore_tables_from_source(
                candidate,
                source_page=page,
                bbox=bbox,
                coordinate_space=coordinate_space,
                confidence=confidence,
                region_id=region_id,
                source_format="auto",
            )
            for table in restored:
                # Backward-compatible legacy key: callers may read `page`.
                table["page"] = int(table.get("source_page") or page)
            tables.extend(restored)

    return deduplicate_table_segments(tables)
