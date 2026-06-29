"""Add admin_vector_configs table for DB-backed pgvector/embedding configuration.

Revision ID: p5_5_vector_config
Revises: p5_4_subject_id_fk
Create Date: 2026-06-29

Single-row table storing all vector search and embedding parameters.
Seeds from environment variables on first read (handled by service layer).
"""

from alembic import op
import sqlalchemy as sa

revision = "p5_5_vector_config"
down_revision = "p5_4_subject_id_fk"
branch_labels = None
depends_on = None


def _has_table(inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "admin_vector_configs"):
        op.create_table(
            "admin_vector_configs",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            # Vector Search
            sa.Column("vector_enabled", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("vector_mode", sa.String(16), nullable=False, server_default="off"),
            sa.Column("vector_allowlist", sa.Text(), nullable=False, server_default=""),
            sa.Column("vector_cache_ttl_sec", sa.Integer(), nullable=False, server_default="300"),
            sa.Column("vector_top_k", sa.Integer(), nullable=False, server_default="100"),
            sa.Column("vector_similarity_threshold", sa.Float(), nullable=False, server_default="0.15"),
            # Embedding
            sa.Column("embedding_provider", sa.String(64), nullable=False, server_default="openai_compatible"),
            sa.Column("embedding_api_key_encrypted", sa.String(512), nullable=True),
            sa.Column("embedding_base_url", sa.String(256), nullable=False, server_default=""),
            sa.Column("embedding_model", sa.String(128), nullable=False, server_default="BAAI/bge-m3"),
            sa.Column("embedding_dim", sa.Integer(), nullable=False, server_default="1024"),
            sa.Column("embedding_timeout", sa.Integer(), nullable=False, server_default="30"),
            sa.Column("embedding_batch_size", sa.Integer(), nullable=False, server_default="16"),
            # Metadata
            sa.Column("updated_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_table(inspector, "admin_vector_configs"):
        op.drop_table("admin_vector_configs")
