"""Structured table recovery stage.

The stage consumes provider table blocks first, then coordinate/token data, and
finally conservative OCR-text inference.  Markdown is generated only as a
compatibility projection of the canonical ``table.v2`` segment.
"""

from __future__ import annotations

import logging
from typing import Any

from app.features.pipeline_stages._helpers import _count_risk_flags
from app.features.table_structure import (
    TABLE_SEGMENT_TYPE,
    deduplicate_table_segments,
    merge_continued_table_segments,
    restore_tables_from_source,
    table_fingerprint,
    validate_table_segment,
)

logger = logging.getLogger(__name__)

_TABLE_REGION_TYPES = {"table", "table_image", "table_caption"}


def run_table_detect_stage(questions: list[dict]) -> dict:
    """Recover canonical tables and attach them to the correct question."""
    if not questions:
        return {"questions": questions, "warnings": ["table_detect: empty questions"]}

    warnings: list[str] = []
    table_count = 0
    low_confidence_count = 0

    for question in questions:
        stem = str(
            question.get("stem")
            or (question.get("parsed_content") or {}).get("text")
            or ""
        )
        existing_segments = list(
            question.get("segments")
            or (question.get("parsed_content") or {}).get("segments")
            or []
        )

        migrated, retained = _migrate_existing_segments(existing_segments, question)
        provider_tables = _restore_provider_tables(question)
        text_tables = []
        if stem:
            text_tables = restore_tables_from_source(
                stem,
                source_page=int(question.get("page_start") or 1),
                source_format="text",
            )

        tables = deduplicate_table_segments(migrated + provider_tables + text_tables)
        if not tables:
            # Still remove no legacy content; this is a pass-through question.
            continue

        tables = [
            table
            for table in tables
            if not validate_table_segment(table) or table.get("rows")
        ]
        tables = merge_continued_table_segments(tables)
        table_count += len(tables)
        low_confidence_count += sum(
            bool(table.get("requires_review")) for table in tables
        )

        # Rebuild textual layout only when table text was inferred from the stem.
        rebuilt = _segments_with_tables_in_text(stem, tables)
        if rebuilt:
            # Text was reconstructed around the recovered table, therefore old
            # text/newline segments would duplicate the stem.  Preserve only
            # non-text visual segments from earlier stages.
            retained_visual = [
                segment
                for segment in retained
                if str(segment.get("type") or "").lower() not in {"text", "newline"}
            ]
            segments = rebuilt + retained_visual
            existing_table_fingerprints = {
                table_fingerprint(seg)
                for seg in rebuilt
                if seg.get("type") == TABLE_SEGMENT_TYPE
            }
            segments.extend(
                table
                for table in tables
                if table_fingerprint(table) not in existing_table_fingerprints
            )
        else:
            segments = retained + tables

        # Stable de-dup while preserving text/image ordering.
        final_segments: list[dict] = []
        table_seen: set[str] = set()
        for segment in segments:
            if segment.get("type") == TABLE_SEGMENT_TYPE:
                fp = table_fingerprint(segment)
                if fp in table_seen:
                    continue
                table_seen.add(fp)
            final_segments.append(segment)

        flags = list(question.get("risk_flags") or [])
        _append_unique(flags, "table_detected")
        if any(table.get("requires_review") for table in tables):
            _append_unique(flags, "table_low_confidence")
        else:
            _append_unique(flags, "table_structured")

        question["segments"] = final_segments
        question["parsed_content"] = {
            **(question.get("parsed_content") or {}),
            "text": stem,
            "render_mode": "segments",
            "segments": final_segments,
        }
        question["risk_flags"] = flags
        question["table_count"] = len(tables)

    if table_count:
        warnings.append(
            f"table_detect: restored {table_count} structured table(s); "
            f"review_required={low_confidence_count}"
        )

    return {
        "questions": questions,
        "warnings": warnings,
        "risk_flag_counts": _count_risk_flags(questions),
        "table_structured_count": table_count,
        "table_review_count": low_confidence_count,
    }


def _migrate_existing_segments(
    segments: list[dict], question: dict
) -> tuple[list[dict], list[dict]]:
    tables: list[dict] = []
    retained: list[dict] = []
    page = int(question.get("page_start") or 1)
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        seg_type = str(segment.get("type") or "").lower()
        if seg_type == TABLE_SEGMENT_TYPE:
            tables.extend(restore_tables_from_source(segment, source_page=page))
        elif seg_type == "table_markdown":
            raw = segment.get("markdown") or segment.get("text") or ""
            tables.extend(
                restore_tables_from_source(
                    raw,
                    source_page=int(segment.get("source_page") or page),
                    bbox=segment.get("bbox"),
                    coordinate_space=segment.get("coordinate_space"),
                    confidence=segment.get("confidence"),
                    region_id=segment.get("region_id"),
                    source_format="markdown",
                )
            )
        else:
            retained.append(segment)
    return tables, retained


def _restore_provider_tables(question: dict) -> list[dict]:
    page = int(question.get("page_start") or 1)
    tables: list[dict] = []

    for region in question.get("visual_regions") or []:
        if not isinstance(region, dict):
            continue
        region_type = str(region.get("region_type") or region.get("type") or "").lower()
        if region_type not in _TABLE_REGION_TYPES:
            continue
        source = region.get("table_source") or region.get("raw_data") or region
        restored = restore_tables_from_source(
            source,
            source_page=int(region.get("source_page") or page),
            bbox=region.get("bbox"),
            coordinate_space=region.get("coordinate_space"),
            confidence=region.get("confidence"),
            region_id=region.get("region_id"),
            source_format="auto",
        )
        if region.get("requires_review"):
            for table in restored:
                table["requires_review"] = True
                signals = list(table.get("signals") or [])
                _append_unique(signals, "region_requires_review")
                table["signals"] = signals
        tables.extend(restored)

    for key in ("vl_layout_blocks", "layout_blocks", "table_blocks", "table_sources"):
        value = question.get(key)
        if not isinstance(value, list):
            continue
        for block in value:
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type") or block.get("label") or "").lower()
            if block_type and block_type not in _TABLE_REGION_TYPES:
                continue
            tables.extend(
                restore_tables_from_source(
                    block,
                    source_page=int(
                        block.get("page") or block.get("source_page") or page
                    ),
                    bbox=block.get("bbox"),
                    coordinate_space=block.get("coordinate_space"),
                    confidence=block.get("confidence"),
                    region_id=block.get("region_id"),
                    source_format="auto",
                )
            )
    return tables


def _segments_with_tables_in_text(stem: str, tables: list[dict]) -> list[dict]:
    candidates: list[tuple[int, int, dict]] = []
    for table in tables:
        if table.get("source_format") != "ocr_text":
            continue
        source_text = str(table.get("source_text") or "").strip()
        if not source_text:
            continue
        start = stem.find(source_text)
        if start >= 0:
            candidates.append((start, start + len(source_text), table))
    if not candidates:
        return []

    candidates.sort(key=lambda item: (item[0], item[1]))
    result: list[dict] = []
    cursor = 0
    for start, end, table in candidates:
        if start < cursor:
            continue
        if start > cursor:
            _append_text_segment(result, stem[cursor:start])
        result.append(table)
        cursor = end
    if cursor < len(stem):
        _append_text_segment(result, stem[cursor:])
    return result


def _append_text_segment(segments: list[dict], text: str) -> None:
    text = text.strip("\n")
    if text.strip():
        segments.append({"type": "text", "text": text})


def _append_unique(values: list[Any], value: Any) -> None:
    if value not in values:
        values.append(value)
