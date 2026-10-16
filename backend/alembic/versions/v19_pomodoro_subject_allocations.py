"""Persist per-session Pomodoro subject attribution.

Revision ID: v19_pomodoro_subject_allocations
Revises: v18_production_schema_reconciliation
"""

import sqlalchemy as sa

from alembic import op

revision = "v19_pomodoro_subject_allocations"
down_revision = "v18_production_schema_reconciliation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pomodoro_subject_allocations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=True),
        sa.Column("weight_basis_points", sa.Integer(), nullable=False),
        sa.Column("subject_code_snapshot", sa.String(length=32), nullable=False),
        sa.Column("subject_name_snapshot", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["pomodoro_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "weight_basis_points > 0",
            name="ck_pomodoro_allocation_weight_positive",
        ),
        sa.CheckConstraint(
            "subject_code_snapshot <> ''",
            name="ck_pomodoro_allocation_code_present",
        ),
        sa.CheckConstraint(
            "subject_name_snapshot <> ''",
            name="ck_pomodoro_allocation_name_present",
        ),
    )
    op.create_index(
        "ux_pomodoro_subject_allocations_session_subject",
        "pomodoro_subject_allocations",
        ["session_id", "subject_id"],
        unique=True,
    )
    op.create_index(
        "ix_pomodoro_subject_allocations_subject",
        "pomodoro_subject_allocations",
        ["subject_id"],
    )
    op.create_index(
        "ux_pomodoro_subject_allocations_session_code",
        "pomodoro_subject_allocations",
        ["session_id", "subject_code_snapshot"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ux_pomodoro_subject_allocations_session_code",
        table_name="pomodoro_subject_allocations",
    )
    op.drop_index(
        "ix_pomodoro_subject_allocations_subject",
        table_name="pomodoro_subject_allocations",
    )
    op.drop_index(
        "ux_pomodoro_subject_allocations_session_subject",
        table_name="pomodoro_subject_allocations",
    )
    op.drop_table("pomodoro_subject_allocations")
