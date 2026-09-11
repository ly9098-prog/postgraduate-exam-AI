"""add durable reservations for concurrent sequential starts

Revision ID: s408seq20260911
Revises: s408outbox20260910
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "s408seq20260911"
down_revision = "s408outbox20260910"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "sequential_reservations" in inspector.get_table_names():
        return
    op.create_table(
        "sequential_reservations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("scope_key", sa.String(length=64), nullable=False),
        sa.Column("start_request_id", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "subject_id",
            "scope_key",
            "question_id",
            name="uq_sequential_reservation_question",
        ),
    )
    op.create_index(
        "ix_sequential_reservations_lookup",
        "sequential_reservations",
        ["user_id", "subject_id", "scope_key", "expires_at"],
    )
    op.create_index(
        "ix_sequential_reservations_request",
        "sequential_reservations",
        ["user_id", "start_request_id"],
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "sequential_reservations" not in inspector.get_table_names():
        return
    op.drop_index("ix_sequential_reservations_request", table_name="sequential_reservations")
    op.drop_index("ix_sequential_reservations_lookup", table_name="sequential_reservations")
    op.drop_table("sequential_reservations")
