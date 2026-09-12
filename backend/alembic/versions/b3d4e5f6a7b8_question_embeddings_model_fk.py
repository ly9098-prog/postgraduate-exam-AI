"""question_embeddings: string embedding_model -> model_id FK (stage 1).

The mini-program smart-recommendation vector table stored the embedding model
identity as a free string (``embedding_model varchar(128)``, e.g.
"qwen3.7-text-embedding").  Model identity now belongs to
``admin_ai_model_configs`` (the registry that also holds credentials), so this
migration introduces a real foreign key:

    question_embeddings.model_id -> admin_ai_model_configs.id

Stage 1 (this revision):
  1. add nullable model_id
  2. backfill model_id from the live model registry.  The historical string
     stored in question_embeddings.embedding_model is the *display_name* of
     the embedding-capable config (name is "qwen3.7-text-embedding-flash" —
     the API model id actually sent to the provider — while display_name is
     "qwen3.7-text-embedding").  Mapping precedence:
       a) admin_ai_model_configs.display_name = embedding_model
       b) admin_ai_model_configs.name = embedding_model
     An ambiguous match (more than one candidate) or an unmatched value
     aborts the migration before any destructive change; nothing is fuzzy
     matched and no config row is invented.
  3. validate: 0 NULL model_id, 0 orphan model_id, row count unchanged
  4. add fk_question_embeddings_model (NO ACTION — deleting a model config
     must not cascade-delete generated embeddings)
  5. replace UNIQUE(question_id, embedding_model) with
     UNIQUE(question_id, model_id) and add ix_question_embeddings_model_id
  6. SET NOT NULL

Stage 2 (drop the legacy embedding_model column) lives in
follow-up revision b3d4e5f6a7b8 so the code deploy can go first.

Production audit (2026-09-12): 2160 rows, single value
"qwen3.7-text-embedding" -> exact_unique match on admin_ai_model_configs.id=70
(display_name), embedding_dim 1024/1024.

PostgreSQL-only in practice: question_embeddings exists only where pgvector is
available (p5_3_vector_schema is a no-op elsewhere), so this migration is a
no-op on other dialects.

Downgrade reconstructs the string column via JOIN (display_name preferred,
name fallback) — no data loss.
"""

from __future__ import annotations

import logging

import sqlalchemy as sa

from alembic import op

revision = "b3d4e5f6a7b8"
down_revision = "r408kpunique20260912"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.migration")

_TABLE = "question_embeddings"
_FK = "fk_question_embeddings_model"
_UNIQUE_OLD = "question_embeddings_question_id_embedding_model_key"
_UNIQUE_NEW = "uq_question_embeddings_question_id_model_id"
_INDEX = "ix_question_embeddings_model_id"


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _table_exists(conn, name: str) -> bool:
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = :t"
        ),
        {"t": name},
    ).scalar()
    return row is not None


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


