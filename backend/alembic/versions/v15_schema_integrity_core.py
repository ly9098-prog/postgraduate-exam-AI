"""v15: restore core schema integrity.

Creates the two data-bearing tables that previously existed only through local
``create_all()``, and aligns critical PK/unique/FK constraints without deleting
or merging any rows.
"""

from __future__ import annotations

from collections.abc import Iterable

import sqlalchemy as sa

from alembic import op

revision = "v15_schema_integrity_core"
down_revision = "v14_add_review_sessions"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _constraint_names(table: str, kind: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    getter = {
        "pk": inspector.get_pk_constraint,
        "unique": inspector.get_unique_constraints,
        "foreign": inspector.get_foreign_keys,
    }[kind]
    value = getter(table)
    if isinstance(value, dict):
        return {value.get("name")} if value.get("name") else set()
    return {item.get("name") for item in value if item.get("name")}


def _require_columns(table: str, columns: Iterable[str]) -> None:
    actual = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}
    missing = set(columns) - actual
    if missing:
        raise RuntimeError(f"{table} exists but is missing columns: {sorted(missing)}")


def _scalar(sql: str) -> int:
    return int(op.get_bind().execute(sa.text(sql)).scalar_one())


def _assert_no_duplicates(table: str, columns: tuple[str, ...]) -> None:
    cols = ", ".join(columns)
    duplicates = _scalar(
        f"SELECT COUNT(*) FROM (SELECT {cols} FROM {table} "
        f"GROUP BY {cols} HAVING COUNT(*) > 1) AS duplicate_groups"
    )
    if duplicates:
        raise RuntimeError(
            f"cannot add unique constraint to {table}({cols}): "
            f"{duplicates} duplicate group(s) exist"
        )


def _create_unique(table: str, name: str, columns: list[str]) -> None:
    if name in _constraint_names(table, "unique"):
        return
    _assert_no_duplicates(table, tuple(columns))
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(table, recreate="always") as batch_op:
            batch_op.create_unique_constraint(name, columns)
    else:
        op.create_unique_constraint(name, table, columns)


def _drop_constraint(table: str, name: str, kind: str) -> None:
    if name not in _constraint_names(table, kind):
        return
    constraint_type = {"pk": "primary", "unique": "unique", "foreign": "foreignkey"}[kind]
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(table, recreate="always") as batch_op:
            batch_op.drop_constraint(name, type_=constraint_type)
    else:
        op.drop_constraint(name, table, type_=constraint_type)


def _ensure_feedback_table() -> None:
    table = "ai_feedback_logs"
    required = {
        "id",
        "user_id",
        "source",
        "feedback_type",
        "question_id",
        "detail",
        "created_at",
    }
    if table in _table_names():
        _require_columns(table, required)
        return
    op.create_table(
        table,
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("feedback_type", sa.String(32), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_feedback_logs")),
    )
    op.create_index(op.f("ix_ai_feedback_logs_user_id"), table, ["user_id"])


def _ensure_worker_credentials_table() -> None:
    table = "worker_credentials"
    required = {
        "id",
        "worker_id",
        "key_hash",
        "is_active",
        "created_at",
        "rotated_at",
        "expires_at",
    }
    if table in _table_names():
        _require_columns(table, required)
        return
    op.create_table(
        table,
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("worker_id", sa.String(64), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("rotated_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_worker_credentials")),
    )
    op.create_index(op.f("ix_worker_credentials_worker_id"), table, ["worker_id"])


def _ensure_formula_graph_specs_pk() -> None:
    table = "formula_graph_specs"
    pk = sa.inspect(op.get_bind()).get_pk_constraint(table)
    if pk.get("constrained_columns"):
        if pk["constrained_columns"] != ["id"]:
            raise RuntimeError(f"unexpected {table} primary key: {pk['constrained_columns']}")
        return
    if _scalar(f"SELECT COUNT(*) FROM {table} WHERE id IS NULL"):
        raise RuntimeError(f"cannot add primary key: {table}.id contains NULL")
    _assert_no_duplicates(table, ("id",))
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(table, recreate="always") as batch_op:
            batch_op.create_primary_key("pk_formula_graph_specs", ["id"])
    else:
        op.create_primary_key("pk_formula_graph_specs", table, ["id"])


def _ensure_formula_asset_reviewer_fk() -> None:
    table = "formula_graph_assets"
    inspector = sa.inspect(op.get_bind())
    for fk in inspector.get_foreign_keys(table):
        if fk.get("constrained_columns") == ["reviewed_by"]:
            return
    orphans = _scalar(
        "SELECT COUNT(*) FROM formula_graph_assets AS a "
        "LEFT JOIN admin_users AS u ON u.id = a.reviewed_by "
        "WHERE a.reviewed_by IS NOT NULL AND u.id IS NULL"
    )
    if orphans:
        raise RuntimeError(
            "cannot add formula graph reviewer FK: "
            f"{orphans} orphan reviewed_by value(s) exist"
        )
    name = "fk_formula_graph_assets_reviewed_by_admin_users"
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(table, recreate="always") as batch_op:
            batch_op.create_foreign_key(name, "admin_users", ["reviewed_by"], ["id"])
    else:
        op.create_foreign_key(name, table, "admin_users", ["reviewed_by"], ["id"])


def upgrade() -> None:
    _ensure_feedback_table()
    _ensure_worker_credentials_table()
    _ensure_formula_graph_specs_pk()
    _create_unique(
        "user_knowledge_adaptive_state",
        "uq_ukas_user_kp",
        ["user_id", "knowledge_point_id"],
    )
    _create_unique(
        "user_question_difficulty_state",
        "uq_uqds_user_question",
        ["user_id", "question_id"],
    )
    _ensure_formula_asset_reviewer_fk()


def downgrade() -> None:
    # Preserve ai_feedback_logs and worker_credentials: both may predate this
    # migration in local databases and may contain business data.
    _drop_constraint(
        "formula_graph_assets",
        "fk_formula_graph_assets_reviewed_by_admin_users",
        "foreign",
    )
    _drop_constraint(
        "user_question_difficulty_state", "uq_uqds_user_question", "unique"
    )
    _drop_constraint("user_knowledge_adaptive_state", "uq_ukas_user_kp", "unique")
    _drop_constraint("formula_graph_specs", "pk_formula_graph_specs", "pk")
