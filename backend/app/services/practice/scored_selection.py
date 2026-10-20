"""Select ranked practice questions with the existing diversity relaxation."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.question import Question


def select_scored_candidates(
    scored: list[tuple[Question, float, list[str]]],
    count: int,
    q_kp_map: dict[int, list[int]],
    metadata: dict[int, dict],
    metadata_factory: Callable[[float, list[str], list[int]], dict],
) -> tuple[list[Question], set[int], bool]:
    """Keep rank order and build metadata at the original selection points."""
    max_per_kp = max(1, int(count * 0.5))
    selected: list[Question] = []
    selected_ids: set[int] = set()
    kp_counter: dict[int, int] = {}
    for q, score, reasons in scored:
        kp_ids = q_kp_map.get(q.id, [])
        if kp_ids:
            min_count = min(kp_counter.get(k, 0) for k in kp_ids)
            if min_count >= max_per_kp:
                continue
        selected.append(q)
        selected_ids.add(q.id)
        for kid in kp_ids:
            kp_counter[kid] = kp_counter.get(kid, 0) + 1
        metadata[q.id] = metadata_factory(score, reasons, kp_ids)
        if len(selected) >= count:
            break
    relaxed = len(selected) < count
    if relaxed:
        for q, score, reasons in scored:
            if q.id in selected_ids:
                continue
            selected.append(q)
            selected_ids.add(q.id)
            metadata[q.id] = metadata_factory(score, reasons, q_kp_map.get(q.id, []))
            if len(selected) >= count:
                break
    return selected, selected_ids, relaxed
