"""add pipeline watermark snapshot

Revision ID: 8779bfb39e9d
Revises: db7b046d9c2c
Create Date: 2026-06-06 00:00:00.000000

P0-3: import_pipelines 增加 watermark_snapshot JSON 列，记录首次导入时
实际生效的水印规则。resume 时直接复用快照，避免管理员在 paused 与
resume 之间调整规则导致新旧 chunk 文本归一化结果不一致 / GlobalHashIndex
去重契约失效。NULL 兼容历史 paused pipeline，回退到旧的"重新加载规则"
路径并打 warning。
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "8779bfb39e9d"
down_revision: Union[str, Sequence[str], None] = "db7b046d9c2c"
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


def upgrade() -> None:
    if _has_table("import_pipelines"):
        if not _has_column("import_pipelines", "watermark_snapshot"):
            op.add_column(
                "import_pipelines",
                sa.Column("watermark_snapshot", sa.JSON(), nullable=True),
            )


def downgrade() -> None:
    if _has_column("import_pipelines", "watermark_snapshot"):
        op.drop_column("import_pipelines", "watermark_snapshot")
