"""add request_id column and unique index to import_batch_jobs

Adds a nullable request_id column with a unique index on
import_batch_jobs for concurrent-duplicate request_id protection.

Revision ID: a5eac9aa37fa
Revises: c07a8112c2f2
Create Date: 2026-06-26 15:03:19.219552

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a5eac9aa37fa'
down_revision: Union[str, Sequence[str], None] = 'c07a8112c2f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add request_id column + unique index to import_batch_jobs."""
    op.add_column(
        "import_batch_jobs",
        sa.Column("request_id", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_import_batch_jobs_request_id",
        "import_batch_jobs",
        ["request_id"],
        unique=True,
    )


def downgrade() -> None:
    """Drop request_id column + unique index from import_batch_jobs."""
    op.drop_index("ix_import_batch_jobs_request_id", table_name="import_batch_jobs")
    op.drop_column("import_batch_jobs", "request_id")
