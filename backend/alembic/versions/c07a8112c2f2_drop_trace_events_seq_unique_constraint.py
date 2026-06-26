"""drop trace events seq unique constraint

SQLite does not support ALTER TABLE DROP CONSTRAINT, so we use
batch_alter_table which recreates the table internally.

Revision ID: c07a8112c2f2
Revises: b1b2c3d4e5f6
Create Date: 2026-06-26 14:11:43.839861

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c07a8112c2f2'
down_revision: Union[str, Sequence[str], None] = 'b1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("batch_job_trace_events") as batch_op:
        batch_op.drop_constraint("uq_trace_events_job_seq", type_="unique")


def downgrade() -> None:
    with op.batch_alter_table("batch_job_trace_events") as batch_op:
        batch_op.create_unique_constraint("uq_trace_events_job_seq", ["job_id", "seq"])
