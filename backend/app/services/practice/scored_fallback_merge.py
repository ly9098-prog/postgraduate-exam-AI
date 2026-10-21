"""Merge scored selection with fallback rows without owning queries or metadata."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.question import Question


def merge_fill_questions(
    selected: list[Question],
    selected_ids: set[int],
    questions: Iterable[Question],
    metadata: dict[int, dict],
    reason: str,
    strategy: str,
    metadata_factory: Callable[[str, str], dict],
    *,
    skip_duplicates: bool,
) -> list[Question]:
    """Append fill rows in provider order and attach metadata at merge points."""
    for question in questions:
        if skip_duplicates and question.id in selected_ids:
            continue
        selected.append(question)
        selected_ids.add(question.id)
        metadata[question.id] = metadata_factory(reason, strategy)
    return selected
