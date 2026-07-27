"""merge: v11_export_version + v15_task_outbox

Revision ID: v11_v15_merge
Revises: v11_export_version, v15_task_outbox
Create Date: 2026-07-27 14:00:00.000000

"""
from __future__ import annotations

from typing import ClassVar, Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v11_v15_merge"
down_revision: Union[str, Sequence[str], None] = ("v11_export_version", "v15_task_outbox")
branch_labels: ClassVar[tuple[str] | None] = None
depends_on: ClassVar[tuple[str] | None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
