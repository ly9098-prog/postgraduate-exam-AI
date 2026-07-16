"""v10: Add CHECK constraints for question_type

Adds database-level CHECK constraints to ensure question_type columns
only contain canonical QuestionType codes.

Also updates the server_default on practice_records.question_type from
'choice' to 'single_choice' to match the new ORM default.

Pre-check: if any records contain non-canonical question_type values,
the migration will FAIL with a clear error message.
Run scripts/audit_question_types.py first to check data quality,
then use --apply to migrate known aliases before running this migration.

Constraints applied:
- questions.question_type: NOT NULL, IN (6 canonical codes)
- question_imports.question_type: NULL allowed, non-NULL must be canonical
- practice_records.question_type: NOT NULL, IN (6 canonical codes)

Revision ID: v10_question_type_check_constraints
Revises: v11_merge_heads
Create Date: 2026-07-16
"""

from alembic import op
from sqlalchemy import inspect, String, text

revision = "v10_question_type_check_constraints"
down_revision = "v11_merge_heads"
branch_labels = None
depends_on = None

# 6 个标准 QuestionType code
# WARNING: 若修改 QuestionType 枚举，必须同步更新此列表。
# tests/test_migration_question_types.py 会验证此列表与枚举一致。
CANONICAL_TYPES = [
    "single_choice",
    "multiple_choice",
    "true_false",
    "fill_blank",
    "multi_blank_choice",
    "subjective",
]

# 代码字面常量（用于 SQL）
_CANONICAL_SQL = ", ".join(f"'{c}'" for c in CANONICAL_TYPES)

# 涉及的约束
_CONSTRAINTS = {
    "questions": {
        "column": "question_type",
        "name": "ck_questions_question_type",
        "sql": f"question_type IN ({_CANONICAL_SQL})",
    },
    "question_imports": {
        "column": "question_type",
        "name": "ck_question_imports_question_type",
        "sql": f"question_type IS NULL OR question_type IN ({_CANONICAL_SQL})",
    },
    "practice_records": {
        "column": "question_type",
        "name": "ck_practice_records_question_type",
        "sql": f"question_type IN ({_CANONICAL_SQL})",
    },
}


def _pre_check(table: str, column: str) -> None:
    """运行预检查：扫描非标准值，有则中止迁移。"""
    bind = op.get_bind()
    inspector = inspect(bind)
    if table not in inspector.get_table_names():
        return
    cols = [c["name"] for c in inspector.get_columns(table)]
    if column not in cols:
        return

    result = bind.execute(
        text(
            f"SELECT {column}, COUNT(*) FROM {table} "
            f"WHERE {column} IS NOT NULL AND {column} NOT IN ({_CANONICAL_SQL}) "
            f"GROUP BY {column} ORDER BY COUNT(*) DESC"
        )
    )
    bad_rows = result.fetchall()
    if bad_rows:
        detail = "\n".join(f"  '{row[0]}': {row[1]} 条" for row in bad_rows)
        raise ValueError(
            f"表 {table}.{column} 包含 {len(bad_rows)} 个非标准值，无法添加 CHECK 约束。\n"
            f"请先运行: python scripts/audit_question_types.py --apply\n"
            f"非标准值:\n{detail}"
        )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    dialect = bind.dialect.name

    # 第 1 步：更新 practice_records server_default
    if "practice_records" in inspector.get_table_names():
        cols = [c["name"] for c in inspector.get_columns("practice_records")]
        if "question_type" in cols:
            if dialect == "sqlite":
                with op.batch_alter_table("practice_records") as batch_op:
                    batch_op.alter_column(
                        "question_type",
                        server_default="single_choice",
                        existing_type=String(32),
                        existing_nullable=False,
                    )
            else:
                op.execute(
                    "ALTER TABLE practice_records ALTER COLUMN question_type "
                    "SET DEFAULT 'single_choice'"
                )

    # 第 2 步：为每张表添加 CHECK 约束
    for table, config in _CONSTRAINTS.items():
        if table not in inspector.get_table_names():
            continue
        cols = [c["name"] for c in inspector.get_columns(table)]
        if config["column"] not in cols:
            continue

        # 预检查
        _pre_check(table, config["column"])

        # 添加约束
        if dialect == "sqlite":
            with op.batch_alter_table(table) as batch_op:
                batch_op.create_check_constraint(
                    config["name"],
                    config["sql"],
                )
        else:
            op.execute(
                f"ALTER TABLE {table} "
                f"ADD CONSTRAINT {config['name']} "
                f"CHECK ({config['sql']})"
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    dialect = bind.dialect.name

    # 第 1 步：恢复 practice_records server_default
    if "practice_records" in inspector.get_table_names():
        cols = [c["name"] for c in inspector.get_columns("practice_records")]
        if "question_type" in cols:
            if dialect == "sqlite":
                with op.batch_alter_table("practice_records") as batch_op:
                    batch_op.alter_column(
                        "question_type",
                        server_default="choice",
                        existing_type=String(32),
                        existing_nullable=False,
                    )
            else:
                op.execute(
                    "ALTER TABLE practice_records ALTER COLUMN question_type "
                    "SET DEFAULT 'choice'"
                )

    # 第 2 步：删除 CHECK 约束
    for table, config in _CONSTRAINTS.items():
        if table not in inspector.get_table_names():
            continue
        cols = [c["name"] for c in inspector.get_columns(table)]
        if config["column"] not in cols:
            continue

        if dialect == "sqlite":
            with op.batch_alter_table(table) as batch_op:
                batch_op.drop_constraint(config["name"])
        else:
            op.execute(
                f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {config['name']}"
            )