def upgrade() -> None:
    if not _is_postgresql():
        return

    conn = op.get_bind()
    if not _table_exists(conn, _TABLE):
        logger.info("%s does not exist; skip", _TABLE)
        return
    if not _table_exists(conn, "admin_ai_model_configs"):
        logger.info("admin_ai_model_configs does not exist; skip")
        return
    if _has_column(conn, _TABLE, "model_id"):
        logger.info("%s.model_id already present; skip", _TABLE)
        return

    before_count = conn.execute(
        sa.text(f"SELECT COUNT(*) FROM {_TABLE}")
    ).scalar()

    # 1. add nullable model_id
    op.execute(f"ALTER TABLE {_TABLE} ADD COLUMN model_id integer")

    # 2. audit + backfill (display_name first, then name; ambiguity aborts)
    audit = conn.execute(
        sa.text(
            f"""
            SELECT qe.embedding_model AS old_value,
                   COUNT(DISTINCT c.id) AS candidates
            FROM {_TABLE} qe
            LEFT JOIN admin_ai_model_configs c
              ON c.display_name = qe.embedding_model
             OR c.name = qe.embedding_model
            GROUP BY qe.embedding_model
            """
        )
    ).fetchall()
    bad = [(r[0], r[1]) for r in audit if r[1] != 1]
    if bad:
        for old_value, candidates in bad:
            logger.error(
                "embedding_model=%r matched %d model configs (expected 1)",
                old_value,
                candidates,
            )
        raise RuntimeError(
            "question_embeddings.embedding_model -> admin_ai_model_configs "
            "mapping is not exact_unique; aborting migration. "
            f"Unresolved values: {bad}. Resolve manually before retrying."
        )

    op.execute(
        f"""
        UPDATE {_TABLE} qe
        SET model_id = c.id
        FROM admin_ai_model_configs c
        WHERE c.display_name = qe.embedding_model
        """
    )
    op.execute(
        f"""
        UPDATE {_TABLE} qe
        SET model_id = c.id
        FROM admin_ai_model_configs c
        WHERE c.name = qe.embedding_model
          AND qe.model_id IS NULL
        """
    )

    # 3. validate
    null_count = conn.execute(
        sa.text(f"SELECT COUNT(*) FROM {_TABLE} WHERE model_id IS NULL")
    ).scalar()
    if null_count:
        raise RuntimeError(
            f"{null_count} question_embeddings rows have NULL model_id after "
            "backfill; aborting before NOT NULL / FK."
        )
    orphan_count = conn.execute(
        sa.text(
            f"SELECT COUNT(*) FROM {_TABLE} qe "
            "LEFT JOIN admin_ai_model_configs c ON c.id = qe.model_id "
            "WHERE c.id IS NULL"
        )
    ).scalar()
    if orphan_count:
        raise RuntimeError(
            f"{orphan_count} question_embeddings rows have orphan model_id; "
            "aborting before FK."
        )
    after_count = conn.execute(sa.text(f"SELECT COUNT(*) FROM {_TABLE}")).scalar()
    if after_count != before_count:
        raise RuntimeError(
            f"row count changed during migration: before={before_count} "
            f"after={after_count}; aborting."
        )

    # 4. FK (NO ACTION: model config deletion must not cascade-delete embeddings)
    op.execute(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT {_FK} "
        "FOREIGN KEY (model_id) REFERENCES admin_ai_model_configs(id)"
    )

    # 5. swap uniqueness from (question_id, embedding_model) to
    #    (question_id, model_id) + lookup index
    unique_old_exists = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE table_name = :t AND constraint_name = :c"
        ),
        {"t": _TABLE, "c": _UNIQUE_OLD},
    ).scalar()
    if unique_old_exists:
        op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT {_UNIQUE_OLD}")
    op.execute(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT {_UNIQUE_NEW} "
        f"UNIQUE (question_id, model_id)"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {_INDEX} ON {_TABLE}(model_id)"
    )

    # 6. NOT NULL last
    op.execute(f"ALTER TABLE {_TABLE} ALTER COLUMN model_id SET NOT NULL")


def downgrade() -> None:
    if not _is_postgresql():
        return

    conn = op.get_bind()
    if not _table_exists(conn, _TABLE):
        return
    if not _has_column(conn, _TABLE, "model_id"):
        return

    # Rebuild the string column from the registry, then drop the FK identity.
    op.execute(
        f"ALTER TABLE {_TABLE} ADD COLUMN embedding_model varchar(128)"
    )
    op.execute(
        f"""
        UPDATE {_TABLE} qe
        SET embedding_model = COALESCE(c.display_name, c.name)
        FROM admin_ai_model_configs c
        WHERE c.id = qe.model_id
          AND qe.embedding_model IS NULL
        """
    )
    orphans = conn.execute(
        sa.text(
            f"SELECT COUNT(*) FROM {_TABLE} WHERE embedding_model IS NULL"
        )
    ).scalar()
    if orphans:
        raise RuntimeError(
            f"downgrade aborted: {orphans} rows cannot reconstruct "
            "embedding_model (model_id missing from admin_ai_model_configs)"
        )
    op.execute(f"ALTER TABLE {_TABLE} ALTER COLUMN embedding_model SET NOT NULL")
    op.execute(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT {_UNIQUE_OLD} "
        f"UNIQUE (question_id, embedding_model)"
    )
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
    fk_exists = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE table_name = :t AND constraint_name = :c"
        ),
        {"t": _TABLE, "c": _FK},
    ).scalar()
    if fk_exists:
        op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT {_FK}")
    unique_new_exists = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE table_name = :t AND constraint_name = :c"
        ),
        {"t": _TABLE, "c": _UNIQUE_NEW},
    ).scalar()
    if unique_new_exists:
        op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT {_UNIQUE_NEW}")
    op.execute(f"ALTER TABLE {_TABLE} DROP COLUMN model_id")
