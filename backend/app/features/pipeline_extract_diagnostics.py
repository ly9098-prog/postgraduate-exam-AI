"""Project extraction diagnostics without changing block ownership or read order."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def resolve_extract_port(namespace: dict, name: str) -> Any:
    """Resolve an original orchestrator global, including builtin overrides."""
    if name in namespace:
        return namespace[name]
    builtins = namespace["__builtins__"]
    if not isinstance(builtins, dict):
        builtins = vars(builtins)
    if name in builtins:
        return builtins[name]
    raise NameError(f"name '{name}' is not defined", name=name)


def boxes_failed_pages(
    raw_blocks: list[dict], *, ports: Callable[[str], Any]
) -> list[int]:
    """Keep page fallback and repeated mapping reads from the original projection."""
    return ports("sorted")(
        {
            ports("int")(b.get("page") or b.get("page_index") or 0)
            for b in raw_blocks
            if b.get("_ocr_boxes_failed") and (b.get("page") or b.get("page_index"))
        }
    )


def text_fallback_pages(
    raw_blocks: list[dict], *, ports: Callable[[str], Any]
) -> list[int]:
    """Collect text-fallback pages in a separate ordered pass over the blocks."""
    return ports("sorted")(
        {
            ports("int")(b.get("page") or b.get("page_index") or 0)
            for b in raw_blocks
            if b.get("source") == "ocr_text_fallback"
            and (b.get("page") or b.get("page_index"))
        }
    )


def reported_failure_pages(
    raw_blocks: list[dict],
    key: str,
    *,
    ports: Callable[[str], Any],
) -> list[int]:
    """Normalize each embedded failure list without suppressing malformed values."""
    return ports("sorted")(
        {ports("int")(page) for b in raw_blocks for page in (b.get(key) or []) if page}
    )


def project_extract_result(
    raw_blocks: list[dict],
    exercise_regions: list[dict],
    exercise_regions_missing: bool,
    keyword_arguments: dict,
    *,
    ports: Callable[[str], Any],
) -> dict:
    """Assemble the fresh stage result after extraction and region filtering."""
    return {
        "raw_blocks": raw_blocks,
        "extracted": ports("len")(raw_blocks),
        "_original_raw_text": (keyword_arguments.get("options") or {}).get(
            "_original_raw_text", ""
        ),
        "exercise_regions": exercise_regions,
        "exercise_regions_missing": exercise_regions_missing,
        "ocr_boxes_failed_pages": boxes_failed_pages(raw_blocks, ports=ports),
        "ocr_text_fallback_pages": text_fallback_pages(raw_blocks, ports=ports),
        "ocr_text_fallback_unavailable_pages": reported_failure_pages(
            raw_blocks,
            "_ocr_text_fallback_unavailable_pages",
            ports=ports,
        ),
        "ocr_runtime_failed_pages": reported_failure_pages(
            raw_blocks,
            "_ocr_runtime_failed_pages",
            ports=ports,
        ),
    }
