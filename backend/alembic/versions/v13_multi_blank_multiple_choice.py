"""v13: Add multi_blank_multiple_choice question type

Splits 多空选择题 into two canonical types:
- multi_blank_choice → 多空（单选）选择题 (one letter per blank)
- multi_blank_multiple_choice → 多空（多选）选择题 (one or more letters per blank)

Steps:
1. Reclassify existing rows whose canonical answer has at least one blank
   slot with more than one letter — those can only be 多空（多选）选择题.
   (multi_blank_multiple_choice data could not exist before this migration,
   so no rows need reclassifying the other way.)
2. Refresh the CHECK constraints on questions / question_imports /
   practice_records to accept the new canonical code.

The migration is idempotent-friendly: constraint recreation drops any
existing constraint of the same name first.
"""

from __future__ import annotations

import re

from sqlalchemy import inspect, text

from alembic import op

revision = "v13_multi_blank_multiple_choice"
down_revision = "e408examdelete20260915"
branch_labels = None
depends_on = None

# 与 app.features.question_type.QuestionType 保持一致。
# tests/ocr_pipeline/test_migration_question_types.py 仅校验 v10 文件；
# 新增枚举值的历史约束更新通过本迁移完成。
CANONICAL_TYPES = [
    "single_choice",
    "multiple_choice",
    "true_false",
    "fill_blank",
    "multi_blank_choice",
    "multi_blank_multiple_choice",
    "subjective",
]

_CANONICAL_SQL = ", ".join(f"'{c}'" for c in CANONICAL_TYPES)

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

# One canonical slot value is "A" or "A,C" (≥2 letters ⇒ multi-select blank).
_SLOT_PAIR_RE = re.compile(r"[^:：;；]+?\s*[:：]\s*([A-Ha-h](?:\s*[，,、][A-Ha-h])+)")
_SLOT_RUN_RE = re.compile(r"[^:：;；]+?\s*[:：]\s*([A-Ha-h]{2,})")
_CIRCLED_MULTI_RE = re.compile(r"[①-⑳]\s*[A-Ha-h]{2,}(?![A-Za-z]*(?:[①-⑳]|$))")


def _answer_has_multi_letter_slot(answer: str | None) -> bool:
    """True when a canonical multi-blank answer has a slot with ≥2 letters."""
    if not answer:
        return False
    value = str(answer).strip()
    if not value:
        return False
    # Canonical "①:A,C;②:B" / "1:AC;2:B" forms
    for pattern in (_SLOT_PAIR_RE, _SLOT_RUN_RE):
        if pattern.search(value):
            return True
    # Compact "①AC、②D" forms (no colon)
    if ":" not in value and "：" not in value and _CIRCLED_MULTI_RE.search(value):
        return True
    return False


def _table_column_exists(inspector, table: str, column: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    cols = [c["name"] for c in inspector.get_columns(table)]
    return column in cols


def _reclassify_multi_letter_rows(inspector) -> int:
    """Upgrade multi_blank_choice rows with multi-letter slots to the new type."""
    bind = op.get_bind()
    upgraded = 0

    if _table_column_exists(inspector, "questions", "question_type"):
        rows = bind.execute(
            text(
                "SELECT id, answer FROM questions "
                "WHERE question_type = 'multi_blank_choice'"
            )
        ).fetchall()
        for row in rows:
            if _answer_has_multi_letter_slot(row[1]):
                bind.execute(
                    text(
                        "UPDATE questions SET question_type = "
                        "'multi_blank_multiple_choice' WHERE id = :rid"
                    ),
                    {"rid": row[0]},
                )
                upgraded += 1

    for table, id_col in (
        ("question_imports", "id"),
        ("question_revisions", "id"),
    ):
        if not _table_column_exists(inspector, table, "question_type"):
            continue
        answer_col = "parsed_answer" if table == "question_imports" else "answer"
        if answer_col not in [c["name"] for c in inspector.get_columns(table)]:
            continue
        rows = bind.execute(
            text(
                f"SELECT {id_col}, {answer_col} FROM {table} "
                f"WHERE question_type = 'multi_blank_choice'"
            )
        ).fetchall()
        for row in rows:
            if _answer_has_multi_letter_slot(row[1]):
                bind.execute(
                    text(
                        f"UPDATE {table} SET question_type = "
                        f"'multi_blank_multiple_choice' WHERE {id_col} = :rid"
                    ),
                    {"rid": row[0]},
                )
                upgraded += 1

    return upgraded


def _drop_constraint(bind, dialect: str, table: str, name: str) -> None:
    if dialect == "sqlite":
        return  # SQLite constraints are table-level; batch recreate handles it
    bind.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}"))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    dialect = bind.dialect.name

    # 第 1 步：存量多空选择题中每空多字母的记录重分类为多空（多选）选择题
    _reclassify_multi_letter_rows(inspector)

    # 第 2 步：刷新 CHECK 约束以纳入新题型
    for table, config in _CONSTRAINTS.items():
        if not _table_column_exists(inspector, table, config["column"]):
            continue

        if dialect == "sqlite":
            with op.batch_alter_table(table) as batch_op:
                batch_op.drop_constraint(config["name"], type_="check")
                batch_op.create_check_constraint(config["name"], config["sql"])
        else:
            _drop_constraint(bind, dialect, table, config["name"])
            op.execute(
                f"ALTER TABLE {table} "
                f"ADD CONSTRAINT {config['name']} "
                f"CHECK ({config['sql']})"
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    dialect = bind.dialect.name

    _OLD_CANONICAL_SQL = ", ".join(
        f"'{c}'"
        for c in (
            "single_choice",
            "multiple_choice",
            "true_false",
            "fill_blank",
            "multi_blank_choice",
            "subjective",
        )
    )
    _OLD_CONSTRAINTS = {
        "questions": {
            "column": "question_type",
            "name": "ck_questions_question_type",
            "sql": f"question_type IN ({_OLD_CANONICAL_SQL})",
        },
        "question_imports": {
            "column": "question_type",
            "name": "ck_question_imports_question_type",
            "sql": (
                f"question_type IS NULL OR question_type IN ({_OLD_CANONICAL_SQL})"
            ),
        },
        "practice_records": {
            "column": "question_type",
            "name": "ck_practice_records_question_type",
            "sql": f"question_type IN ({_OLD_CANONICAL_SQL})",
        },
    }

    # 第 1 步：新题型记录回退为 multi_blank_choice（答案结构本身兼容逐空单值/多值存储）
    for table in ("questions", "question_imports", "question_revisions"):
        if _table_column_exists(inspector, table, "question_type"):
            bind.execute(
                text(
                    f"UPDATE {table} SET question_type = 'multi_blank_choice' "
                    f"WHERE question_type = 'multi_blank_multiple_choice'"
                )
            )

    # 第 2 步：恢复旧 CHECK 约束
    for table, config in _OLD_CONSTRAINTS.items():
        if not _table_column_exists(inspector, table, config["column"]):
            continue

        if dialect == "sqlite":
            with op.batch_alter_table(table) as batch_op:
                batch_op.drop_constraint(config["name"], type_="check")
                batch_op.create_check_constraint(config["name"], config["sql"])
        else:
            _drop_constraint(bind, dialect, table, config["name"])
            op.execute(
                f"ALTER TABLE {table} "
                f"ADD CONSTRAINT {config['name']} "
                f"CHECK ({config['sql']})"
            )
