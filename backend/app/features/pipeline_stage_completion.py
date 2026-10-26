"""Release completed-stage inputs and collect non-blocking split observations."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def complete_stage_data(
    name: str, data: dict, result: Any, *, warning: Callable[..., None]
) -> None:
    """Release an input only after its last consumer has completed."""
    if name == "extract":
        pass
    elif name == "normalize_text":
        data.pop("raw_blocks", None)
    elif name == "ocr_correction":
        data.pop("file_content", None)
        data.pop("page_images", None)
    elif name == "split":
        data.pop("file_path", None)
        _observe_split_quality(data, result, warning)
        _observe_routing(data, warning)
    elif name == "match":
        data.pop("normalized_blocks", None)
    elif name == "normalize_schema":
        data.pop("raw_questions", None)
        data.pop("matched", None)
        data.pop("unmatched", None)


def _observe_split_quality(
    data: dict, result: Any, warning: Callable[..., None]
) -> None:
    try:
        from app.evaluation.split_quality import evaluate_split_quality

        score = evaluate_split_quality(
            result.get("raw_questions", []),
            result.get("split_diagnostics"),
            data.get("layout_result"),
        )
        data["split_quality"] = score
    except Exception as exc:
        warning("split_quality evaluation failed: %s", exc)


def _observe_routing(data: dict, warning: Callable[..., None]) -> None:
    try:
        from app.evaluation.routing_metrics import build_routing_metrics

        data["routing_metrics"] = build_routing_metrics(data)
    except Exception as exc:
        warning("routing_metrics build failed: %s", exc)
