"""drop old batch columns from practice_records

Revision ID: 7386c399b670
Revises: u9v8w7x6y5z4
Create Date: 2026-06-29 00:31:23.008506

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

revision: str = "7386c399b670"
down_revision: Union[str, Sequence[str], None] = "u9v8w7x6y5z4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = [c["name"] for c in inspector.get_columns(table)]
    return column in cols


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    if is_sqlite:
        with op.batch_alter_table("practice_records") as batch_op:
            for col in ("mode", "question_ids", "answers", "correct_count", "wrong_count", "duration_sec", "started_at", "finished_at"):
                if _has_column("practice_records", col):
                    batch_op.drop_column(col)
    else:
        for col in ("mode", "question_ids", "answers", "correct_count", "wrong_count", "duration_sec", "started_at", "finished_at"):
            if _has_column("practice_records", col):
                op.drop_column("practice_records", col)


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    # Re-add old columns in batch mode for SQLite, direct for others
    cols = [
        ("mode", sa.VARCHAR(length=16), False, None),
        ("question_ids", sqlite.JSON(), False, None),
        ("answers", sqlite.JSON(), False, None),
        ("correct_count", sa.SMALLINT(), False, None),
        ("wrong_count", sa.SMALLINT(), False, None),
        ("duration_sec", sa.INTEGER(), False, None),
        ("started_at", sa.DATETIME(), False, sa.text("(CURRENT_TIMESTAMP)")),
        ("finished_at", sa.DATETIME(), True, None),
    ]

    if is_sqlite:
        with op.batch_alter_table("practice_records") as batch_op:
            for name, typ, nullable, server_default in cols:
                if not _has_column("practice_records", name):
                    batch_op.add_column(sa.Column(name, typ, nullable=nullable, server_default=server_default))
    else:
        for name, typ, nullable, server_default in cols:
            if not _has_column("practice_records", name):
                op.add_column("practice_records", sa.Column(name, typ, nullable=nullable, server_default=server_default))
