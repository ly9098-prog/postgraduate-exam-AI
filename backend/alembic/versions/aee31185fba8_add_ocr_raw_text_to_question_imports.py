"""Add ocr_raw_text to question imports (stub — already applied to DB)

Revision ID: aee31185fba8
Revises: q2g3h4i5j6k7
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "aee31185fba8"
down_revision: Union[str, Sequence[str], None] = "q2g3h4i5j6k7"


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
