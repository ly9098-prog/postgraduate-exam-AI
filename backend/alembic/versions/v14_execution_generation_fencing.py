"""v14: add execution_generation fencing fields

Adds execution_generation, current_task_id, current_owner_token, and
execution_status columns to import_pipelines, import_batch_jobs, and
formula_import_jobs tables.

These fields support P0-1 fencing: execution generation + owner token guard
against stale workers writing business state after lease loss.

Revision ID: v14_execution_generation_fencing
Revises: v13_review_wq_indexes
Create Date: 2026-07-25
"""
from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "v14_execution_generation_fencing"
down_revision: str | Sequence[str] | None = "v10_performance_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── import_pipelines ──────────────────────────────────────────
    op.add_column("import_pipelines", sa.Column("execution_generation", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("import_pipelines", sa.Column("current_task_id", sa.String(64), nullable=True))
    op.add_column("import_pipelines", sa.Column("current_owner_token", sa.String(64), nullable=True))
    op.add_column("import_pipelines", sa.Column("execution_status", sa.String(16), nullable=True))
    op.create_index("ix_import_pipelines_execution_status", "import_pipelines", ["execution_status"])

    # ── import_batch_jobs ─────────────────────────────────────────
    op.add_column("import_batch_jobs", sa.Column("execution_generation", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("import_batch_jobs", sa.Column("current_task_id", sa.String(64), nullable=True))
    op.add_column("import_batch_jobs", sa.Column("current_owner_token", sa.String(64), nullable=True))
    op.add_column("import_batch_jobs", sa.Column("execution_status", sa.String(16), nullable=True))
    op.create_index("ix_import_batch_jobs_execution_status", "import_batch_jobs", ["execution_status"])

    # ── formula_import_jobs ───────────────────────────────────────
    op.add_column("formula_import_jobs", sa.Column("execution_generation", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("formula_import_jobs", sa.Column("current_task_id", sa.String(64), nullable=True))
    op.add_column("formula_import_jobs", sa.Column("current_owner_token", sa.String(64), nullable=True))
    op.add_column("formula_import_jobs", sa.Column("execution_status", sa.String(16), nullable=True))


def downgrade() -> None:
    # ── formula_import_jobs ───────────────────────────────────────
    op.drop_column("formula_import_jobs", "execution_status")
    op.drop_column("formula_import_jobs", "current_owner_token")
    op.drop_column("formula_import_jobs", "current_task_id")
    op.drop_column("formula_import_jobs", "execution_generation")

    # ── import_batch_jobs ─────────────────────────────────────────
    op.drop_index("ix_import_batch_jobs_execution_status")
    op.drop_column("import_batch_jobs", "execution_status")
    op.drop_column("import_batch_jobs", "current_owner_token")
    op.drop_column("import_batch_jobs", "current_task_id")
    op.drop_column("import_batch_jobs", "execution_generation")

    # ── import_pipelines ──────────────────────────────────────────
    op.drop_index("ix_import_pipelines_execution_status")
    op.drop_column("import_pipelines", "execution_status")
    op.drop_column("import_pipelines", "current_owner_token")
    op.drop_column("import_pipelines", "current_task_id")
    op.drop_column("import_pipelines", "execution_generation")
