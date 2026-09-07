"""normalize 408 subject codes to one canonical catalog

Revision ID: s408canonical20260907
Revises: a4c5d6e7f8b9
Create Date: 2026-09-07

This is the one-time boundary between historical subject codes and the strict
runtime catalog. After this migration the application accepts only:

- exam408
- data_structure
- computer_organization
- operating_system
- computer_network

Legacy aliases remain only in this migration so upgraded databases can be
normalized safely. Subject primary keys are preserved; all subject_id foreign
keys therefore remain stable.
"""
from __future__ import annotations

import json
import re
from typing import Any

from alembic import op
import sqlalchemy as sa

revision = "s408canonical20260907"
down_revision = "a4c5d6e7f8b9"
branch_labels = None
depends_on = None

CANONICAL_CATALOG: tuple[tuple[str, str, int], ...] = (
    ("exam408", "408计算机综合", 0),
    ("data_structure", "数据结构", 10),
    ("computer_organization", "计算机组成原理", 20),
    ("operating_system", "操作系统", 30),
    ("computer_network", "计算机网络", 40),
)

LEGACY_CODE_TO_CANONICAL: dict[str, str] = {
    # 408 root
    "408": "exam408",
    "computer": "exam408",
    "cs": "exam408",
    "computer_science": "exam408",
    "exam408": "exam408",
    # four disciplines
    "ds": "data_structure",
    "exam408-ds": "data_structure",
    "data_structure": "data_structure",
    "co": "computer_organization",
    "exam408-co": "computer_organization",
    "computer_organization": "computer_organization",
    "os": "operating_system",
    "exam408-os": "operating_system",
    "operating_system": "operating_system",
    "cn": "computer_network",
    "exam408-cn": "computer_network",
    "computer_network": "computer_network",
}

LEGACY_NAME_TO_CANONICAL: dict[str, str] = {
    "408": "exam408",
    "408计算机综合": "exam408",
    "计算机学科专业基础综合": "exam408",
    "计算机基础": "exam408",
    "数据结构": "data_structure",
    "计算机组成原理": "computer_organization",
    "组成原理": "computer_organization",
    "计组": "computer_organization",
    "操作系统": "operating_system",
    "计算机网络": "computer_network",
    "计网": "computer_network",
}

LEGACY_CODES = frozenset(
    code for code, canonical in LEGACY_CODE_TO_CANONICAL.items() if code != canonical
)


