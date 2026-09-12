"""add pipeline owner and source hash

Revision ID: db7b046d9c2c
Revises: n5d6e7f8a9b0
Create Date: 2026-06-06 00:00:00.000000

P0-1 / P0-2: import_pipelines 增加 created_by + source_sha256，让 resume
endpoint 能校验"是否同一用户"以及"是否同一份 PDF"。两列都允许 NULL，
保持向后兼容（历史 paused pipeline 仍可被原 import:write 持有人 resume）。
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "db7b046d9c2c"
down_revision: Union[str, Sequence[str], None] = "n5d6e7f8a9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return name in inspector.get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(table_name):
        return False
    return column_name in {col["name"] for col in inspector.get_columns(table_name)}


def _has_index(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(table_name):
        return False
    return index_name in {item["name"] for item in inspector.get_indexes(table_name)}


def upgrade() -> None:
    if _has_table("import_pipelines"):
        if not _has_column("import_pipelines", "created_by"):
            op.add_column(
                "import_pipelines",
                sa.Column("created_by", sa.String(64), nullable=True),
            )
        if not _has_column("import_pipelines", "source_sha256"):
            op.add_column(
                "import_pipelines",
                sa.Column("source_sha256", sa.String(64), nullable=True),
            )
        if not _has_index("import_pipelines", "ix_import_pipelines_created_by"):
            op.create_index(
                "ix_import_pipelines_created_by",
                "import_pipelines",
                ["created_by"],
            )


def downgrade() -> None:
    if _has_index("import_pipelines", "ix_import_pipelines_created_by"):
        op.drop_index(
            "ix_import_pipelines_created_by", table_name="import_pipelines"
        )
    if _has_column("import_pipelines", "source_sha256"):
        op.drop_column("import_pipelines", "source_sha256")
    if _has_column("import_pipelines", "created_by"):
        op.drop_column("import_pipelines", "created_by")
