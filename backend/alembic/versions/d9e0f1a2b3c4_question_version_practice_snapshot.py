"""add full practice snapshot fields to question versions

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-09-04
"""

from alembic import op
import sqlalchemy as sa


revision = "d9e0f1a2b3c4"
down_revision = "c8d9e0f1a2b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("question_versions", sa.Column("subject_id", sa.Integer(), nullable=True))
    op.add_column("question_versions", sa.Column("question_type", sa.String(length=32), nullable=True))
    op.add_column("question_versions", sa.Column("image_url", sa.JSON(), nullable=True))
    op.add_column("question_versions", sa.Column("is_active", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("question_versions", "is_active")
    op.drop_column("question_versions", "image_url")
    op.drop_column("question_versions", "question_type")
    op.drop_column("question_versions", "subject_id")
