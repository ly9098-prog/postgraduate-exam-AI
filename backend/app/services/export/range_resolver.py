"""Resolve the set of wrong-question IDs for a given export range type.

Validates that:
- For ``selected`` range: every ID belongs to the current user's wrong-question book.
- For ``all`` range: page-filter params are NOT applied (range is truly all).
- For ``filtered`` range: filter params are applied using the same query logic
  as the wrong-question listing endpoint.
- Count limits are enforced by the create/retry/re-export endpoints, NOT here,
  so preview-count can report any number without error.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.wrong_question import WrongQuestion
from app.schemas.export_task import ExportRangeType

logger = logging.getLogger(__name__)


def _build_base_query(user_id: int) -> select:
    """Return active wrong-question rows for a user."""
    return select(WrongQuestion.id).where(
        WrongQuestion.user_id == user_id,
        WrongQuestion.is_active.is_(True),
    )


async def _apply_filters(db: AsyncSession, query: select, filters: dict | None) -> select:
    """Apply the same filter logic as the wrong-question list endpoint.

    Supported filter keys: ``subject``, ``error_type``, ``topic``.
    Subject codes/names are resolved through ``resolve_subject_ids()``
    to be consistent with the wrong-question listing endpoint.
    """
    if not filters:
        return query

    if subject := filters.get("subject"):
        from app.models.question import Question
        from app.services.admin_subject_service import resolve_subject_ids

        subject_ids = await resolve_subject_ids(db, subject)
        if subject_ids:
            query = query.join(Question, WrongQuestion.question_id == Question.id).where(
                Question.subject_id.in_(subject_ids)
            )
        else:
            query = query.where(False)

    if error_type := filters.get("error_type"):
        query = query.where(WrongQuestion.error_type == error_type)
    if topic := filters.get("topic"):
        import sqlalchemy as sa

        from app.models.question import Question
        if not any(
            isinstance(f, sa.sql.Join) or str(f).startswith("JOIN")
            for f in query.froms  # type: ignore[union-attr]
        ):
            query = query.join(Question, WrongQuestion.question_id == Question.id)
        query = query.where(
            Question.knowledge_points.any(topic) if hasattr(Question.knowledge_points, "any")
            else Question.knowledge_points.contains(topic)
        )

    return query


async def resolve_range(
    db: AsyncSession,
    user_id: int,
    range_type: ExportRangeType,
    filters: dict | None = None,
    selected_ids: list[int] | None = None,
) -> list[int]:
    """Return the list of validated WrongQuestion IDs for the given range.

    Raises:
        ValueError: if the range type is invalid or ownership check fails.
        Does NOT enforce max-count limits — those are checked at create time.
    """
    if range_type == ExportRangeType.SELECTED:
        return await _resolve_selected(db, user_id, selected_ids or [])

    if range_type == ExportRangeType.ALL:
        return await _resolve_all(db, user_id)

    if range_type == ExportRangeType.FILTERED:
        return await _resolve_filtered(db, user_id, filters)

    raise ValueError(f"不支持的导出范围: {range_type}")


async def _resolve_all(db: AsyncSession, user_id: int) -> list[int]:
    """All active wrong questions for the user — no filters applied."""
    query = _build_base_query(user_id).order_by(WrongQuestion.id)
    result = await db.execute(query)
    ids = [row[0] for row in result.fetchall()]
    return ids


async def _resolve_filtered(
    db: AsyncSession,
    user_id: int,
    filters: dict | None,
) -> list[int]:
    """Active wrong questions matching the given filter params.

    Empty filter payloads are treated as the unfiltered result set. This keeps
    preview/create compatible with clients that represent "current result"
    as ``filtered`` even when the user has not applied any actual condition.
    """
    if not filters or not any(
        value not in (None, "", [], {}) for value in filters.values()
    ):
        return await _resolve_all(db, user_id)
    query = _build_base_query(user_id)
    query = await _apply_filters(db, query, filters)
    query = query.order_by(WrongQuestion.id)
    result = await db.execute(query)
    ids = [row[0] for row in result.fetchall()]
    return ids


async def _resolve_selected(
    db: AsyncSession,
    user_id: int,
    selected_ids: list[int],
) -> list[int]:
    """Verify each selected ID is an active wrong-question record of the user.

    If ANY ID is not found, not owned by the user, or not active, the entire
    request is rejected. This prevents leaking information about which IDs
    exist or belong to other users.
    """
    if not selected_ids:
        raise ValueError("已选错题列表为空")

    # Deduplicate
    unique = list(dict.fromkeys(selected_ids))

    # Validate ownership
    result = await db.execute(
        select(WrongQuestion.id).where(
            WrongQuestion.id.in_(unique),
            WrongQuestion.user_id == user_id,
            WrongQuestion.is_active.is_(True),
        )
    )
    valid_ids = {row[0] for row in result.fetchall()}

    # If ANY selected ID is invalid, reject the entire request
    missing = len(unique) - len(valid_ids)
    if missing > 0:
        logger.warning(
            "User %d: %d selected wrong-question IDs invalid (unauthorized/deleted)",
            user_id, missing,
        )
        # Return an opaque error — do not leak which IDs are valid
        raise ValueError("部分题目无法导出，请刷新后重试")

    return unique


def preview_count(
    resolved_ids: list[int],
) -> int:
    """Return the count without additional DB roundtrip."""
    return len(resolved_ids)
