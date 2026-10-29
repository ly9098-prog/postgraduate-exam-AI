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
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import (  # noqa: F401 -- dynamic projection ports
    serialize_utc_datetime,
    utcnow,
)
from app.models.practice_session import PracticeSession
from app.services import knowledge_diagnosis_projection as _projection
from app.services import knowledge_map_service
from app.services.knowledge_diagnosis_logic import (
    _accuracy,  # noqa: F401 -- dynamic projection port
    _float,  # noqa: F401 -- dynamic projection port
    _int,  # noqa: F401 -- dynamic projection port
    _scope_coverage,  # noqa: F401 -- dynamic projection port
    aggregate_session_stats,
    rank_chapter_recommendations,
)
from app.services.practice.session_scope import (
    public_practice_session_scope,  # noqa: F401
)

_MAX_RECENT_SESSIONS = 5


def _diagnosis_port(name: str) -> Any:
    return globals()[name]


async def _load_chapter_sessions(
    db: AsyncSession, *, user_id: int, subject_id: int, since: datetime
) -> list[dict]:
    rows = (
        await db.execute(
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
        )
    ).all()
    return _projection.project_chapter_sessions(rows, ports=_diagnosis_port)


def _root_chapter_reports(
    nodes: list[dict], chapter_stats: dict[int, dict]
) -> list[dict]:
    return _projection._root_chapter_reports(
        nodes, chapter_stats, ports=_diagnosis_port
    )


async def get_knowledge_diagnosis(
    db: AsyncSession, user_id: int, subject_id: int, *, days: int = 30
) -> dict | None:
    subject_map = await knowledge_map_service.get_subject_map(db, user_id, subject_id)
    if subject_map is None:
        return None
    now = utcnow()
    since = now - timedelta(days=max(1, min(int(days), 365)))
    nodes = list(subject_map.get("nodes") or [])
    sessions = await _load_chapter_sessions(
        db, user_id=user_id, subject_id=subject_id, since=since
    )
    chapter_stats, totals = aggregate_session_stats(
        nodes, sessions, recent_since=now - timedelta(days=7)
    )
    recommendations = rank_chapter_recommendations(
        nodes, chapter_stats, subject_id=subject_id, now=now
    )
    chapters = _root_chapter_reports(nodes, chapter_stats)
    subject = subject_map["subject"]
    recent_sessions = _projection.recent_session_reports(
        sessions, ports=_diagnosis_port
    )
    report = _projection.diagnosis_report(
        chapters, totals, subject, days, ports=_diagnosis_port
    )
    return _projection.diagnosis_response(
        subject_map,
        subject,
        now,
        recommendations,
        report,
        chapters,
        recent_sessions,
        ports=_diagnosis_port,
    )
