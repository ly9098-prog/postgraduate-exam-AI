"""p5_2_1_practice_records_fk — 补齐 practice_records.question_id 外键

Revision ID: p5_2_1_practice_records_fk
Revises: p5_0_schema_baseline
Create Date: 2026-06-29

Phase 5.2.1: 补齐 ORM 已声明但数据库缺失的外键约束。

安全规则：
- 先检查孤儿数据，有孤儿则跳过（不自动删除历史记录）
- upgrade 先检查 FK 是否已存在（幂等）
- downgrade 安全移除
- PostgreSQL / SQLite 均兼容（SQLite 不支持 ADD CONSTRAINT FK，需跳过）
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "p5_2_1_practice_records_fk"
down_revision: Union[str, Sequence[str], None] = "p5_0_schema_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return op.get_bind().dialect.has_table(op.get_bind(), name)


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    if not bind.dialect.has_table(bind, table):
        return False
    cols = [c["name"] for c in bind.dialect.get_columns(bind, table)]
    return column in cols


def _count_orphans() -> int:
    """检查 practice_records 中指向不存在 question 的孤儿数据。"""
    bind = op.get_bind()
    if not bind.dialect.has_table(bind, "practice_records"):
        return 0
    if not bind.dialect.has_table(bind, "questions"):
        return 0
    if not _has_column("practice_records", "question_id"):
        return 0

    result = bind.execute(sa.text(
        "SELECT COUNT(*) AS orphan_count "
        "FROM practice_records pr "
        "LEFT JOIN questions q ON q.id = pr.question_id "
        "WHERE pr.question_id IS NOT NULL "
        "AND q.id IS NULL"
    ))
    return result.scalar() or 0


def _fk_exists() -> bool:
    """检查 practice_records.question_id 的 FK 约束是否已存在。"""
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # SQLite 不支持动态添加 FK，跳过
        return True
    if not _has_table("practice_records"):
        return True

    fks = bind.dialect.get_foreign_keys(bind, "practice_records")
    for fk in fks:
        if "question_id" in fk.get("constrained_columns", []):
            referred = fk.get("referred_table", "")
            if referred == "questions":
                return True
    return False


def upgrade() -> None:
    bind = op.get_bind()

    # SQLite 不支持 ADD CONSTRAINT FOREIGN KEY，跳过
    if bind.dialect.name == "sqlite":
        return

    if not _has_table("practice_records"):
        return

    if not _has_column("practice_records", "question_id"):
        return

    if _fk_exists():
        return

    # 检查孤儿数据
    orphan_count = _count_orphans()
    if orphan_count > 0:
        # 有孤儿数据，不自动添加 FK，也不自动删除数据
        # 记录到日志但不阻塞迁移
        import logging
        logger = logging.getLogger("alembic")
        logger.warning(
            "practice_records 中存在 %d 条孤儿数据（question_id 指向不存在的 question），"
            "跳过外键添加。请手动处理孤儿数据后重新运行迁移。",
            orphan_count,
        )
        return

    # 安全添加 FK
    op.create_foreign_key(
        "fk_practice_records_question_id",
        "practice_records",
        "questions",
        ["question_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name == "sqlite":
        return

    if not _has_table("practice_records"):
        return

    if not _fk_exists():
        return

    op.drop_constraint(
        "fk_practice_records_question_id",
        "practice_records",
        type_="foreignkey",
    )
