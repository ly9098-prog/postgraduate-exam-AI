"""add 408 coverage governance indexes

Revision ID: s408coverage20260907
Revises: s408syllabus20260907
Create Date: 2026-09-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "s408coverage20260907"
down_revision: Union[str, Sequence[str], None] = "s408syllabus20260907"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _indexes(inspector: sa.Inspector, table: str) -> set[str]:
    if not inspector.has_table(table):
        return set()
    return {str(item["name"]) for item in inspector.get_indexes(table) if item.get("name")}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "ix_questions_coverage_scope" not in _indexes(inspector, "questions"):
        op.create_index(
            "ix_questions_coverage_scope",
            "questions",
            ["subject_id", "review_status", "is_active"],
            unique=False,
        )

    if "ix_exam_papers_coverage_type_year_status" not in _indexes(inspector, "exam_papers"):
        op.create_index(
            "ix_exam_papers_coverage_type_year_status",
            "exam_papers",
            ["paper_type", "year", "status", "is_active"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "ix_exam_papers_coverage_type_year_status" in _indexes(inspector, "exam_papers"):
        op.drop_index("ix_exam_papers_coverage_type_year_status", table_name="exam_papers")
    if "ix_questions_coverage_scope" in _indexes(inspector, "questions"):
        op.drop_index("ix_questions_coverage_scope", table_name="questions")
