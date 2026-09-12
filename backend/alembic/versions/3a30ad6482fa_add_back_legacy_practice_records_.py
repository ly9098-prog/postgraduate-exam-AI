"""add back legacy practice_records columns for ORM compatibility

Revision ID: 3a30ad6482fa
Revises: p5_7_drop_batch_job_subject
Create Date: 2026-06-30 23:23:10.443077

Migration 7386c399b670 dropped the legacy batch columns from practice_records,
but the current ORM model (practice_record.py) re-declares them to prevent
Alembic autogenerate from emitting DROP COLUMN.  This migration re-adds them
so that ORM queries against PracticeRecord do not fail with
"no such column: practice_records.mode".
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "3a30ad6482fa"
down_revision: Union[str, Sequence[str], None] = "p5_7_drop_batch_job_subject"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = [c["name"] for c in inspector.get_columns(table)]
    return column in cols


LEGACY_COLS = [
    ("mode", sa.String(16), True, None),
    ("question_ids", sa.Text, True, None),
    ("answers", sa.Text, True, None),
    ("correct_count", sa.Integer, True, None),
    ("wrong_count", sa.Integer, True, None),
    ("duration_sec", sa.Integer, True, None),
    ("started_at", sa.DateTime, True, None),
    ("finished_at", sa.DateTime, True, None),
]


def upgrade() -> None:
    for name, typ, nullable, server_default in LEGACY_COLS:
        if not _has_column("practice_records", name):
            op.add_column(
                "practice_records",
                sa.Column(name, typ, nullable=nullable, server_default=server_default),
            )


def downgrade() -> None:
    for name, _, _, _ in LEGACY_COLS:
        if _has_column("practice_records", name):
            op.drop_column("practice_records", name)
