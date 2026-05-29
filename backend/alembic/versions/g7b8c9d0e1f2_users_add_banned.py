"""add users banned fields

Revision ID: g7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-05-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("is_banned", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("banned_reason", sa.String(length=256), nullable=True))
        batch_op.add_column(sa.Column("banned_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("banned_by", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_users_banned_by_admin_users", "admin_users", ["banned_by"], ["id"])

    op.create_index(op.f("ix_users_is_banned"), "users", ["is_banned"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_is_banned"), table_name="users")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("fk_users_banned_by_admin_users", type_="foreignkey")
        batch_op.drop_column("banned_by")
        batch_op.drop_column("banned_at")
        batch_op.drop_column("banned_reason")
        batch_op.drop_column("is_banned")
