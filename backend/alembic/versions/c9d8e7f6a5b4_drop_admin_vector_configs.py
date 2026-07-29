"""drop admin_vector_configs table (migrated to admin_ai_configs)

Revision ID: c9d8e7f6a5b4
Revises: b7c8d9e0f1a2
Create Date: 2026-07-29

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c9d8e7f6a5b4"
down_revision: Union[str, Sequence[str], None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE admin_ai_configs SET config_value = 'all' WHERE config_key = 'vector_mode' AND config_value = '1'")
    op.drop_table("admin_vector_configs")


def downgrade() -> None:
    op.create_table(
        "admin_vector_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vector_enabled", sa.Boolean(), nullable=False),
        sa.Column("vector_mode", sa.String(length=16), nullable=False),
        sa.Column("vector_allowlist", sa.Text(), nullable=False),
        sa.Column("vector_cache_ttl_sec", sa.Integer(), nullable=False),
        sa.Column("vector_top_k", sa.Integer(), nullable=False),
        sa.Column("vector_similarity_threshold", sa.Float(), nullable=False),
        sa.Column("embedding_provider", sa.String(length=64), nullable=False),
        sa.Column("embedding_api_key_encrypted", sa.String(length=512), nullable=True),
        sa.Column("embedding_base_url", sa.String(length=256), nullable=False),
        sa.Column("embedding_model", sa.String(length=128), nullable=False),
        sa.Column("embedding_dim", sa.Integer(), nullable=False),
        sa.Column("embedding_timeout", sa.Integer(), nullable=False),
        sa.Column("embedding_batch_size", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
