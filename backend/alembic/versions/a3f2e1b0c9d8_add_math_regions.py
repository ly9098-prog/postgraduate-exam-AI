"""add math_regions column to question_imports"""
import sqlalchemy as sa

from alembic import op

revision = "a3f2e1b0c9d8"
down_revision = "e4a51b2293da"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("question_imports") as batch:
        batch.add_column(sa.Column("math_regions", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("question_imports") as batch:
        batch.drop_column("math_regions")
