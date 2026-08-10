"""Group sorted WrongQuestion IDs into sections by the requested strategy.

Grouping is an overlay on top of sorting. Each group gets a title/header.
Questions with no group data sort into a default "其他" group at the end.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.question import Question
from app.models.wrong_question import WrongQuestion
from app.schemas.export_task import ExportGroupBy
from app.services.knowledge_point_service import load_question_kps

logger = logging.getLogger(__name__)


@dataclass
class GroupSection:
    """A named group within the export."""
    title: str
    wq_ids: list[int] = field(default_factory=list)


async def group_questions(
    db: AsyncSession,
    user_id: int,
    wq_ids: list[int],
    group_by: ExportGroupBy,
) -> list[GroupSection]:
    """Partition WQ IDs into groups.

    When ``group_by`` is ``none``, a single group is returned.
    Each question appears in exactly one group. For multi-knowledge-point
    questions, the first knowledge point is used as the primary one.
    """
    if group_by == ExportGroupBy.NONE:
        return [GroupSection(title="", wq_ids=list(wq_ids))]

    # Load question data for grouping
    result = await db.execute(
        select(WrongQuestion, Question)
        .join(Question, WrongQuestion.question_id == Question.id)
        .where(WrongQuestion.id.in_(wq_ids))
        .options(selectinload(Question.subject_ref))
    )
    rows = result.fetchall()

    kp_map = await load_question_kps(db, [q.id for _wq, q in rows])

    groups_map: dict[str, list[int]] = {}
    _wq_order = {wq_id: idx for idx, wq_id in enumerate(wq_ids)}

    for wq, q in rows:
        group_key, group_title = _group_key_title(group_by, wq, q, kp_map.get(q.id, []))
        if group_key not in groups_map:
            groups_map[group_key] = []
        groups_map[group_key].append(wq.id)

    # Preserve within-group order based on input order and sort groups stably
    for key in groups_map:
        groups_map[key].sort(key=lambda i: _wq_order.get(i, 999999))

    sorted_groups = sorted(groups_map.items(), key=lambda x: x[0])

    return [
        GroupSection(title=title, wq_ids=ids)
        for key, (title, ids) in [(k, (k, v)) for k, v in sorted_groups]
    ]


def _group_key_title(group_by: ExportGroupBy, wq: WrongQuestion, q: Question, kps: list[str] | None = None) -> tuple[str, str]:
    """Return (sort_key, display_title) for the question."""
    if group_by == ExportGroupBy.SUBJECT:
        subject = _get_subject_label(q)
        return (subject or "其他", subject or "其他")

    if group_by == ExportGroupBy.CHAPTER:
        chapter = _get_chapter(q)
        return (chapter or "其他", chapter or "其他")

    if group_by == ExportGroupBy.KNOWLEDGE_POINT:
        kp = _get_primary_knowledge_point(kps)
        return (kp or "其他知识点", kp or "其他知识点")

    if group_by == ExportGroupBy.QUESTION_TYPE:
        qt_label = _get_question_type_label(q)
        return (qt_label or "其他", qt_label or "其他")

    return ("", "")


def _get_subject_label(q: Question) -> str | None:
    """Get the subject display name from the question."""
    try:
        if q.subject_ref:
            from app.models.admin import Subject
            if isinstance(q.subject_ref, Subject):
                return q.subject_ref.name
    except Exception:
        pass
    return None


def _get_chapter(q: Question) -> str | None:
    """Extract chapter from question source or knowledge_points."""
    # The project may not have explicit chapters — fall back to source
    if q.source:
        return q.source
    return None


def _get_primary_knowledge_point(kps: list[str] | None) -> str | None:
    """Return the first knowledge point as the primary one (order by position)."""
    if kps and len(kps) > 0:
        return str(kps[0])
    return None


def _get_question_type_label(q: Question) -> str | None:
    """Return the Chinese label for the question type."""
    from app.features.question_type import QUESTION_TYPE_LABELS, QuestionType
    if q.question_type:
        try:
            return QUESTION_TYPE_LABELS.get(QuestionType(q.question_type))
        except (ValueError, KeyError):
            pass
    return None
