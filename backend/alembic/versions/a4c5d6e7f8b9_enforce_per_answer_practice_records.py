"""enforce the per-answer practice_records schema

Revision ID: a4c5d6e7f8b9
Revises: f3b4c5d6e7a8
Create Date: 2026-09-05

``practice_records`` is permanently a one-answer-per-row event table. Batch and
session aggregates belong to ``practice_sessions``. This migration removes any
retired batch columns that might still exist on an upgraded database and
verifies the columns required by the current model.

The migration deliberately does *not* recreate legacy columns on downgrade.
Those columns no longer have supported application semantics.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "a4c5d6e7f8b9"
down_revision = "f3b4c5d6e7a8"
branch_labels = None
depends_on = None

RETIRED_BATCH_COLUMNS = (
    "question_ids",
    "answers",
    "correct_count",
    "wrong_count",
    "duration_sec",
    "started_at",
    "finished_at",
)

REQUIRED_PER_ANSWER_COLUMNS = frozenset({
    "id",
    "user_id",
    "question_id",
    "question_version_id",
    "subject_id",
    "question_type",
    "user_answer",
    "is_correct",
    "used_time",
    "answered_at",
    "created_at",
    "projection_state",
    "mode",
})


def _columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if "practice_records" not in inspector.get_table_names():
        raise RuntimeError("practice_records table is missing")
    return {
        str(column["name"])
        for column in inspector.get_columns("practice_records")
    }


def upgrade() -> None:
    existing = _columns()
    missing = sorted(REQUIRED_PER_ANSWER_COLUMNS - existing)
    if missing:
        raise RuntimeError(
            "practice_records is missing required per-answer columns: "
            + ", ".join(missing)
        )

    retired_present = [name for name in RETIRED_BATCH_COLUMNS if name in existing]
    if not retired_present:
        return

    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("practice_records", recreate="auto") as batch:
            for name in retired_present:
                batch.drop_column(name)
    else:
        for name in retired_present:
            op.drop_column("practice_records", name)


def downgrade() -> None:
    raise RuntimeError(
        "Retired practice_records batch columns are intentionally unsupported. "
        "Restore a database backup instead of downgrading this revision."
    )
