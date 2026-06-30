"""drop subject column from import_batch_jobs

Revision ID: p5_7_drop_batch_job_subject
Revises: merge_p5_6_s7a8
Create Date: 2026-06-30

The subject string column on import_batch_jobs is redundant now that
subject_id (FK -> subjects.id) exists.  Subject display code is
resolved via the ORM relationship (ImportBatchJob.subject_ref.code).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p5_7_drop_batch_job_subject"
down_revision: Union[str, Sequence[str], None] = "merge_p5_6_s7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotency guard: only drop if column exists
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    col_names = [c["name"] for c in inspector.get_columns("import_batch_jobs")]
    if "subject" in col_names:
        with op.batch_alter_table("import_batch_jobs") as batch_op:
            batch_op.drop_column("subject")


def downgrade() -> None:
    # Restore the column so older code can still read it.
    with op.batch_alter_table("import_batch_jobs") as batch_op:
        batch_op.add_column(sa.Column("subject", sa.String(32), nullable=True))
