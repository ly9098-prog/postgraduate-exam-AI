"""v18: reconcile legacy production schema with the canonical contract.

Fresh databases already have these constraints and indexes from older revisions.
Some long-lived production databases predated those definitions, so this
forward-only reconciliation adds only missing objects and repairs one FK action.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "v18_production_schema_reconciliation"
down_revision = "v17_redundant_index_cleanup"
branch_labels = None
depends_on = None

_UNIQUES = (
    ("admin_users", "admin_users_username_key", ("username",)),
    ("permissions", "permissions_name_key", ("name",)),
    ("roles", "roles_name_key", ("name",)),
    ("subjects", "subjects_code_key", ("code",)),
)

_INDEXES = (
    ("answer_behaviors", "idx_answer_behavior_user_date", ("user_id", "created_at")),
    ("audit_logs", "idx_audit_logs_resource", ("resource_type", "resource_id")),
    ("practice_records", "idx_practice_records_user_date", ("user_id", "answered_at")),
    ("review_records", "ix_review_records_user_reviewed", ("user_id", "reviewed_at")),
)


def _assert_no_duplicates(table: str, columns: tuple[str, ...]) -> None:
    cols = ", ".join(columns)
    duplicate_groups = int(
        op.get_bind()
        .execute(
            sa.text(
                f"SELECT COUNT(*) FROM (SELECT {cols} FROM {table} "
                f"GROUP BY {cols} HAVING COUNT(*) > 1) AS duplicate_groups"
            )
        )
        .scalar_one()
    )
    if duplicate_groups:
        raise RuntimeError(
            f"cannot add unique constraint to {table}({cols}): "
            f"{duplicate_groups} duplicate group(s) exist"
        )


def _ensure_unique(table: str, name: str, columns: tuple[str, ...]) -> None:
    inspector = sa.inspect(op.get_bind())
    if any(item.get("name") == name for item in inspector.get_unique_constraints(table)):
        return
    _assert_no_duplicates(table, columns)
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(table, recreate="always") as batch_op:
            batch_op.create_unique_constraint(name, list(columns))
    else:
        op.create_unique_constraint(name, table, list(columns))


def _ensure_index(table: str, name: str, columns: tuple[str, ...]) -> None:
    if any(item.get("name") == name for item in sa.inspect(op.get_bind()).get_indexes(table)):
        return
    op.create_index(name, table, list(columns), unique=False)


def _repair_practice_question_fk() -> None:
    table = "practice_records"
    inspector = sa.inspect(op.get_bind())
    matching = [
        fk
        for fk in inspector.get_foreign_keys(table)
        if fk.get("constrained_columns") == ["question_id"]
    ]
    if matching and (matching[0].get("options") or {}).get("ondelete") == "CASCADE":
        return

    orphans = int(
        op.get_bind()
        .execute(
            sa.text(
                "SELECT COUNT(*) FROM practice_records AS p "
                "LEFT JOIN questions AS q ON q.id = p.question_id "
                "WHERE p.question_id IS NOT NULL AND q.id IS NULL"
            )
        )
        .scalar_one()
    )
    if orphans:
        raise RuntimeError(
            "cannot repair practice_records.question_id FK: "
            f"{orphans} orphan value(s) exist"
        )

    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(table, recreate="always") as batch_op:
            for fk in matching:
                if fk.get("name"):
                    batch_op.drop_constraint(fk["name"], type_="foreignkey")
            batch_op.create_foreign_key(
                "fk_practice_records_question_id",
                "questions",
                ["question_id"],
                ["id"],
                ondelete="CASCADE",
            )
    else:
        for fk in matching:
            if fk.get("name"):
                op.drop_constraint(fk["name"], table, type_="foreignkey")
        op.create_foreign_key(
            "fk_practice_records_question_id",
            table,
            "questions",
            ["question_id"],
            ["id"],
            ondelete="CASCADE",
        )


def upgrade() -> None:
    for table, name, columns in _UNIQUES:
        _ensure_unique(table, name, columns)
    for table, name, columns in _INDEXES:
        _ensure_index(table, name, columns)
    _repair_practice_question_fk()


def downgrade() -> None:
    # Forward-only compatibility repair. These objects may predate this revision
    # on fresh/local databases, so removing them would make downgrade destructive.
    pass
