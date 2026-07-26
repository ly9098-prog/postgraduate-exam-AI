"""Resolve the set of wrong-question IDs for a given export range type.

Validates that:
- For ``selected`` range: every ID belongs to the current user's wrong-question book.
- For ``all`` range: page-filter params are NOT applied (range is truly all).
- For ``filtered`` range: filter params are applied using the same query logic
  as the wrong-question listing endpoint.
- Max 100 items enforced after resolution.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.wrong_question import WrongQuestion
from app.schemas.export_task import ExportRangeType

logger = logging.getLogger(__name__)

_MAX_EXPORT = 100


def _build_base_query(user_id: int) -> select:
    """Return active wrong-question rows for a user."""
    return select(WrongQuestion.id).where(
        WrongQuestion.user_id == user_id,
        WrongQuestion.is_active.is_(True),
    )


def _apply_filters(query: select, filters: dict | None) -> select:
    """Apply the same filter logic as the wrong-question list endpoint.

    Supported filter keys: ``subject``, ``error_type``, ``topic``.
    """
    if not filters:
        return query

    if subject := filters.get("subject"):
        from app.models.question import Question
        query = query.join(Question, WrongQuestion.question_id == Question.id).where(
            Question.subject_id == subject  # subject here is subject_id
        )
    if error_type := filters.get("error_type"):
        query = query.where(WrongQuestion.error_type == error_type)
    if topic := filters.get("topic"):
        # topic is matched against the question's knowledge_points
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
        ValueError: if the range is invalid or exceeds MAX_EXPORT.
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
    _check_limit(ids)
    return ids


async def _resolve_filtered(
    db: AsyncSession,
    user_id: int,
    filters: dict | None,
) -> list[int]:
    """Active wrong questions matching the given filter params."""
    query = _build_base_query(user_id)
    query = _apply_filters(query, filters)
    query = query.order_by(WrongQuestion.id)
    result = await db.execute(query)
    ids = [row[0] for row in result.fetchall()]
    _check_limit(ids)
    return ids


async def _resolve_selected(
    db: AsyncSession,
    user_id: int,
    selected_ids: list[int],
) -> list[int]:
    """Verify each selected ID is an active wrong-question record of the user."""
    if not selected_ids:
        raise ValueError("已选错题列表为空")

    # Deduplicate
    unique = list(dict.fromkeys(selected_ids))
    if len(unique) > _MAX_EXPORT:
        raise ValueError(f"单次最多导出 {_MAX_EXPORT} 道，已选 {len(unique)} 道")

    # Validate ownership
    result = await db.execute(
        select(WrongQuestion.id).where(
            WrongQuestion.id.in_(unique),
            WrongQuestion.user_id == user_id,
            WrongQuestion.is_active.is_(True),
        )
    )
    valid_ids = {row[0] for row in result.fetchall()}

    invalid = [str(i) for i in unique if i not in valid_ids]
    if invalid:
        logger.warning(
            "User %d: selected wrong-question IDs not found/owned: %s",
            user_id, invalid,
        )

    result_list = [i for i in unique if i in valid_ids]
    if not result_list:
        raise ValueError("没有可导出的有效错题记录")

    return result_list


def preview_count(
    resolved_ids: list[int],
) -> int:
    """Return the count without additional DB roundtrip."""
    return len(resolved_ids)


def _check_limit(ids: list[int]) -> None:
    if len(ids) > _MAX_EXPORT:
        raise ValueError(
            f"单次最多导出 {_MAX_EXPORT} 道，当前共 {len(ids)} 道，请调整导出范围。"
        )
