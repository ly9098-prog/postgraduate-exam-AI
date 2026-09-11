"""Common orchestration primitives for smart-practice strategies.

Strategy implementations may recall/score candidates differently, but they
share naming, stable merge/deduplication and fallback semantics here.  Keeping
these rules centralized prevents scored/path/vector branches from drifting.
"""

from __future__ import annotations

from typing import TypeVar

T = TypeVar("T")

_STRATEGY_ALIASES = {
    "knowledge_path": "path",
    "hybrid_graph": "scored",
    "smart_scored": "scored",
    "weakness_vector": "weakness_vector",
}


def normalize_smart_strategy(strategy: str | None) -> str:
    value = (strategy or "scored").strip().lower()
    return _STRATEGY_ALIASES.get(value, value)


def merge_recommendation_results(
    primary: list[T],
    primary_meta: dict[int, dict],
    fallback: list[T],
    fallback_meta: dict[int, dict],
    *,
    count: int,
) -> tuple[list[T], dict[int, dict]]:
    """Stable merge by object ``id``; primary always wins duplicates/metadata."""
    merged: list[T] = []
    seen: set[int] = set()
    metadata: dict[int, dict] = {}

    for bucket, bucket_meta in ((primary, primary_meta), (fallback, fallback_meta)):
        for item in bucket:
            item_id = int(getattr(item, "id"))
            if item_id in seen:
                continue
            seen.add(item_id)
            merged.append(item)
            if item_id in bucket_meta and item_id not in metadata:
                metadata[item_id] = dict(bucket_meta[item_id])
            if len(merged) >= count:
                return merged, metadata
    return merged, metadata
