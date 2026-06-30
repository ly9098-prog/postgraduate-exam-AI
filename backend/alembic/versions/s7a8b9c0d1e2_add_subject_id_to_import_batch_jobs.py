"""add subject_id to import_batch_jobs

Revision ID: s7a8b9c0d1e2
Revises: p5_2_1_practice_records_fk
Create Date: 2026-06-30

Adds subject_id FK (-> subjects.id) to import_batch_jobs so that
batch image import jobs can store the integer subject_id alongside
the legacy string subject column.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "s7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "p5_2_1_practice_records_fk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = [c["name"] for c in inspector.get_columns("import_batch_jobs")]

    if "subject_id" not in columns:
        with op.batch_alter_table("import_batch_jobs") as batch_op:
            batch_op.add_column(
                sa.Column("subject_id", sa.Integer(), nullable=True),
            )
            batch_op.create_foreign_key(
                "fk_import_batch_jobs_subject_id",
                "subjects",
                ["subject_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch_op.create_index(
                "ix_import_batch_jobs_subject_id",
                ["subject_id"],
            )


def downgrade() -> None:
    with op.batch_alter_table("import_batch_jobs") as batch_op:
        batch_op.drop_index("ix_import_batch_jobs_subject_id")
        batch_op.drop_constraint("fk_import_batch_jobs_subject_id", type_="foreignkey")
        batch_op.drop_column("subject_id")
