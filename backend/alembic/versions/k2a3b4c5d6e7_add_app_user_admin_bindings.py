"""add app user admin bindings

Revision ID: k2a3b4c5d6e7
Revises: j1f2a3b4c5d6
Create Date: 2026-05-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "k2a3b4c5d6e7"
down_revision: Union[str, Sequence[str], None] = "j1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_user_admin_bindings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("admin_user_id", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["admin_user_id"], ["admin_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["admin_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("admin_user_id", name="uq_app_user_admin_bindings_admin_user_id"),
        sa.UniqueConstraint("user_id", name="uq_app_user_admin_bindings_user_id"),
    )
    op.create_index(op.f("ix_app_user_admin_bindings_admin_user_id"), "app_user_admin_bindings", ["admin_user_id"], unique=False)
    op.create_index(op.f("ix_app_user_admin_bindings_user_id"), "app_user_admin_bindings", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_app_user_admin_bindings_user_id"), table_name="app_user_admin_bindings")
    op.drop_index(op.f("ix_app_user_admin_bindings_admin_user_id"), table_name="app_user_admin_bindings")
    op.drop_table("app_user_admin_bindings")
