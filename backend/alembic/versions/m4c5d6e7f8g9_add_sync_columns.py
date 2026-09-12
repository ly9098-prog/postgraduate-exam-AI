"""add sync columns

Revision ID: m4c5d6e7f8g9
Revises: l3b4c5d6e7f8
Create Date: 2026-06-04 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "m4c5d6e7f8g9"
down_revision: Union[str, Sequence[str], None] = "l3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("questions", sa.Column("sync_uuid", sa.String(36), nullable=True))
    op.add_column("questions", sa.Column("sync_version", sa.Integer(), nullable=False, server_default="0"))
    op.create_index(op.f("ix_questions_sync_uuid"), "questions", ["sync_uuid"], unique=True)

    op.add_column("tags", sa.Column("sync_uuid", sa.String(36), nullable=True))
    op.create_index(op.f("ix_tags_sync_uuid"), "tags", ["sync_uuid"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_tags_sync_uuid"), table_name="tags")
    op.drop_column("tags", "sync_uuid")

    op.drop_index(op.f("ix_questions_sync_uuid"), table_name="questions")
    op.drop_column("questions", "sync_version")
    op.drop_column("questions", "sync_uuid")
