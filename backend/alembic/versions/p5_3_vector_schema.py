"""Add question_embeddings table with pgvector support.

Revision ID: p5_3_vector_schema
Revises: 25b0a2fea77a
Create Date: 2026-06-29

Creates the pgvector extension and question_embeddings table for vector similarity search.
This migration replaces the runtime _ensure_vector_schema() DDL for production environments.

NOTE: This migration is PostgreSQL-only. On SQLite (used for testing), it is a no-op.
"""
from sqlalchemy import text

from alembic import op

revision = "p5_3_vector_schema"
down_revision = "25b0a2fea77a"
branch_labels = None
depends_on = None


def _is_postgresql() -> bool:
    """Check if the current database is PostgreSQL."""
    conn = op.get_bind()
    return conn.dialect.name == "postgresql"


def upgrade() -> None:
    # pgvector is PostgreSQL-only; skip on SQLite (test environments)
    if not _is_postgresql():
        return

    # 1. Check if pgvector extension is available before attempting to create it.
    #    CREATE EXTENSION IF NOT EXISTS throws an aborted-transaction error when
    #    the extension files are missing. Pre-check avoids this.
    conn = op.get_bind()
    available = conn.execute(
        text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
    ).scalar()
    if not available:
        return

    # pgvector available — create extension and vector tables
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 2. Create question_embeddings table
    # Dimension is set to 1536 (common for OpenAI text-embedding-3-small)
    # but should match EMBEDDING_DIM setting. Using 1536 as default.
    # Users with different dimensions should adjust before running.
    op.execute("""
        CREATE TABLE IF NOT EXISTS question_embeddings (
            id BIGSERIAL PRIMARY KEY,
            question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
            subject VARCHAR(32) NOT NULL,
            question_type VARCHAR(32) NOT NULL,
            embedding_model VARCHAR(128) NOT NULL,
            embedding_dim INTEGER NOT NULL,
            content_hash VARCHAR(64) NOT NULL,
            content_text TEXT NOT NULL,
            embedding vector(1536) NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
            embedded_at TIMESTAMP NOT NULL DEFAULT NOW(),
            UNIQUE(question_id, embedding_model)
        )
    """)

    # 3. B-tree indexes for common queries
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_question_embeddings_question_id "
        "ON question_embeddings(question_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_question_embeddings_subject "
        "ON question_embeddings(subject)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_question_embeddings_content_hash "
        "ON question_embeddings(content_hash)"
    )

    # 4. HNSW index for cosine similarity search
    try:
        op.execute("""
            CREATE INDEX IF NOT EXISTS ix_question_embeddings_embedding_hnsw
            ON question_embeddings
            USING hnsw (embedding vector_cosine_ops)
        """)
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
            "HNSW index creation failed; vector search will still work but may be slower"
        )


def downgrade() -> None:
    # pgvector is PostgreSQL-only; skip on SQLite
    if not _is_postgresql():
        return

    # Drop in reverse order

    # 1. Drop HNSW index
    op.execute("DROP INDEX IF EXISTS ix_question_embeddings_embedding_hnsw")

    # 2. Drop B-tree indexes
    op.execute("DROP INDEX IF EXISTS ix_question_embeddings_content_hash")
    op.execute("DROP INDEX IF EXISTS ix_question_embeddings_subject")
    op.execute("DROP INDEX IF EXISTS ix_question_embeddings_question_id")

    # 3. Drop table
    op.execute("DROP TABLE IF EXISTS question_embeddings")

    # NOTE: Do NOT drop the vector extension here.
    # Other tables or future use may depend on it.
    # If you need to remove the extension entirely, do it manually:
    #   DROP EXTENSION IF EXISTS vector;
