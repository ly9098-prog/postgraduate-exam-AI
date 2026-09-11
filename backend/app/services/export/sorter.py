"""Sort resolved WrongQuestion IDs according to the requested strategy.

Sorting is applied to the *wrong-question* records and their associated
*question* data. The result is a stable ordering of WrongQuestion IDs.

Edge-case handling:
- Items missing the sort field sort last, with a stable tiebreaker.
- Random sort is determined once at creation time and stored in the snapshot;
  re-export preserves the same order.
"""

from __future__ import annotations

import hashlib
import logging
import random
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import normalize_to_naive_utc
from app.features.question_type import (
    QUESTION_TYPE_SORT_ORDER,
    QuestionType,
)
from app.models.wrong_question import WrongQuestion
from app.schemas.export_task import ExportSortBy
from app.services.question_revision_service import (
    load_revision_kp_names,
    load_revision_views,
)

logger = logging.getLogger(__name__)


async def sort_questions(
    db: AsyncSession,
    user_id: int,
    wq_ids: list[int],
    sort_by: ExportSortBy,
) -> list[int]:
    """Return the WQ IDs in the requested sort order.

    The full sort result carries the canonical ordering used for snapshot
    and PDF generation. Each call produces a deterministic ordering.
    """
    if not wq_ids:
        return []

    if sort_by == ExportSortBy.RANDOM:
        return _sort_random(wq_ids)

    # Sort from immutable wrong-question revisions.
    rows = list(
        (
            await db.scalars(select(WrongQuestion).where(WrongQuestion.id.in_(wq_ids)))
        ).all()
    )
    revision_ids = [int(wq.question_version_id) for wq in rows]
    views = await load_revision_views(db, revision_ids)
    kp_map = await load_revision_kp_names(db, revision_ids)

    # Build sort key map: wq_id -> (primary_sort_key, tiebreaker)
    sort_keys: dict[int, tuple] = {}

    for wq in rows:
        q = views.get(int(wq.question_version_id))
        if q is None:
            continue
        tiebreaker = wq.id  # stable tiebreaker
        key = _sort_key(sort_by, wq, q, kp_map.get(int(wq.question_version_id), []))
        sort_keys[wq.id] = (key, tiebreaker)

    # Items not in sort_keys (shouldn't happen) sort last
    # Preserve input order for unknown items
    missing = [i for i in wq_ids if i not in sort_keys]

    known = [(i, sort_keys[i]) for i in wq_ids if i in sort_keys]
    known.sort(key=lambda x: x[1])  # sort by (sort_key, tiebreaker)

    return [i for i, _ in known] + missing


def _sort_key(
    sort_by: ExportSortBy, wq: WrongQuestion, q, kps: list[str] | None = None
):
    """Return a comparable sort key."""
    if sort_by == ExportSortBy.NEWEST:
        timestamp = _datetime_timestamp(wq.created_at)
        # Missing timestamps always sort last; newest dates sort first.
        return (1, 0.0) if timestamp is None else (0, -timestamp)

    if sort_by == ExportSortBy.OLDEST:
        timestamp = _datetime_timestamp(wq.created_at)
        # Missing timestamps always sort last; oldest dates sort first.
        return (1, 0.0) if timestamp is None else (0, timestamp)

    if sort_by == ExportSortBy.ORIGINAL:
        # Original order based on question source ordering — use question ID as proxy
        return (q.id or 0,)

    if sort_by == ExportSortBy.KNOWLEDGE_POINT:
        kp = kps or []
        primary = str((kp[0] if kp else "") or "").strip()
        return (0, primary) if primary else (1, "")

    if sort_by == ExportSortBy.QUESTION_TYPE:
        qt = q.question_type or ""
        try:
            order = QUESTION_TYPE_SORT_ORDER.get(QuestionType(qt), 999) if qt else 999
        except (ValueError, KeyError):
            order = 999
        return (order,)

    return (0,)


def _datetime_timestamp(value) -> float | None:
    """Normalize datetime-like values to a sortable timestamp.

    ``WrongQuestion.created_at`` is normally a ``datetime`` but older rows or
    test fixtures may contain ISO strings. Returning ``None`` keeps malformed
    or missing values at the end instead of raising a mixed-type sort error.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        try:
            normalized = normalize_to_naive_utc(value)
            return normalized.replace(tzinfo=UTC).timestamp()
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            normalized = normalize_to_naive_utc(parsed)
            return normalized.replace(tzinfo=UTC).timestamp()
        except (OSError, OverflowError, ValueError):
            return None
    return None


def _sort_random(wq_ids: list[int]) -> list[int]:
    """Deterministic shuffle based on hash of sorted IDs.

    The same input list always produces the same shuffle.
    This is saved in the snapshot so re-export preserves order.
    """
    seed = hashlib.sha256(str(sorted(wq_ids)).encode()).digest()
    rng = random.Random(seed)
    shuffled = list(wq_ids)
    rng.shuffle(shuffled)
    return shuffled
