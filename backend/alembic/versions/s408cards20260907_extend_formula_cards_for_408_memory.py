"""extend formula cards into 408 memory/confusable cards

Revision ID: s408cards20260907
Revises: s408plan20260907
Create Date: 2026-09-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "s408cards20260907"
down_revision: Union[str, Sequence[str], None] = "s408plan20260907"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "formula_cards",
        sa.Column("study_card_type", sa.String(length=32), nullable=False, server_default="formula"),
    )
    op.add_column(
        "formula_cards",
        sa.Column("template_type", sa.String(length=24), nullable=False, server_default="standard"),
    )
    op.create_index(
        "ix_formula_cards_exam_study_type_status",
        "formula_cards",
        ["exam_scope", "study_card_type", "status"],
        unique=False,
    )
    op.create_index(
        "ix_formula_cards_template_type",
        "formula_cards",
        ["template_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_formula_cards_template_type", table_name="formula_cards")
    op.drop_index("ix_formula_cards_exam_study_type_status", table_name="formula_cards")
    op.drop_column("formula_cards", "template_type")
    op.drop_column("formula_cards", "study_card_type")
