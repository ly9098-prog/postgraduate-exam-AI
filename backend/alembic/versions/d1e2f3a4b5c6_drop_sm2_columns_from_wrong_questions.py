"""drop sm2 columns from wrong_questions

SM-2 scheduling state is now exclusively managed by ReviewSchedule.
Remove redundant SM-2 fields from wrong_questions table.

Revision ID: d1e2f3a4b5c6
Revises: a5eac9aa37fa
Create Date: 2026-06-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, Sequence[str], None] = "a5eac9aa37fa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop index that references next_review_date before dropping the column.
    # SQLite batch_alter_table recreates the table and re-applies indexes,
    # so the old index must be removed first.
    conn = op.get_bind()
    dialect = conn.dialect.name
    if dialect == "postgresql":
        op.execute("DROP INDEX IF EXISTS idx_wrong_questions_user_mastered_date")
    else:
        op.drop_index("idx_wrong_questions_user_mastered_date", table_name="wrong_questions")

    # Use batch_alter_table for SQLite compatibility
    with op.batch_alter_table("wrong_questions") as batch_op:
        batch_op.drop_column("efactor")
        batch_op.drop_column("interval")
        batch_op.drop_column("repetitions")
        batch_op.drop_column("next_review_date")
        batch_op.drop_column("quality")


def downgrade() -> None:
    with op.batch_alter_table("wrong_questions") as batch_op:
        batch_op.add_column(
            sa.Column("quality", sa.SmallInteger(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("next_review_date", sa.Date(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("repetitions", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("interval", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("efactor", sa.Float(), nullable=False, server_default="2.5")
        )

    # Recreate the index after restoring the column
    op.create_index(
        "idx_wrong_questions_user_mastered_date",
        "wrong_questions",
        ["user_id", "mastered", "next_review_date"],
    )
