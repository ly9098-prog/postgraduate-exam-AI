"""add soft-delete timestamp to admin_ai_model_configs

Revision ID: d5f6a7b8c9d0
Revises: c4e5f6a7b8c9
Create Date: 2026-09-12

``admin_ai_model_configs`` is referenced by historical rows such as
``question_embeddings.model_id``.  Model deletion must therefore preserve the
registry row (and its stable id) instead of physically deleting it.

The nullable ``deleted_at`` timestamp is the soft-delete marker.  Existing
rows remain active because the migration does not backfill the column.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "d5f6a7b8c9d0"
down_revision = "c4e5f6a7b8c9"
branch_labels = None
depends_on = None

_TABLE = "admin_ai_model_configs"
_COLUMN = "deleted_at"


def _table_exists(conn) -> bool:
    return sa.inspect(conn).has_table(_TABLE)


def _has_column(conn) -> bool:
    if not _table_exists(conn):
        return False
    return _COLUMN in {column["name"] for column in sa.inspect(conn).get_columns(_TABLE)}


def upgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn) or _has_column(conn):
        return
    op.add_column(_TABLE, sa.Column(_COLUMN, sa.DateTime(), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    if not _has_column(conn):
        return
    with op.batch_alter_table(_TABLE) as batch_op:
        batch_op.drop_column(_COLUMN)
