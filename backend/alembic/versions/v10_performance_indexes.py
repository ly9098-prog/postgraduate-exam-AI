"""v10: add composite indexes for common query patterns

Adds composite indexes on foreign key + frequently-filtered column pairs
that the query planner cannot fully leverage with single-column indexes alone.

Key query patterns targeted:
- user_question_state.user_id + next_review_at: "due questions today"
- import_pipelines.created_by + status: "my pipelines filter"
- practice_records.user_id + created_at: "recent practice history"

This migration revises v13 (not directly v9) so the chain stays linear:
v9 → ... → v13 → v10 (indexes) → v14 (fencing)

Revision ID: v10_performance_indexes
Revises: v13_review_wq_indexes
Create Date: 2026-07-25
"""

from alembic import op
import sqlalchemy as sa

revision = "v10_performance_indexes"
down_revision = "v13_review_wq_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_context().bind
    if bind and bind.dialect.name == "postgresql":
        # CREATE INDEX CONCURRENTLY must run outside a transaction block.
        with op.get_context().autocommit_block():
            op.execute(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "ix_user_question_state_user_next_review "
                "ON user_question_state USING btree (user_id, next_review_at)"
            )
            op.execute(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "ix_import_pipelines_created_by_status "
                "ON import_pipelines USING btree (created_by, status)"
            )
            op.execute(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "ix_practice_records_user_created "
                "ON practice_records USING btree (user_id, created_at)"
            )
    else:
        op.create_index(
            "ix_user_question_state_user_next_review",
            "user_question_state",
            ["user_id", "next_review_at"],
        )
        op.create_index(
            "ix_import_pipelines_created_by_status",
            "import_pipelines",
            ["created_by", "status"],
        )
        op.create_index(
            "ix_practice_records_user_created",
            "practice_records",
            ["user_id", "created_at"],
        )


def downgrade() -> None:
    op.drop_index("ix_user_question_state_user_next_review", if_exists=True)
    op.drop_index("ix_import_pipelines_created_by_status", if_exists=True)
    op.drop_index("ix_practice_records_user_created", if_exists=True)
