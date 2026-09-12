"""relax knowledge_points (subject_id, normalized_name) uniqueness

The 408 Markdown syllabus reuses one title at both a chapter/section and its
child (e.g. chapter "第4章 指令系统" and section "4.1 指令系统" both display as
"指令系统"). The reconstructed catalog keeps both nodes; they are distinguished
by id, so (subject_id, normalized_name) must not be a unique key. Drop the
unique constraint and keep an equivalent non-unique lookup index.

Revision ID: r408kpunique20260912
Revises: s408seq20260911
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "r408kpunique20260912"
down_revision = "s408seq20260911"
branch_labels = None
depends_on = None

_TABLE = "knowledge_points"
_CONSTRAINT = "uq_kp_subject_id_normalized_name"
_INDEX = "ix_kp_subject_normalized_name"


def _has_constraint(name: str) -> bool:
    conn = op.get_bind()
    if conn.dialect.name == "sqlite":
        sql = conn.execute(
            sa.text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:t"),
            {"t": _TABLE},
        ).scalar()
        return bool(sql) and name in sql
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE table_name=:t AND constraint_name=:c"
        ),
        {"t": _TABLE, "c": name},
    ).scalar()
    return row is not None


def _has_index(name: str) -> bool:
    conn = op.get_bind()
    if conn.dialect.name == "sqlite":
        row = conn.execute(
            sa.text("SELECT 1 FROM sqlite_master WHERE type='index' AND name=:n"),
            {"n": name},
        ).scalar()
        return row is not None
    row = conn.execute(
        sa.text("SELECT 1 FROM pg_indexes WHERE indexname=:n"), {"n": name}
    ).scalar()
    return row is not None


def upgrade() -> None:
    # SQLite cannot ALTER TABLE DROP CONSTRAINT; batch mode recreates the table.
    if _has_constraint(_CONSTRAINT):
        with op.batch_alter_table(_TABLE) as batch_op:
            batch_op.drop_constraint(_CONSTRAINT, type_="unique")
    if not _has_index(_INDEX):
        op.create_index(_INDEX, _TABLE, ["subject_id", "normalized_name"])


def downgrade() -> None:
    if _has_index(_INDEX):
        op.drop_index(_INDEX, table_name=_TABLE)
    if not _has_constraint(_CONSTRAINT):
        with op.batch_alter_table(_TABLE) as batch_op:
            batch_op.create_unique_constraint(
                _CONSTRAINT, ["subject_id", "normalized_name"]
            )
