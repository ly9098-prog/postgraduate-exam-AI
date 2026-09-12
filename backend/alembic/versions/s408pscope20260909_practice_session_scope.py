"""persist immutable semantic scope on practice_sessions

Revision ID: s408pscope20260909
Revises: s408stability20260907, s408cards20260907
Create Date: 2026-09-09

The existing ``mode`` column describes the question-selection algorithm.  These
columns persist a separate, server-signed semantic scope (knowledge point/chapter)
for reporting, history and future recommendation attribution.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "s408pscope20260909"
down_revision: Union[str, Sequence[str], None] = (
    "s408stability20260907",
    "s408cards20260907",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def _index_names(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {str(index.get("name")) for index in inspector.get_indexes(table) if index.get("name")}


def _positive_int(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _legacy_scope_snapshot(response, subject_id):
    """Backfill the subset recoverable from Stage-5 submission_response JSON."""
    if not isinstance(response, dict):
        return None
    knowledge_session = response.get("knowledge_session")
    if not isinstance(knowledge_session, dict):
        return None

    root_id = _positive_int(knowledge_session.get("root_knowledge_point_id"))
    practice_mode = str(knowledge_session.get("practice_mode") or "")
    if root_id is None or practice_mode not in {"knowledge_point", "knowledge_chapter"}:
        return None

    served_ids = []
    baseline = knowledge_session.get("_baseline")
    if isinstance(baseline, dict):
        seen = set()
        for item in baseline.get("points") or []:
            if not isinstance(item, list) or not item:
                continue
            kp_id = _positive_int(item[0])
            if kp_id is None or kp_id in seen:
                continue
            seen.add(kp_id)
            served_ids.append(kp_id)

    resolved_count = _positive_int(knowledge_session.get("knowledge_point_count")) or 1
    return {
        "v": 1,
        "source_context_version": 1,
        "practice_mode": practice_mode,
        "subject_id": _positive_int(subject_id),
        "syllabus_version_id": None,
        "root_knowledge_point_id": root_id,
        "root_name": str(knowledge_session.get("root_name") or ""),
        "include_descendants": bool(knowledge_session.get("include_descendants")),
        # Stage 5 did not persist the full resolved id set in submission_response.
        "resolved_knowledge_point_ids": [],
        "served_knowledge_point_ids": served_ids,
        "resolved_knowledge_point_count": resolved_count,
        "served_knowledge_point_count": len(served_ids),
        "resolved_ids_complete": False,
        "served_ids_complete": bool(served_ids),
    }


def upgrade() -> None:
    columns = _column_names("practice_sessions")
    if not columns:
        raise RuntimeError("practice_sessions table is missing; run prior migrations first")

    if "scope_type" not in columns:
        op.add_column(
            "practice_sessions",
            sa.Column("scope_type", sa.String(length=32), nullable=True),
        )
    if "scope_root_knowledge_point_id" not in columns:
        op.add_column(
            "practice_sessions",
            sa.Column("scope_root_knowledge_point_id", sa.Integer(), nullable=True),
        )
    if "scope_snapshot" not in columns:
        op.add_column(
            "practice_sessions",
            sa.Column("scope_snapshot", sa.JSON(), nullable=True),
        )

    if "ix_practice_sessions_user_scope_finished" not in _index_names("practice_sessions"):
        op.create_index(
            "ix_practice_sessions_user_scope_finished",
            "practice_sessions",
            ["user_id", "scope_type", "scope_root_knowledge_point_id", "finished_at"],
            unique=False,
        )

    # Rolling-deployment backfill: Stage-5 sessions may already contain a signed
    # knowledge_session snapshot inside submission_response.  Recover what can be
    # known without re-resolving today's mutable syllabus.  Full resolved ids are
    # intentionally left unavailable for those historical rows.
    bind = op.get_bind()
    sessions = sa.table(
        "practice_sessions",
        sa.column("id", sa.Integer()),
        sa.column("subject_id", sa.Integer()),
        sa.column("submission_response", sa.JSON()),
        sa.column("scope_type", sa.String(length=32)),
        sa.column("scope_root_knowledge_point_id", sa.Integer()),
        sa.column("scope_snapshot", sa.JSON()),
    )
    rows = bind.execute(
        sa.select(
            sessions.c.id,
            sessions.c.subject_id,
            sessions.c.submission_response,
        ).where(sessions.c.scope_snapshot.is_(None))
    ).mappings().all()
    for row in rows:
        snapshot = _legacy_scope_snapshot(row["submission_response"], row["subject_id"])
        if snapshot is None:
            continue
        bind.execute(
            sessions.update()
            .where(sessions.c.id == row["id"])
            .values(
                scope_type=snapshot["practice_mode"],
                scope_root_knowledge_point_id=snapshot["root_knowledge_point_id"],
                scope_snapshot=snapshot,
            )
        )


def downgrade() -> None:
    columns = _column_names("practice_sessions")
    indexes = _index_names("practice_sessions")
    if "ix_practice_sessions_user_scope_finished" in indexes:
        op.drop_index("ix_practice_sessions_user_scope_finished", table_name="practice_sessions")
    if "scope_snapshot" in columns:
        op.drop_column("practice_sessions", "scope_snapshot")
    if "scope_root_knowledge_point_id" in columns:
        op.drop_column("practice_sessions", "scope_root_knowledge_point_id")
    if "scope_type" in columns:
        op.drop_column("practice_sessions", "scope_type")
