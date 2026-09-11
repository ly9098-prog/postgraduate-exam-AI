"""Durable semantic scope for a completed practice session.

``PracticeSession.mode`` describes the question-selection algorithm (random/smart/etc.).
This module captures a different concern: *why* the batch was issued and which
knowledge-point range it represented at issue time.

The snapshot is built only from the server-signed practice batch token.  Client
session metadata never controls it, so a submit cannot relabel a random batch as a
knowledge chapter batch.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


_SCOPE_SNAPSHOT_VERSION = 1
_SCOPE_TYPES = frozenset({"knowledge_point", "knowledge_chapter"})


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _ordered_positive_ids(values: Any) -> list[int]:
    if not isinstance(values, (list, tuple)):
        return []
    result: list[int] = []
    seen: set[int] = set()
    for value in values:
        parsed = _positive_int(value)
        if parsed is None or parsed in seen:
            continue
        seen.add(parsed)
        result.append(parsed)
    return result


def _legacy_served_ids(context: dict) -> list[int]:
    """Recover issued/touched KP ids from a Stage-5 v1 context.

    Stage 5 stored per-point baselines only for KPs represented by the immutable
    revisions in the issued batch.  That makes them a reliable served-scope fallback
    for tokens already in flight when durable session scope is deployed.
    """
    baseline = context.get("baseline")
    if not isinstance(baseline, dict):
        return []
    ids: list[int] = []
    for item in baseline.get("points") or []:
        if not isinstance(item, list) or not item:
            continue
        parsed = _positive_int(item[0])
        if parsed is not None:
            ids.append(parsed)
    return _ordered_positive_ids(ids)


def build_practice_session_scope(
    context: dict | None,
    *,
    fallback_subject_id: int | None = None,
) -> dict | None:
    """Convert signed knowledge context into an immutable session scope snapshot.

    New context versions contain the exact resolved and served knowledge-point ids.
    Older Stage-5 tokens contain only ``scope_count`` plus the per-point baseline;
    those are accepted for rolling deployment and marked as a partial legacy scope.
    """
    if not isinstance(context, dict):
        return None

    root_id = _positive_int(context.get("root_id"))
    if root_id is None:
        return None

    practice_mode = str(context.get("practice_mode") or "knowledge_point")
    if practice_mode not in _SCOPE_TYPES:
        return None

    subject_id = _positive_int(context.get("subject_id")) or _positive_int(
        fallback_subject_id
    )
    syllabus_version_id = _positive_int(context.get("syllabus_version_id"))

    resolved_ids = _ordered_positive_ids(context.get("scope_ids"))
    declared_resolved_count = _positive_int(context.get("scope_count")) or 1
    resolved_ids_complete = (
        bool(resolved_ids) and len(resolved_ids) == declared_resolved_count
    )
    if resolved_ids and root_id not in resolved_ids:
        # A server-issued exact scope must always include its root.  Treat a malformed
        # context as partial rather than inventing membership.
        resolved_ids_complete = False

    served_ids = _ordered_positive_ids(context.get("served_ids"))
    if not served_ids:
        served_ids = _legacy_served_ids(context)
    served_ids_complete = bool(context.get("served_ids") is not None) or bool(
        served_ids
    )

    if resolved_ids_complete:
        resolved_set = set(resolved_ids)
        # Exact snapshots never retain a served id outside the resolved hierarchy.
        served_ids = [kp_id for kp_id in served_ids if kp_id in resolved_set]

    snapshot = {
        "v": _SCOPE_SNAPSHOT_VERSION,
        "source_context_version": int(context.get("v") or 1),
        "practice_mode": practice_mode,
        "subject_id": subject_id,
        "syllabus_version_id": syllabus_version_id,
        "root_knowledge_point_id": root_id,
        "root_name": str(context.get("root_name") or ""),
        "include_descendants": bool(context.get("include_descendants")),
        "resolved_knowledge_point_ids": resolved_ids,
        "served_knowledge_point_ids": served_ids,
        "resolved_knowledge_point_count": declared_resolved_count,
        "served_knowledge_point_count": len(served_ids),
        "resolved_ids_complete": resolved_ids_complete,
        "served_ids_complete": served_ids_complete,
    }
    return snapshot


def public_practice_session_scope(snapshot: dict | None) -> dict | None:
    """Return the stable, non-baseline scope payload safe for APIs/reports."""
    if not isinstance(snapshot, dict):
        return None
    root_id = _positive_int(snapshot.get("root_knowledge_point_id"))
    practice_mode = str(snapshot.get("practice_mode") or "")
    if root_id is None or practice_mode not in _SCOPE_TYPES:
        return None

    resolved_ids = _ordered_positive_ids(snapshot.get("resolved_knowledge_point_ids"))
    served_ids = _ordered_positive_ids(snapshot.get("served_knowledge_point_ids"))
    return {
        "practice_mode": practice_mode,
        "subject_id": _positive_int(snapshot.get("subject_id")),
        "syllabus_version_id": _positive_int(snapshot.get("syllabus_version_id")),
        "root_knowledge_point_id": root_id,
        "root_name": str(snapshot.get("root_name") or ""),
        "include_descendants": bool(snapshot.get("include_descendants")),
        "resolved_knowledge_point_ids": resolved_ids,
        "served_knowledge_point_ids": served_ids,
        "resolved_knowledge_point_count": max(
            1,
            int(
                snapshot.get("resolved_knowledge_point_count") or len(resolved_ids) or 1
            ),
        ),
        "served_knowledge_point_count": max(
            0,
            int(snapshot.get("served_knowledge_point_count") or len(served_ids)),
        ),
        "resolved_ids_complete": bool(snapshot.get("resolved_ids_complete")),
        "served_ids_complete": bool(snapshot.get("served_ids_complete")),
    }


async def get_practice_session_scope(
    db: AsyncSession,
    *,
    user_id: int,
    request_id: str,
) -> tuple[bool, dict | None]:
    """Read a persisted session scope without loading the large replay response."""
    normalized_request_id = str(request_id or "").strip()
    if not normalized_request_id:
        return False, None

    from app.models.practice_session import PracticeSession

    row = (
        await db.execute(
            select(
                PracticeSession.scope_type,
                PracticeSession.scope_root_knowledge_point_id,
                PracticeSession.scope_snapshot,
            ).where(
                PracticeSession.user_id == int(user_id),
                PracticeSession.request_id == normalized_request_id,
            )
        )
    ).one_or_none()
    if row is None:
        return False, None

    scope = public_practice_session_scope(row.scope_snapshot)
    if scope is None:
        return True, None

    # Denormalized query columns are integrity sentinels.  Fail closed if they no
    # longer agree with the immutable JSON snapshot.
    if str(row.scope_type or "") != str(scope["practice_mode"]):
        return True, None
    if int(row.scope_root_knowledge_point_id or 0) != int(
        scope["root_knowledge_point_id"]
    ):
        return True, None
    return True, scope
