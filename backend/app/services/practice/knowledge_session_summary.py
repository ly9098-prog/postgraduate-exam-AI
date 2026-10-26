"""Knowledge-impact summary for a completed practice batch.

The practice writer persists only leaf/question evidence. Chapter mastery remains a
read-time aggregation from ``knowledge_map_service``; this module snapshots the
pre-practice state in the signed batch token and compares it with the projected
post-practice state once answer projections finish.

The semantic practice scope is persisted on ``PracticeSession`` for history and
reporting, but no additional chapter-mastery table is maintained.  Chapter mastery
therefore still has a single source of truth: aggregation from knowledge-point state.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import QuestionVersionKnowledgePoint
from app.models.knowledge_point import KnowledgePoint
from app.models.practice_record import PracticeRecord
from app.models.practice_session import PracticeSession
from app.models.user_knowledge_state import UserKnowledgeState
from app.services.practice.knowledge_summary_baseline import (
    _compact_point_baseline,
    issue_scope_ids,
    signed_knowledge_context,
)
from app.services.practice.knowledge_summary_points import (
    _state_status,
    add_revision_points,
    point_statistics,
    project_points,
    rank_points,
    record_revision_ids,
    response_record_ids,
    session_baselines,
)
from app.services.practice.knowledge_summary_projection import (
    project_chapter,
    public_knowledge_session,
    summary_response,
    summary_scope,
)

_CONTEXT_VERSION = 2
_MAX_SUMMARY_POINTS = 24
_MAX_BASELINE_POINTS = 96


def _number_or_none(value: Any, *, digits: int = 1) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _delta(before: Any, after: Any) -> float | None:
    before_value = _number_or_none(before, digits=4)
    after_value = _number_or_none(after, digits=4)
    if before_value is None or after_value is None:
        return None
    return round(after_value - before_value, 1)


async def build_issue_knowledge_context(
    db: AsyncSession,
    *,
    user_id: int,
    knowledge_scope: dict | None,
    questions: list,
    revision_ids: dict[int, int],
    practice_subject_id: int | None = None,
) -> dict | None:
    """Load revision evidence before projecting the signed issue-time baseline."""
    if not knowledge_scope or not questions:
        return None
    root_id, scope_id_list = issue_scope_ids(knowledge_scope)
    scope_ids = set(scope_id_list)
    if not scope_ids:
        return None
    issued_revision_ids = [
        int(revision_ids[int(question.id)])
        for question in questions
        if int(question.id) in revision_ids
    ]
    if not issued_revision_ids:
        return None
    rows = await _load_issued_points(db, issued_revision_ids, scope_ids)
    represented_ids = {int(value) for value in rows}
    served_ids = [kp_id for kp_id in scope_id_list if kp_id in represented_ids]
    touched_ids = served_ids[:_MAX_BASELINE_POINTS]
    states = await _load_knowledge_states(db, user_id, touched_ids)

    from app.services import knowledge_map_service

    root_detail = await knowledge_map_service.get_point_detail(db, user_id, root_id)
    return signed_knowledge_context(
        knowledge_scope,
        root_id,
        scope_id_list,
        served_ids,
        touched_ids,
        states,
        root_detail,
        practice_subject_id,
        _CONTEXT_VERSION,
        lambda state, kp_id: _compact_point_baseline(state, kp_id),
    )


async def _load_issued_points(db, issued_revision_ids, scope_ids):
    rows = await db.execute(
        select(QuestionVersionKnowledgePoint.knowledge_point_id)
        .join(
            KnowledgePoint,
            QuestionVersionKnowledgePoint.knowledge_point_id == KnowledgePoint.id,
        )
        .where(
            QuestionVersionKnowledgePoint.question_version_id.in_(issued_revision_ids),
            QuestionVersionKnowledgePoint.knowledge_point_id.in_(scope_ids),
            KnowledgePoint.is_active.is_(True),
        )
        .distinct()
    )
    return rows.scalars().all()


async def _load_summary_mappings(db, revision_ids, baseline_ids):
    return (
        await db.execute(
            select(
                QuestionVersionKnowledgePoint.question_version_id,
                KnowledgePoint.id,
                KnowledgePoint.name,
            )
            .join(
                KnowledgePoint,
                QuestionVersionKnowledgePoint.knowledge_point_id == KnowledgePoint.id,
            )
            .where(
                QuestionVersionKnowledgePoint.question_version_id.in_(revision_ids),
                QuestionVersionKnowledgePoint.knowledge_point_id.in_(baseline_ids),
                KnowledgePoint.is_active.is_(True),
            )
        )
    ).all()


async def _load_knowledge_states(db, user_id, touched_ids):
    if not touched_ids:
        return {}
    state_rows = (
        await db.scalars(
            select(UserKnowledgeState).where(
                UserKnowledgeState.user_id == user_id,
                UserKnowledgeState.knowledge_point_id.in_(touched_ids),
            )
        )
    ).all()
    return {int(state.knowledge_point_id): state for state in state_rows}


def persisted_knowledge_session(context: dict | None) -> dict | None:
    public = public_knowledge_session(context)
    if public is None:
        return None
    return {
        **public,
        "_baseline": (context or {}).get("baseline") or {},
        "_context_version": int((context or {}).get("v") or _CONTEXT_VERSION),
    }


async def _load_session_records(
    db: AsyncSession,
    *,
    user_id: int,
    response: dict,
) -> list[PracticeRecord]:
    record_ids = response_record_ids(response)
    if not record_ids:
        return []
    rows = (
        await db.scalars(
            select(PracticeRecord).where(
                PracticeRecord.user_id == user_id,
                PracticeRecord.id.in_(record_ids),
            )
        )
    ).all()
    by_id = {int(record.id): record for record in rows}
    return [by_id[record_id] for record_id in record_ids if record_id in by_id]


async def get_session_knowledge_summary(
    db: AsyncSession,
    *,
    user_id: int,
    request_id: str,
) -> dict | None:
    request_id = str(request_id or "").strip()
    if not request_id:
        return None
    session = await db.scalar(
        select(PracticeSession).where(
            PracticeSession.user_id == user_id, PracticeSession.request_id == request_id
        )
    )
    if session is None:
        return None
    response = (
        session.submission_response
        if isinstance(session.submission_response, dict)
        else {}
    )
    knowledge_session = response.get("knowledge_session")

    from app.services.practice.session_scope import public_practice_session_scope

    persisted_scope = public_practice_session_scope(session.scope_snapshot)
    scope, practice_mode = summary_scope(persisted_scope, knowledge_session)
    if scope is None or not isinstance(knowledge_session, dict):
        return summary_response(request_id, practice_mode, scope, status="unavailable")
    records = await _load_session_records(db, user_id=user_id, response=response)
    pending_count = sum(
        1 for record in records if str(record.projection_state) == "pending"
    )
    if pending_count:
        return summary_response(
            request_id,
            practice_mode,
            scope,
            status="processing",
            pending_count=pending_count,
        )
    return await _ready_knowledge_summary(
        db, user_id, request_id, scope, practice_mode, knowledge_session, records
    )


async def _ready_knowledge_summary(
    db, user_id, request_id, scope, mode, knowledge, records
):
    revision_ids = record_revision_ids(records)
    qv_to_kps = defaultdict(set)
    kp_names = {}
    root_id = int(scope["root_knowledge_point_id"])
    baseline, baseline_points = session_baselines(knowledge)
    baseline_ids = set(baseline_points)
    if revision_ids and baseline_ids:
        mapping_rows = await _load_summary_mappings(db, revision_ids, baseline_ids)
        add_revision_points(mapping_rows, qv_to_kps, kp_names)
    stats = point_statistics(records, qv_to_kps)
    touched_ids = sorted(stats)
    current_states = await _load_knowledge_states(db, user_id, touched_ids)
    points = project_points(
        touched_ids,
        current_states,
        baseline_points,
        kp_names,
        stats,
        number=lambda value: _number_or_none(value),
        delta=lambda before, after: _delta(before, after),
        status=lambda state: _state_status(state),
    )
    points = rank_points(points, _MAX_SUMMARY_POINTS)

    from app.services import knowledge_map_service

    root_detail = await knowledge_map_service.get_point_detail(db, user_id, root_id)
    root_baseline = (
        baseline.get("root") if isinstance(baseline.get("root"), list) else None
    )
    chapter = project_chapter(
        root_detail,
        root_baseline,
        scope,
        root_id,
        number=lambda value: _number_or_none(value),
        delta=lambda before, after: _delta(before, after),
    )
    return summary_response(
        request_id,
        mode,
        scope,
        chapter=chapter,
        touched_count=len(touched_ids),
        points=points,
    )
