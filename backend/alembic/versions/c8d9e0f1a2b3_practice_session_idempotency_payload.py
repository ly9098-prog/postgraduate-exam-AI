"""store practice submit idempotency payload on practice_sessions

Revision ID: c8d9e0f1a2b3
Revises: b6c7d8e9f0a1
Create Date: 2026-09-04 00:00:00.000000

The previous application release temporarily stored a batch-submit fingerprint
and canonical response in legacy PracticeRecord text columns.  The session row
is the correct owner of this state: it exists once per submitted batch and also
covers a batch where every question is skipped.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8d9e0f1a2b3"
down_revision: Union[str, Sequence[str], None] = "b6c7d8e9f0a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    columns = _column_names("practice_sessions")
    if not columns:
        # The base practice_sessions migration should already have run on this
        # branch.  Do not silently create a partial table if an operator skipped
        # historical migrations.
        raise RuntimeError("practice_sessions table is missing; run prior migrations first")

    if "submission_payload_hash" not in columns:
        op.add_column(
            "practice_sessions",
            sa.Column("submission_payload_hash", sa.String(length=64), nullable=True),
        )
    if "submission_response" not in columns:
        op.add_column(
            "practice_sessions",
            sa.Column("submission_response", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    columns = _column_names("practice_sessions")
    if "submission_response" in columns:
        op.drop_column("practice_sessions", "submission_response")
    if "submission_payload_hash" in columns:
        op.drop_column("practice_sessions", "submission_payload_hash")