def _has_table(inspector: sa.Inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _has_column(inspector: sa.Inspector, table: str, column: str) -> bool:
    return any(c["name"] == column for c in inspector.get_columns(table))


def _canonical_target(code: Any, name: Any) -> str | None:
    raw_code = str(code or "").strip().lower()
    if raw_code in LEGACY_CODE_TO_CANONICAL:
        return LEGACY_CODE_TO_CANONICAL[raw_code]
    return LEGACY_NAME_TO_CANONICAL.get(str(name or "").strip())


def _normalize_json(value: Any) -> Any:
    """Normalize exact legacy subject-code values inside active task/import JSON."""
    if isinstance(value, str):
        raw = value.strip().lower()
        return LEGACY_CODE_TO_CANONICAL.get(raw, value)
    if isinstance(value, list):
        return [_normalize_json(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_json(item) for key, item in value.items()}
    return value


def _normalize_json_column(bind, inspector, table: str, pk: str, column: str) -> None:
    if not _has_table(inspector, table) or not _has_column(inspector, table, column):
        return

    # Reflect the real column type so SQLite JSON and PostgreSQL JSON/JSONB are
    # decoded/encoded by SQLAlchemy instead of being treated as opaque text.
    metadata = sa.MetaData()
    t = sa.Table(table, metadata, autoload_with=bind)
    rows = bind.execute(sa.select(t.c[pk], t.c[column])).fetchall()
    for row_id, value in rows:
        if value is None:
            continue
        normalized = _normalize_json(value)
        if normalized != value:
            bind.execute(
                sa.update(t).where(t.c[pk] == row_id).values({column: normalized})
            )


def _normalize_ai_config_text(bind, inspector) -> None:
    if not _has_table(inspector, "admin_ai_configs"):
        return
    t = sa.table(
        "admin_ai_configs",
        sa.column("config_key", sa.String()),
        sa.column("config_value", sa.Text()),
    )
    replacements = {
        "exam408-ds": "data_structure",
        "exam408-co": "computer_organization",
        "exam408-os": "operating_system",
        "exam408-cn": "computer_network",
    }
    for key, value in bind.execute(sa.select(t.c.config_key, t.c.config_value)).fetchall():
        if not value:
            continue
        normalized = str(value)

        # Config values that are explicitly subject-code collections can safely
        # normalize even the short historical codes because their semantics are
        # unambiguous at this boundary.
        if str(key or "").strip().lower() == "vector_allowlist":
            try:
                parsed = json.loads(normalized)
            except (TypeError, json.JSONDecodeError):
                parsed = None
            if isinstance(parsed, (list, dict)):
                parsed_normalized = _normalize_json(parsed)
                normalized = json.dumps(parsed_normalized, ensure_ascii=False, separators=(",", ":"))

        # Prompt/config prose only replaces the unambiguous long historical
        # tokens; short words such as ``os`` are not rewritten in free text.
        for old, new in replacements.items():
            normalized = re.sub(rf"(?<![A-Za-z0-9_]){re.escape(old)}(?![A-Za-z0-9_])", new, normalized)
        if normalized != value:
            bind.execute(
                sa.update(t).where(t.c.config_key == key).values(config_value=normalized)
            )


def _normalize_formula_scope(bind, inspector) -> None:
    for table in ("formula_categories", "formula_cards"):
        if not _has_table(inspector, table) or not _has_column(inspector, table, "exam_scope"):
            continue
        t = sa.table(table, sa.column("exam_scope", sa.String()))
        bind.execute(
            sa.update(t)
            .where(sa.func.lower(t.c.exam_scope).in_(["408", "computer"]))
            .values(exam_scope="exam408")
        )


def _ensure_catalog(bind, inspector) -> dict[str, int]:
    if not _has_table(inspector, "subjects"):
        raise RuntimeError("subjects table is missing")

    subjects = sa.table(
        "subjects",
        sa.column("id", sa.Integer()),
        sa.column("parent_id", sa.Integer()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("level", sa.SmallInteger()),
        sa.column("path", sa.String()),
        sa.column("sort_order", sa.Integer()),
        sa.column("is_active", sa.Boolean()),
    )
    rows = bind.execute(
        sa.select(
            subjects.c.id,
            subjects.c.parent_id,
            subjects.c.code,
            subjects.c.name,
            subjects.c.level,
            subjects.c.path,
            subjects.c.sort_order,
            subjects.c.is_active,
        )
    ).fetchall()

    grouped: dict[str, list[Any]] = {}
    for row in rows:
        target = _canonical_target(row.code, row.name)
        if target:
            grouped.setdefault(target, []).append(row)

    duplicates = {key: vals for key, vals in grouped.items() if len(vals) > 1}
    if duplicates:
        detail = ", ".join(
            f"{code}: ids={[row.id for row in vals]}" for code, vals in sorted(duplicates.items())
        )
        raise RuntimeError(
            "408 canonical migration found duplicate subject identities; "
            "manual data review is required before migration: " + detail
        )

    canonical_ids: dict[str, int] = {}
    catalog_names = {code: name for code, name, _ in CANONICAL_CATALOG}
    catalog_order = {code: order for code, _, order in CANONICAL_CATALOG}

    # Normalize/create root first so children can be re-parented deterministically.
    root_rows = grouped.get("exam408", [])
    if root_rows:
        root_id = int(root_rows[0].id)
        bind.execute(
            sa.update(subjects).where(subjects.c.id == root_id).values(
                parent_id=None,
                code="exam408",
                name=catalog_names["exam408"],
                level=1,
                path="exam408",
                sort_order=catalog_order["exam408"],
                is_active=True,
            )
        )
    else:
        bind.execute(
            sa.insert(subjects).values(
                parent_id=None,
                code="exam408",
                name=catalog_names["exam408"],
                level=1,
                path="exam408",
                sort_order=catalog_order["exam408"],
                is_active=True,
            )
        )
        root_id = int(bind.execute(
            sa.select(subjects.c.id).where(subjects.c.code == "exam408")
        ).scalar_one())
    canonical_ids["exam408"] = root_id

    for code, name, sort_order in CANONICAL_CATALOG[1:]:
        matches = grouped.get(code, [])
        if matches:
            sid = int(matches[0].id)
            bind.execute(
                sa.update(subjects).where(subjects.c.id == sid).values(
                    parent_id=root_id,
                    code=code,
                    name=name,
                    level=2,
                    path=f"exam408/{code}",
                    sort_order=sort_order,
                    is_active=True,
                )
            )
        else:
            bind.execute(
                sa.insert(subjects).values(
                    parent_id=root_id,
                    code=code,
                    name=name,
                    level=2,
                    path=f"exam408/{code}",
                    sort_order=sort_order,
                    is_active=True,
                )
            )
            sid = int(bind.execute(
                sa.select(subjects.c.id).where(subjects.c.code == code)
            ).scalar_one())
        canonical_ids[code] = sid

    # Current product is 408-only. Keep other subject rows for future reactivation,
    # but make their inactive state explicit at the data layer.
    bind.execute(
        sa.update(subjects)
        .where(subjects.c.id.notin_(list(canonical_ids.values())))
        .values(is_active=False)
    )

    # Final invariant: no recognized legacy 408 code remains and exactly one row
    # exists for every canonical catalog entry.
    current = bind.execute(sa.select(subjects.c.id, subjects.c.code)).fetchall()
    bad = [str(row.code) for row in current if str(row.code or "").strip().lower() in LEGACY_CODES]
    if bad:
        raise RuntimeError("legacy 408 subject codes remain after migration: " + ", ".join(sorted(bad)))
    for code, _, _ in CANONICAL_CATALOG:
        count = sum(1 for row in current if str(row.code or "").strip().lower() == code)
        if count != 1:
            raise RuntimeError(f"canonical subject {code!r} must exist exactly once, found {count}")

    return canonical_ids


def _install_formula_scope_guard(bind, inspector) -> None:
    for table in ("formula_categories", "formula_cards"):
        if not _has_table(inspector, table) or not _has_column(inspector, table, "exam_scope"):
            continue
        if bind.dialect.name == "sqlite":
            insert_trigger = f"trg_{table}_canonical_scope_insert"
            update_trigger = f"trg_{table}_canonical_scope_update"
            op.execute(f"DROP TRIGGER IF EXISTS {insert_trigger}")
            op.execute(f"DROP TRIGGER IF EXISTS {update_trigger}")
            op.execute(f"""
                CREATE TRIGGER {insert_trigger}
                BEFORE INSERT ON {table}
                WHEN lower(NEW.exam_scope) IN ('408', 'computer')
                BEGIN
                    SELECT RAISE(ABORT, 'legacy formula exam_scope is forbidden');
                END
            """)
            op.execute(f"""
                CREATE TRIGGER {update_trigger}
                BEFORE UPDATE OF exam_scope ON {table}
                WHEN lower(NEW.exam_scope) IN ('408', 'computer')
                BEGIN
                    SELECT RAISE(ABORT, 'legacy formula exam_scope is forbidden');
                END
            """)
            continue

        constraint = f"ck_{table}_canonical_exam_scope"
        checks = {item.get("name") for item in inspector.get_check_constraints(table)}
        if constraint not in checks:
            op.create_check_constraint(
                constraint,
                table,
                "lower(exam_scope) NOT IN ('408', 'computer')",
            )


def _install_legacy_code_guard(bind, inspector) -> None:
    values = ",".join(f"'{code}'" for code in sorted(LEGACY_CODES))
    if bind.dialect.name == "sqlite":
        # SQLite cannot add a CHECK constraint without rebuilding a heavily
        # referenced table, so use equivalent write guards.
        op.execute("DROP TRIGGER IF EXISTS trg_subjects_no_legacy_408_insert")
        op.execute("DROP TRIGGER IF EXISTS trg_subjects_no_legacy_408_update")
        op.execute(f"""
            CREATE TRIGGER trg_subjects_no_legacy_408_insert
            BEFORE INSERT ON subjects
            WHEN lower(NEW.code) IN ({values})
            BEGIN
                SELECT RAISE(ABORT, 'legacy 408 subject code is forbidden');
            END
        """)
        op.execute(f"""
            CREATE TRIGGER trg_subjects_no_legacy_408_update
            BEFORE UPDATE OF code ON subjects
            WHEN lower(NEW.code) IN ({values})
            BEGIN
                SELECT RAISE(ABORT, 'legacy 408 subject code is forbidden');
            END
        """)
        return

    checks = {item.get("name") for item in inspector.get_check_constraints("subjects")}
    if "ck_subjects_no_legacy_408_code" not in checks:
        op.create_check_constraint(
            "ck_subjects_no_legacy_408_code",
            "subjects",
            f"lower(code) NOT IN ({values})",
        )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    _ensure_catalog(bind, inspector)
    inspector = sa.inspect(bind)
    _normalize_formula_scope(bind, inspector)
    _normalize_ai_config_text(bind, inspector)

    # These are active/replayable processing payloads. Normalize exact code
    # values so a retry after deployment cannot reintroduce old identifiers.
    _normalize_json_column(bind, inspector, "task_outbox", "id", "payload")
    _normalize_json_column(bind, inspector, "question_imports", "id", "raw_data")
    _normalize_json_column(bind, inspector, "question_imports", "id", "ai_metadata")

    inspector = sa.inspect(bind)
    _install_formula_scope_guard(bind, inspector)
    _install_legacy_code_guard(bind, sa.inspect(bind))


def downgrade() -> None:
    """Remove write guards only; canonical data is intentionally not reverted."""
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_subjects_no_legacy_408_insert")
        op.execute("DROP TRIGGER IF EXISTS trg_subjects_no_legacy_408_update")
        for table in ("formula_categories", "formula_cards"):
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_canonical_scope_insert")
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_canonical_scope_update")
        return

    inspector = sa.inspect(bind)
    if _has_table(inspector, "subjects"):
        checks = {item.get("name") for item in inspector.get_check_constraints("subjects")}
        if "ck_subjects_no_legacy_408_code" in checks:
            op.drop_constraint("ck_subjects_no_legacy_408_code", "subjects", type_="check")
    for table in ("formula_categories", "formula_cards"):
        if not _has_table(inspector, table):
            continue
        constraint = f"ck_{table}_canonical_exam_scope"
        checks = {item.get("name") for item in inspector.get_check_constraints(table)}
        if constraint in checks:
            op.drop_constraint(constraint, table, type_="check")
