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


def _state_status(state: UserKnowledgeState | None) -> str:
    if state is None or int(state.attempt_count or 0) <= 0:
        return "no_data"
    confidence = float(state.confidence or 0.0)
    if confidence < 0.25 or state.mastery_score is None:
        return "insufficient"
    mastery = float(state.mastery_score)
    if mastery < 60:
        return "weak"
    if mastery < 80:
        return "developing"
    if mastery < 90:
        return "good"
    return "mastered"


def _compact_point_baseline(
    state: UserKnowledgeState | None, knowledge_point_id: int
) -> list:
    attempts = int(state.attempt_count or 0) if state is not None else 0
    mastery = (
        round(float(state.mastery_score), 2)
        if state is not None and attempts > 0 and state.mastery_score is not None
        else None
    )
    confidence = round(float(state.confidence or 0.0), 4) if state is not None else 0.0
    return [int(knowledge_point_id), mastery, confidence, attempts]


async def build_issue_knowledge_context(
    db: AsyncSession,
    *,
    user_id: int,
    knowledge_scope: dict | None,
    questions: list,
    revision_ids: dict[int, int],
    practice_subject_id: int | None = None,
) -> dict | None:
    """Build a compact, signed baseline for knowledge-point scoped practice.

    Only knowledge points actually represented by the issued immutable revisions
    are snapshotted individually. The chapter/root aggregate is snapshotted once.
    This keeps the batch token well below its transport limit even for large trees.
    """
    if not knowledge_scope or not questions:
        return None

    root_id = int(knowledge_scope["root_id"])
    scope_id_list = list(
        dict.fromkeys(
            int(value)
            for value in knowledge_scope.get("knowledge_point_ids") or []
            if int(value) > 0
        )
    )
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

    rows = (
        (
            await db.execute(
                select(QuestionVersionKnowledgePoint.knowledge_point_id)
                .join(
                    KnowledgePoint,
                    QuestionVersionKnowledgePoint.knowledge_point_id
                    == KnowledgePoint.id,
                )
                .where(
                    QuestionVersionKnowledgePoint.question_version_id.in_(
                        issued_revision_ids
                    ),
                    QuestionVersionKnowledgePoint.knowledge_point_id.in_(scope_ids),
                    KnowledgePoint.is_active.is_(True),
                )
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    represented_ids = {int(value) for value in rows}
    served_ids = [kp_id for kp_id in scope_id_list if kp_id in represented_ids]
    touched_ids = served_ids[:_MAX_BASELINE_POINTS]

    states: dict[int, UserKnowledgeState] = {}
    if touched_ids:
        state_rows = (
            await db.scalars(
                select(UserKnowledgeState).where(
                    UserKnowledgeState.user_id == user_id,
                    UserKnowledgeState.knowledge_point_id.in_(touched_ids),
                )
            )
        ).all()
        states = {int(state.knowledge_point_id): state for state in state_rows}

    from app.services import knowledge_map_service

    root_detail = await knowledge_map_service.get_point_detail(db, user_id, root_id)
    root_baseline = None
    if root_detail is not None:
        include_descendants = bool(knowledge_scope.get("include_descendants"))
        root_reliable = (
            int(root_detail.get("subtree_reliable_knowledge_points", 0) or 0)
            if include_descendants
            else (
                1 if root_detail.get("status") not in {"no_data", "insufficient"} else 0
            )
        )
        root_weak = (
            int(root_detail.get("subtree_weak_knowledge_points", 0) or 0)
            if include_descendants
            else (1 if root_detail.get("status") == "weak" else 0)
        )
        root_trainable = (
            int(root_detail.get("subtree_trainable_knowledge_points", 0) or 0)
            if include_descendants
            else (
                1 if int(root_detail.get("trainable_question_count", 0) or 0) > 0 else 0
            )
        )
        root_baseline = [
            root_detail.get("subtree_mastery_score")
            if include_descendants
            else root_detail.get("mastery_score"),
            root_detail.get("subtree_coverage_ratio", 0.0)
            if include_descendants
            else (1.0 if root_reliable else 0.0),
            root_weak,
            root_reliable,
            root_trainable,
        ]

    return {
        "v": _CONTEXT_VERSION,
        "practice_mode": (
            "knowledge_chapter"
            if bool(knowledge_scope.get("include_descendants"))
            else "knowledge_point"
        ),
        "root_id": root_id,
        "root_name": str(knowledge_scope.get("root_name") or ""),
        # Keep semantic session subject aligned with the subject that issued the
        # batch.  A knowledge point may belong to a child subject while the user
        # legitimately practices through an aggregate parent subject.
        "subject_id": int(
            practice_subject_id or knowledge_scope.get("subject_id") or 0
        )
        or None,
        "syllabus_version_id": int(knowledge_scope.get("syllabus_version_id") or 0)
        or None,
        # Exact issue-time semantic scope. These compact id arrays are signed into
        # the batch token so submit never has to re-resolve a mutable syllabus tree.
        "scope_ids": scope_id_list,
        "served_ids": served_ids,
        "include_descendants": bool(knowledge_scope.get("include_descendants")),
        "scope_count": len(scope_id_list),
        "served_count": len(served_ids),
        "baseline": {
            "root": root_baseline,
            "points": [
                _compact_point_baseline(states.get(kp_id), kp_id)
                for kp_id in touched_ids
            ],
        },
    }


def public_knowledge_session(context: dict | None) -> dict | None:
    if not isinstance(context, dict):
        return None
    root_id = int(context.get("root_id") or 0)
    if root_id <= 0:
        return None
    return {
        "practice_mode": str(context.get("practice_mode") or "knowledge_point"),
        "root_knowledge_point_id": root_id,
        "root_name": str(context.get("root_name") or ""),
        "include_descendants": bool(context.get("include_descendants")),
        "knowledge_point_count": max(1, int(context.get("scope_count") or 1)),
    }


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
    record_ids = []
    for item in response.get("results") or []:
        if not isinstance(item, dict):
            continue
        record_id = int(item.get("record_id") or 0)
        if record_id > 0:
            record_ids.append(record_id)
    record_ids = list(dict.fromkeys(record_ids))
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
            PracticeSession.user_id == user_id,
            PracticeSession.request_id == request_id,
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
    if persisted_scope is not None:
        scope = {
            "root_knowledge_point_id": int(persisted_scope["root_knowledge_point_id"]),
            "root_name": str(persisted_scope.get("root_name") or ""),
            "include_descendants": bool(persisted_scope.get("include_descendants")),
            "knowledge_point_count": max(
                1, int(persisted_scope.get("resolved_knowledge_point_count") or 1)
            ),
        }
        practice_mode = str(persisted_scope.get("practice_mode") or "knowledge_point")
    elif isinstance(knowledge_session, dict):
        # Rolling-upgrade fallback for sessions completed before durable scope was
        # deployed but after Stage 5 started persisting knowledge_session.
        scope = {
            "root_knowledge_point_id": int(
                knowledge_session.get("root_knowledge_point_id") or 0
            ),
            "root_name": str(knowledge_session.get("root_name") or ""),
            "include_descendants": bool(knowledge_session.get("include_descendants")),
            "knowledge_point_count": max(
                1, int(knowledge_session.get("knowledge_point_count") or 1)
            ),
        }
        practice_mode = str(knowledge_session.get("practice_mode") or "knowledge_point")
    else:
        return {
            "request_id": request_id,
            "status": "unavailable",
            "practice_mode": "general",
            "projection_pending_count": 0,
            "scope": None,
            "chapter": None,
            "touched_knowledge_point_count": 0,
            "points": [],
        }

    if not isinstance(knowledge_session, dict):
        # Scope is durable, but Stage-5 mastery baselines live in the canonical
        # replay response. A damaged/legacy response must not fabricate deltas.
        return {
            "request_id": request_id,
            "status": "unavailable",
            "practice_mode": practice_mode,
            "projection_pending_count": 0,
            "scope": scope,
            "chapter": None,
            "touched_knowledge_point_count": 0,
            "points": [],
        }
    records = await _load_session_records(db, user_id=user_id, response=response)
    pending_count = sum(
        1 for record in records if str(record.projection_state) == "pending"
    )
    if pending_count:
        return {
            "request_id": request_id,
            "status": "processing",
            "practice_mode": practice_mode,
            "projection_pending_count": pending_count,
            "scope": scope,
            "chapter": None,
            "touched_knowledge_point_count": 0,
            "points": [],
        }

    revision_ids = [
        int(record.question_version_id)
        for record in records
        if record.question_version_id
    ]
    qv_to_kps: dict[int, set[int]] = defaultdict(set)
    kp_names: dict[int, str] = {}
    root_id = int(scope["root_knowledge_point_id"])

    baseline = (
        knowledge_session.get("_baseline")
        if isinstance(knowledge_session.get("_baseline"), dict)
        else {}
    )
    baseline_points = {}
    for item in baseline.get("points") or []:
        if not isinstance(item, list) or len(item) < 4:
            continue
        kp_id = int(item[0] or 0)
        if kp_id > 0:
            baseline_points[kp_id] = {
                "mastery": item[1],
                "confidence": item[2],
                "attempt_count": int(item[3] or 0),
            }
    baseline_ids = set(baseline_points)

    if revision_ids and baseline_ids:
        mapping_rows = (
            await db.execute(
                select(
                    QuestionVersionKnowledgePoint.question_version_id,
                    KnowledgePoint.id,
                    KnowledgePoint.name,
                )
                .join(
                    KnowledgePoint,
                    QuestionVersionKnowledgePoint.knowledge_point_id
                    == KnowledgePoint.id,
                )
                .where(
                    QuestionVersionKnowledgePoint.question_version_id.in_(revision_ids),
                    QuestionVersionKnowledgePoint.knowledge_point_id.in_(baseline_ids),
                    KnowledgePoint.is_active.is_(True),
                )
            )
        ).all()
        for revision_id, kp_id, name in mapping_rows:
            qv_to_kps[int(revision_id)].add(int(kp_id))
            kp_names[int(kp_id)] = str(name)

    stats: dict[int, dict[str, int]] = defaultdict(
        lambda: {"question_count": 0, "correct_count": 0, "wrong_count": 0}
    )
    for record in records:
        for kp_id in qv_to_kps.get(int(record.question_version_id), set()):
            stats[kp_id]["question_count"] += 1
            if bool(record.is_correct):
                stats[kp_id]["correct_count"] += 1
            else:
                stats[kp_id]["wrong_count"] += 1

    touched_ids = sorted(stats)
    current_states: dict[int, UserKnowledgeState] = {}
    if touched_ids:
        state_rows = (
            await db.scalars(
                select(UserKnowledgeState).where(
                    UserKnowledgeState.user_id == user_id,
                    UserKnowledgeState.knowledge_point_id.in_(touched_ids),
                )
            )
        ).all()
        current_states = {int(state.knowledge_point_id): state for state in state_rows}

    points = []
    for kp_id in touched_ids:
        current = current_states.get(kp_id)
        before = baseline_points.get(kp_id) or {}
        after_mastery = (
            round(float(current.mastery_score), 1)
            if current is not None
            and int(current.attempt_count or 0) > 0
            and current.mastery_score is not None
            else None
        )
        before_mastery = _number_or_none(before.get("mastery"))
        point_stats = stats[kp_id]
        points.append(
            {
                "knowledge_point_id": kp_id,
                "name": kp_names.get(kp_id) or f"知识点 {kp_id}",
                **point_stats,
                "mastery_before": before_mastery,
                "mastery_after": after_mastery,
                "mastery_delta": _delta(before_mastery, after_mastery),
                "confidence_after": round(float(current.confidence or 0.0), 3)
                if current is not None
                else 0.0,
                "status_after": _state_status(current),
            }
        )

    # Put unresolved/weak points first, then the largest positive/negative change.
    status_rank = {
        "weak": 0,
        "insufficient": 1,
        "no_data": 2,
        "developing": 3,
        "good": 4,
        "mastered": 5,
    }
    points.sort(
        key=lambda item: (
            status_rank.get(str(item.get("status_after")), 9),
            -(int(item.get("wrong_count") or 0)),
            -abs(float(item.get("mastery_delta") or 0.0)),
            int(item["knowledge_point_id"]),
        )
    )
    points = points[:_MAX_SUMMARY_POINTS]

    from app.services import knowledge_map_service

    root_detail = await knowledge_map_service.get_point_detail(db, user_id, root_id)
    root_baseline = (
        baseline.get("root") if isinstance(baseline.get("root"), list) else None
    )
    chapter = None
    if root_detail is not None:
        is_chapter = bool(scope["include_descendants"])
        after_mastery = (
            root_detail.get("subtree_mastery_score")
            if is_chapter
            else root_detail.get("mastery_score")
        )
        after_coverage = (
            float(root_detail.get("subtree_coverage_ratio", 0.0) or 0.0)
            if is_chapter
            else (
                1.0
                if root_detail.get("status") not in {"no_data", "insufficient"}
                else 0.0
            )
        )
        before_mastery = (
            root_baseline[0] if root_baseline and len(root_baseline) > 0 else None
        )
        before_coverage = (
            float(root_baseline[1] or 0.0)
            if root_baseline and len(root_baseline) > 1
            else 0.0
        )
        before_weak = (
            int(root_baseline[2] or 0)
            if root_baseline and len(root_baseline) > 2
            else 0
        )
        before_reliable = (
            int(root_baseline[3] or 0)
            if root_baseline and len(root_baseline) > 3
            else 0
        )
        trainable = (
            int(root_detail.get("subtree_trainable_knowledge_points", 0) or 0)
            if is_chapter
            else (
                1 if int(root_detail.get("trainable_question_count", 0) or 0) > 0 else 0
            )
        )
        chapter = {
            "root_knowledge_point_id": root_id,
            "root_name": str(scope["root_name"] or root_detail.get("name") or ""),
            "mastery_before": _number_or_none(before_mastery),
            "mastery_after": _number_or_none(after_mastery),
            "mastery_delta": _delta(before_mastery, after_mastery),
            "coverage_before": round(before_coverage, 4),
            "coverage_after": round(after_coverage, 4),
            "weak_before": before_weak,
            "weak_after": int(root_detail.get("subtree_weak_knowledge_points", 0) or 0)
            if is_chapter
            else (1 if root_detail.get("status") == "weak" else 0),
            "reliable_before": before_reliable,
            "reliable_after": int(
                root_detail.get("subtree_reliable_knowledge_points", 0) or 0
            )
            if is_chapter
            else (
                1 if root_detail.get("status") not in {"no_data", "insufficient"} else 0
            ),
            "trainable_knowledge_points": trainable,
        }

    return {
        "request_id": request_id,
        "status": "ready",
        "practice_mode": practice_mode,
        "projection_pending_count": 0,
        "scope": scope,
        "chapter": chapter,
        "touched_knowledge_point_count": len(touched_ids),
        "points": points,
    }
