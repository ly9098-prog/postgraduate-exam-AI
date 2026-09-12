"""question_embeddings: drop legacy embedding_model string column (stage 2).

Follow-up to b3d4e5f6a7b8 which added model_id FK.  This revision drops the
legacy ``embedding_model varchar(128)`` string column once the backend has
been deployed against model_id.  The display string is reconstructable via
``model_id JOIN admin_ai_model_configs`` (see stage-1 downgrade), so no data
is lost.

PostgreSQL-only; no-op elsewhere (table may not exist without pgvector).
"""

from __future__ import annotations

import logging

import sqlalchemy as sa

from alembic import op

revision = "c4e5f6a7b8c9"
down_revision = "b3d4e5f6a7b8"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.migration")

_TABLE = "question_embeddings"
_LEGACY_COLUMN = "embedding_model"


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _has_column(conn, table: str, column: str) -> bool:
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = current_schema() "
            "AND table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).scalar()
    return row is not None


def _table_exists(conn, name: str) -> bool:
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = :t"
        ),
        {"t": name},
    ).scalar()
    return row is not None


def upgrade() -> None:
    if not _is_postgresql():
        return

    conn = op.get_bind()
    if not _table_exists(conn, _TABLE):
        return
    if not _has_column(conn, _TABLE, "model_id"):
        raise RuntimeError(
            f"({_TABLE}).model_id does not exist; stage 1 "
            f"(b3d4e5f6a7b8) must run before dropping {_LEGACY_COLUMN}"
        )
    if not _has_column(conn, _TABLE, _LEGACY_COLUMN):
        logger.info("%s.%s already dropped; skip", _TABLE, _LEGACY_COLUMN)
        return

    # Safety: refuse to drop while any row still lacks a model_id.
    null_count = conn.execute(
        sa.text(f"SELECT COUNT(*) FROM {_TABLE} WHERE model_id IS NULL")
    ).scalar()
    if null_count:
        raise RuntimeError(
            f"{null_count} rows have NULL model_id; refusing to drop "
            f"{_LEGACY_COLUMN}"
        )
    op.execute(f"ALTER TABLE {_TABLE} DROP COLUMN {_LEGACY_COLUMN}")


def downgrade() -> None:
    if not _is_postgresql():
        return

    conn = op.get_bind()
    if not _table_exists(conn, _TABLE):
        return
    if not _has_column(conn, _TABLE, _LEGACY_COLUMN):
        op.execute(
            f"ALTER TABLE {_TABLE} ADD COLUMN {_LEGACY_COLUMN} varchar(128)"
        )
        op.execute(
            f"""
            UPDATE {_TABLE} qe
            SET {_LEGACY_COLUMN} = COALESCE(c.display_name, c.name)
            FROM admin_ai_model_configs c
            WHERE c.id = qe.model_id
            """
        )
        op.execute(
            f"ALTER TABLE {_TABLE} ALTER COLUMN {_LEGACY_COLUMN} SET NOT NULL"
        )
        op.execute(
            f"ALTER TABLE {_TABLE} ADD CONSTRAINT "
            f"question_embeddings_question_id_embedding_model_key "
            f"UNIQUE (question_id, {_LEGACY_COLUMN})"
        )
