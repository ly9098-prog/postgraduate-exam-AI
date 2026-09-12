"""add 408 long-horizon study plan and daily snapshots

Revision ID: s408plan20260907
Revises: s408coverage20260907
Create Date: 2026-09-07
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "s408plan20260907"
down_revision: Union[str, Sequence[str], None] = "s408coverage20260907"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "study_plans",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("daily_minutes", sa.Integer(), nullable=False, server_default="90"),
        sa.Column("weekly_days", sa.Integer(), nullable=False, server_default="6"),
        sa.Column("priority_mode", sa.String(length=16), nullable=False, server_default="balanced"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", name="uq_study_plans_user"),
        sa.CheckConstraint(
            "daily_minutes >= 15 AND daily_minutes <= 720",
            name="ck_study_plans_daily_minutes",
        ),
        sa.CheckConstraint(
            "weekly_days >= 1 AND weekly_days <= 7",
            name="ck_study_plans_weekly_days",
        ),
        sa.CheckConstraint(
            "priority_mode IN ('balanced','review','weakness','new','exam')",
            name="ck_study_plans_priority_mode",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_study_plans_revision_positive"),
    )
    op.create_index("ix_study_plans_user_id", "study_plans", ["user_id"], unique=False)
    op.create_index(
        "ix_study_plans_active_target",
        "study_plans",
        ["is_active", "target_date"],
        unique=False,
    )

    op.create_table(
        "study_plan_days",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("plan_revision", sa.Integer(), nullable=False),
        sa.Column("plan_date", sa.Date(), nullable=False),
        sa.Column("target_minutes", sa.Integer(), nullable=False),
        sa.Column("is_rest_day", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("allocation_json", sa.JSON(), nullable=False),
        sa.Column("basis_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["plan_id"], ["study_plans.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("plan_id", "plan_date", name="uq_study_plan_days_plan_date"),
        sa.CheckConstraint("plan_revision >= 1", name="ck_study_plan_days_revision_positive"),
        sa.CheckConstraint("target_minutes >= 0", name="ck_study_plan_days_target_nonnegative"),
    )
    op.create_index("ix_study_plan_days_plan_id", "study_plan_days", ["plan_id"], unique=False)
    op.create_index(
        "ix_study_plan_days_plan_date",
        "study_plan_days",
        ["plan_id", "plan_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_study_plan_days_plan_date", table_name="study_plan_days")
    op.drop_index("ix_study_plan_days_plan_id", table_name="study_plan_days")
    op.drop_table("study_plan_days")
    op.drop_index("ix_study_plans_active_target", table_name="study_plans")
    op.drop_index("ix_study_plans_user_id", table_name="study_plans")
    op.drop_table("study_plans")
