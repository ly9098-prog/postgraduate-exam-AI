"""add position column to question_knowledge_points

``position`` preserves the original JSON-array order of a question's
knowledge points (0-based). The old ``questions.knowledge_points`` JSON column
is replaced by the relation table as the single source of truth, so the display
order must be stored explicitly instead of relying on ``knowledge_points.id``.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "p0q1r2s3t4u5"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def _column_names(inspector, table: str) -> set[str]:
    return {c["name"] for c in inspector.get_columns(table)}


def _index_names(inspector, table: str) -> set[str]:
    return {i["name"] for i in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    cols = _column_names(inspector, "question_knowledge_points")
    if "position" not in cols:
        op.add_column(
            "question_knowledge_points",
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        )

    idx = _index_names(inspector, "question_knowledge_points")
    if "ix_qkp_question_position" not in idx:
        op.create_index(
            "ix_qkp_question_position",
            "question_knowledge_points",
            ["question_id", "position"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    idx = _index_names(inspector, "question_knowledge_points")
    if "ix_qkp_question_position" in idx:
        op.drop_index("ix_qkp_question_position", table_name="question_knowledge_points")

    cols = _column_names(inspector, "question_knowledge_points")
    if "position" in cols:
        op.drop_column("question_knowledge_points", "position")
