"""p5_0_schema_baseline — practice_records 新列 + import_pipelines 质量列

Revision ID: p5_0_schema_baseline
Revises: p4_6_release_hardening
Create Date: 2026-06-29

Phase 5.0 Schema Baseline Repair:
1. practice_records: 添加 5 个 per-question 字段（ORM 已重设计但缺迁移）
2. import_pipelines: 添加 quality_report 和 alerts 2 个 JSON 列
3. practice_records: 添加 question_id 单列索引

安全规则：
- 禁止 DROP TABLE / DROP COLUMN
- 新列先 nullable 添加，不阻塞已有数据
- downgrade 可回滚（drop added columns/indexes）
- 使用 _has_table / _has_column / _has_index guard 保证幂等
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p5_0_schema_baseline"
down_revision: Union[str, Sequence[str], None] = "p4_6_release_hardening"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_table(name: str) -> bool:
    return op.get_bind().dialect.has_table(op.get_bind(), name)


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    if not bind.dialect.has_table(bind, table):
        return False
    cols = [c["name"] for c in bind.dialect.get_columns(bind, table)]
    return column in cols


def _has_index(table: str, index: str) -> bool:
    bind = op.get_bind()
    if not bind.dialect.has_table(bind, table):
        return False
    indexes = bind.dialect.get_indexes(bind, table)
    return any(idx["name"] == index for idx in indexes)


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    # === 1. practice_records: 5 new per-question columns ===
    if _has_table("practice_records"):
        if not _has_column("practice_records", "question_id"):
            op.add_column(
                "practice_records",
                sa.Column("question_id", sa.Integer(), nullable=True),
            )
        if not _has_column("practice_records", "question_type"):
            op.add_column(
                "practice_records",
                sa.Column("question_type", sa.String(32), nullable=True),
            )
        if not _has_column("practice_records", "user_answer"):
            op.add_column(
                "practice_records",
                sa.Column("user_answer", sa.Text(), nullable=True),
            )
        if not _has_column("practice_records", "is_correct"):
            op.add_column(
                "practice_records",
                sa.Column("is_correct", sa.Boolean(), nullable=True),
            )
        if not _has_column("practice_records", "used_time"):
            op.add_column(
                "practice_records",
                sa.Column("used_time", sa.Integer(), nullable=True),
            )

        # Index on question_id (new column)
        if not _has_index("practice_records", "ix_practice_records_question_id"):
            op.create_index(
                "ix_practice_records_question_id",
                "practice_records",
                ["question_id"],
                unique=False,
            )

    # === 2. import_pipelines: 2 new quality columns ===
    if _has_table("import_pipelines"):
        if not _has_column("import_pipelines", "quality_report"):
            op.add_column(
                "import_pipelines",
                sa.Column("quality_report", sa.JSON(), nullable=True),
            )
        if not _has_column("import_pipelines", "alerts"):
            op.add_column(
                "import_pipelines",
                sa.Column("alerts", sa.JSON(), nullable=True),
            )


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------

def downgrade() -> None:
    # import_pipelines: remove quality columns
    if _has_table("import_pipelines"):
        if _has_column("import_pipelines", "alerts"):
            op.drop_column("import_pipelines", "alerts")
        if _has_column("import_pipelines", "quality_report"):
            op.drop_column("import_pipelines", "quality_report")

    # practice_records: remove question_id index and new columns
    if _has_table("practice_records"):
        if _has_index("practice_records", "ix_practice_records_question_id"):
            op.drop_index(
                "ix_practice_records_question_id",
                table_name="practice_records",
            )
        for col in ("used_time", "is_correct", "user_answer",
                     "question_type", "question_id"):
            if _has_column("practice_records", col):
                op.drop_column("practice_records", col)
