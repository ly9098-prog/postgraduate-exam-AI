"""Knowledge diagnosis and chapter-practice reporting.

The service deliberately combines two *read-only* fact sources:

* ``knowledge_map_service`` for the current canonical syllabus hierarchy and
  current mastery/coverage aggregation;
* durable ``PracticeSession.scope_snapshot`` records for historical chapter
  practice intent and actual served knowledge scope.

No mastery state is persisted here.  Recommendations are reproducible read-time
projections over the current knowledge map plus immutable session history.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import serialize_utc_datetime, utcnow
from app.models.practice_session import PracticeSession
from app.services import knowledge_map_service
from app.services.knowledge_diagnosis_logic import (
    _accuracy,
    _float,
    _int,
    _scope_coverage,
    aggregate_session_stats,
    rank_chapter_recommendations,
)
from app.services.practice.session_scope import public_practice_session_scope

_MAX_RECENT_SESSIONS = 5


async def _load_chapter_sessions(
    db: AsyncSession,
    *,
    user_id: int,
    subject_id: int,
    since: datetime,
) -> list[dict]:
    rows = (await db.execute(
        select(
            PracticeSession.request_id,
            PracticeSession.scope_root_knowledge_point_id,
            PracticeSession.scope_snapshot,
            PracticeSession.question_count,
            PracticeSession.correct_count,
            PracticeSession.finished_at,
        )
        .where(
            PracticeSession.user_id == int(user_id),
            PracticeSession.subject_id == int(subject_id),
            PracticeSession.scope_type == "knowledge_chapter",
            PracticeSession.status == "completed",
            PracticeSession.finished_at >= since,
        )
        .order_by(PracticeSession.finished_at.desc(), PracticeSession.id.desc())
    )).all()

    result: list[dict] = []
    for row in rows:
        scope = public_practice_session_scope(row.scope_snapshot)
        root_id = _int(row.scope_root_knowledge_point_id)
        if scope is None or root_id <= 0:
            continue
        if _int(scope.get("root_knowledge_point_id")) != root_id:
            continue
        result.append({
            "request_id": str(row.request_id or ""),
            "root_knowledge_point_id": root_id,
            "root_name": str(scope.get("root_name") or ""),
            "served_ids": {
                _int(value)
                for value in scope.get("served_knowledge_point_ids") or []
                if _int(value) > 0
            },
            "resolved_ids": {
                _int(value)
                for value in scope.get("resolved_knowledge_point_ids") or []
                if _int(value) > 0
            },
            "served_count": max(0, _int(scope.get("served_knowledge_point_count"))),
            "resolved_count": max(0, _int(scope.get("resolved_knowledge_point_count"))),
            "question_count": _int(row.question_count),
            "correct_count": _int(row.correct_count),
            "finished_at": row.finished_at,
        })
    return result


def _root_chapter_reports(nodes: list[dict], chapter_stats: dict[int, dict]) -> list[dict]:
    reports: list[dict] = []
    for node in nodes:
        if _int(node.get("depth")) != 0:
            continue
        kp_id = _int(node.get("knowledge_point_id"))
        stat = chapter_stats.get(kp_id, {})
        question_count = _int(stat.get("question_count"))
        mastery = node.get("subtree_mastery_score")
        last_at = stat.get("last_practiced_at")
        reports.append({
            "knowledge_point_id": kp_id,
            "knowledge_point_name": str(node.get("name") or ""),
            "mastery_score": round(_float(mastery), 1) if mastery is not None else None,
            "coverage_ratio": round(max(0.0, min(1.0, _float(node.get("subtree_coverage_ratio")))), 4),
            "weak_knowledge_points": _int(node.get("subtree_weak_knowledge_points")),
            "reliable_knowledge_points": _int(node.get("subtree_reliable_knowledge_points")),
            "trainable_knowledge_points": _int(node.get("subtree_trainable_knowledge_points")),
            "session_count": _int(stat.get("session_count")),
            "last_7_days_session_count": _int(stat.get("recent_session_count")),
            "question_count": question_count,
            "correct_count": _int(stat.get("correct_count")),
            "accuracy": _accuracy(_int(stat.get("correct_count")), question_count),
            "scope_served_knowledge_point_count": _int(stat.get("scope_served_count")),
            "scope_resolved_knowledge_point_count": _int(stat.get("scope_resolved_count")),
            "scope_coverage_ratio": _scope_coverage(
                _int(stat.get("scope_served_count")),
                _int(stat.get("scope_resolved_count")),
            ),
            "last_practiced_at": serialize_utc_datetime(last_at) if isinstance(last_at, datetime) else None,
        })
    return reports


async def get_knowledge_diagnosis(
    db: AsyncSession,
    user_id: int,
    subject_id: int,
    *,
    days: int = 30,
) -> dict | None:
    subject_map = await knowledge_map_service.get_subject_map(db, user_id, subject_id)
    if subject_map is None:
        return None

    now = utcnow()
    since = now - timedelta(days=max(1, min(int(days), 365)))
    nodes = list(subject_map.get("nodes") or [])
    sessions = await _load_chapter_sessions(
        db,
        user_id=user_id,
        subject_id=subject_id,
        since=since,
    )
    chapter_stats, totals = aggregate_session_stats(
        nodes,
        sessions,
        recent_since=now - timedelta(days=7),
    )
    recommendations = rank_chapter_recommendations(
        nodes,
        chapter_stats,
        subject_id=subject_id,
        now=now,
    )
    chapters = _root_chapter_reports(nodes, chapter_stats)
    subject = subject_map["subject"]
    recent_sessions = []
    for session in sessions[:_MAX_RECENT_SESSIONS]:
        question_count = _int(session.get("question_count"))
        finished_at = session.get("finished_at")
        if not isinstance(finished_at, datetime):
            continue
        recent_sessions.append({
            "request_id": str(session.get("request_id") or ""),
            "root_knowledge_point_id": _int(session.get("root_knowledge_point_id")),
            "root_name": str(session.get("root_name") or ""),
            "question_count": question_count,
            "correct_count": _int(session.get("correct_count")),
            "accuracy": _accuracy(_int(session.get("correct_count")), question_count),
            "served_knowledge_point_count": max(0, _int(session.get("served_count"))),
            "resolved_knowledge_point_count": max(0, _int(session.get("resolved_count"))),
            "scope_coverage_ratio": _scope_coverage(
                max(0, _int(session.get("served_count"))),
                max(0, _int(session.get("resolved_count"))),
            ),
            "finished_at": serialize_utc_datetime(finished_at),
        })

    practiced_root_ids = {
        chapter["knowledge_point_id"]
        for chapter in chapters
        if int(chapter["session_count"]) > 0
    }
    total_questions = _int(totals.get("question_count"))
    report = {
        "period_days": max(1, min(int(days), 365)),
        "session_count": _int(totals.get("session_count")),
        "last_7_days_session_count": _int(totals.get("recent_session_count")),
        "question_count": total_questions,
        "correct_count": _int(totals.get("correct_count")),
        "accuracy": _accuracy(_int(totals.get("correct_count")), total_questions),
        "practiced_chapter_count": len(practiced_root_ids),
        "served_knowledge_point_count": len(totals.get("served_ids") or set()),
        "scope_served_knowledge_point_count": _int(totals.get("scope_served_count")),
        "scope_resolved_knowledge_point_count": _int(totals.get("scope_resolved_count")),
        "scope_coverage_ratio": totals.get("scope_coverage_ratio"),
        "current_coverage_ratio": round(max(0.0, min(1.0, _float(subject.get("coverage_ratio")))), 4),
        "current_reliable_knowledge_points": _int(subject.get("reliable_knowledge_points")),
        "current_trainable_knowledge_points": _int(subject.get("trainable_knowledge_points")),
        "current_weak_knowledge_points": _int(subject.get("weak_knowledge_points")),
    }

    return {
        "scope": str(subject_map.get("scope") or "exam408"),
        "subject_id": int(subject["subject_id"]),
        "subject_code": str(subject["subject_code"]),
        "subject_name": str(subject["subject_name"]),
        "period_days": report["period_days"],
        "generated_at": serialize_utc_datetime(now),
        "primary_recommendation": recommendations[0] if recommendations else None,
        "recommendations": recommendations,
        "report": report,
        "chapters": chapters,
        "recent_sessions": recent_sessions,
    }
