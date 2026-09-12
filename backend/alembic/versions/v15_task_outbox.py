"""v15: add transactional task_outbox table

Adds the ``task_outbox`` table for the transactional outbox pattern,
ensuring DB→Redis consistency for task enqueue operations.

Business operations write both the business record and a task_outbox row
in the same PostgreSQL transaction. A background dispatcher reads pending
outbox rows using FOR UPDATE SKIP LOCKED, enqueues them to Redis, and
marks them as published.

Revision ID: v15_task_outbox
Revises: v14_execution_generation_fencing
Create Date: 2026-07-27
"""
from __future__ import annotations

from typing import ClassVar

import sqlalchemy as sa

from alembic import op

revision: str = "v15_task_outbox"
down_revision: str | None = "v14_execution_generation_fencing"
branch_labels: ClassVar[tuple[str] | None] = None
depends_on: ClassVar[tuple[str] | None] = None


def upgrade() -> None:
    op.create_table(
        "task_outbox",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.String(64), nullable=False, comment="Idempotent task ID"),
        sa.Column("task_type", sa.String(32), nullable=False, comment="Queue task type"),
        sa.Column(
            "payload",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="{}",
            comment="Task payload",
        ),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="pending",
            comment="pending | leased | published | failed | cancelled",
        ),
        sa.Column("lease_token", sa.String(64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", name="uq_task_outbox_task_id"),
    )
    op.create_index(
        "ix_task_outbox_status", "task_outbox", ["status"],
        postgresql_using="btree",
    )
    op.create_index(
        "ix_task_outbox_type_status", "task_outbox", ["task_type", "status"],
        postgresql_using="btree",
    )


def downgrade() -> None:
    op.drop_index("ix_task_outbox_type_status", table_name="task_outbox")
    op.drop_index("ix_task_outbox_status", table_name="task_outbox")
    op.drop_table("task_outbox")
