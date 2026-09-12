"""verify and repair pomodoro constraint/index definitions

Revision y9z0a1b2c3d4 guaranteed that the named integrity objects exist.  This
follow-up also verifies their definitions, because a historically mis-created
object can have the correct name while enforcing the wrong columns, uniqueness,
or partial predicate.

The migration is deliberately fail-loud on legacy data that would violate the
canonical definitions.  It repairs mismatched named objects in-place and then
re-inspects the database to prove the expected definitions are present.
"""
from __future__ import annotations

import re

import sqlalchemy as sa

from alembic import op

revision: str = "z0a1b2c3d4e5"
down_revision: str | None = "y9z0a1b2c3d4"
branch_labels = None
depends_on = None

CK_PAUSE_ENDED = "ck_pomodoro_pause_intervals_ended_at"
UX_ONE_OPEN = "ux_pomodoro_pause_intervals_one_open"
IX_PAUSE_SESSION_STARTED = "ix_pomodoro_pause_intervals_session_started"
CK_SESSION_COMPLETED = "ck_pomodoro_sessions_completed_duration"
UX_ONE_ACTIVE = "ux_pomodoro_sessions_one_active_per_user"
UX_CLIENT_START = "ux_pomodoro_sessions_user_client_start_id"


def _scalar_count(bind, sql: str) -> int:
    return int(bind.execute(sa.text(sql)).scalar() or 0)


def _compact_sql(value) -> str:
    if value is None:
        return ""
    text = str(value).lower()
    text = text.replace('"', '').replace("'", "").replace("`", "")
    text = re.sub(r"\s+", "", text)
    text = text.replace("(", "").replace(")", "")
    return text


def _index_info(bind, table: str, name: str):
    return next(
        (item for item in sa.inspect(bind).get_indexes(table) if item.get("name") == name),
        None,
    )


def _check_info(bind, table: str, name: str):
    return next(
        (item for item in sa.inspect(bind).get_check_constraints(table) if item.get("name") == name),
        None,
    )


def _index_where_text(bind, info) -> str:
    if not info:
        return ""
    options = info.get("dialect_options") or {}
    dialect = bind.dialect.name
    where = options.get(f"{dialect}_where")
    if where is None:
        # Be tolerant of inspectors that expose a different dialect key when
        # reflecting through a compatibility layer.
        where = options.get("postgresql_where") or options.get("sqlite_where")
    return _compact_sql(where)


def _index_matches(
    bind,
    table: str,
    name: str,
    *,
    columns: tuple[str, ...],
    unique: bool,
    predicate_tokens: tuple[str, ...] = (),
) -> bool:
    info = _index_info(bind, table, name)
    if not info:
        return False
    if tuple(info.get("column_names") or ()) != columns:
        return False
    if bool(info.get("unique")) != unique:
        return False
    if predicate_tokens:
        where = _index_where_text(bind, info)
        if not where:
            return False
        return all(_compact_sql(token) in where for token in predicate_tokens)
    return not _index_where_text(bind, info)


def _pause_check_matches(bind) -> bool:
    info = _check_info(bind, "pomodoro_pause_intervals", CK_PAUSE_ENDED)
    if not info:
        return False
    sql = _compact_sql(info.get("sqltext"))
    return (
        "ended_atisnull" in sql
        and "ended_at>started_at" in sql
        and "ended_at>=started_at" not in sql
    )


def _completed_check_matches(bind) -> bool:
    info = _check_info(bind, "pomodoro_sessions", CK_SESSION_COMPLETED)
    if not info:
        return False
    sql = _compact_sql(info.get("sqltext"))
    # PostgreSQL reflection may inject ::text casts around VARCHAR operands,
    # so validate the semantic guard tokens rather than one exact rendering.
    status_guard = (
        "status" in sql
        and "completed" in sql
        and ("!=" in sql or "<>" in sql)
    )
    return (
        status_guard
        and "end_time>=start_time" in sql
        and "actual_duration>=0" in sql
    )


def _validate_legacy_data(bind) -> None:
    invalid_pause = _scalar_count(
        bind,
        "SELECT COUNT(*) FROM pomodoro_pause_intervals "
        "WHERE ended_at IS NOT NULL AND ended_at <= started_at",
    )
    if invalid_pause:
        raise RuntimeError(
            f"Cannot repair {CK_PAUSE_ENDED}: {invalid_pause} pause interval(s) "
            "have ended_at <= started_at."
        )

    duplicate_open = _scalar_count(
        bind,
        "SELECT COUNT(*) FROM ("
        "SELECT session_id FROM pomodoro_pause_intervals "
        "WHERE ended_at IS NULL GROUP BY session_id HAVING COUNT(*) > 1"
        ") AS duplicate_open_pauses",
    )
    if duplicate_open:
        raise RuntimeError(
            f"Cannot repair {UX_ONE_OPEN}: {duplicate_open} session(s) have more than one open pause."
        )

    invalid_completed = _scalar_count(
        bind,
        "SELECT COUNT(*) FROM pomodoro_sessions "
        "WHERE status = 'completed' AND ("
        "end_time IS NULL OR actual_duration IS NULL OR actual_duration < 0 OR end_time < start_time)",
    )
    if invalid_completed:
        raise RuntimeError(
            f"Cannot repair {CK_SESSION_COMPLETED}: {invalid_completed} completed session(s) are invalid."
        )

    duplicate_active = _scalar_count(
        bind,
        "SELECT COUNT(*) FROM ("
        "SELECT user_id FROM pomodoro_sessions "
        "WHERE status IN ('running', 'paused') "
        "GROUP BY user_id HAVING COUNT(*) > 1"
        ") AS duplicate_active_sessions",
    )
    if duplicate_active:
        raise RuntimeError(
            f"Cannot repair {UX_ONE_ACTIVE}: {duplicate_active} user(s) have multiple active sessions."
        )

    duplicate_client_start = _scalar_count(
        bind,
        "SELECT COUNT(*) FROM ("
        "SELECT user_id, client_start_id FROM pomodoro_sessions "
        "WHERE client_start_id IS NOT NULL "
        "GROUP BY user_id, client_start_id HAVING COUNT(*) > 1"
        ") AS duplicate_client_starts",
    )
    if duplicate_client_start:
        raise RuntimeError(
            f"Cannot repair {UX_CLIENT_START}: {duplicate_client_start} duplicate user/client_start_id pair(s) exist."
        )


def _ensure_checks(bind) -> None:
    if not _pause_check_matches(bind):
        existing = _check_info(bind, "pomodoro_pause_intervals", CK_PAUSE_ENDED)
        with op.batch_alter_table("pomodoro_pause_intervals") as batch_op:
            if existing:
                batch_op.drop_constraint(CK_PAUSE_ENDED, type_="check")
            batch_op.create_check_constraint(
                CK_PAUSE_ENDED,
                "ended_at IS NULL OR ended_at > started_at",
            )

    if not _completed_check_matches(bind):
        existing = _check_info(bind, "pomodoro_sessions", CK_SESSION_COMPLETED)
        with op.batch_alter_table("pomodoro_sessions") as batch_op:
            if existing:
                batch_op.drop_constraint(CK_SESSION_COMPLETED, type_="check")
            batch_op.create_check_constraint(
                CK_SESSION_COMPLETED,
                "status != 'completed' OR (end_time >= start_time AND actual_duration >= 0)",
            )


def _ensure_index(
    bind,
    table: str,
    name: str,
    *,
    columns: tuple[str, ...],
    unique: bool,
    predicate_sql: str | None = None,
    predicate_tokens: tuple[str, ...] = (),
) -> None:
    if _index_matches(
        bind,
        table,
        name,
        columns=columns,
        unique=unique,
        predicate_tokens=predicate_tokens,
    ):
        return
    if _index_info(bind, table, name):
        op.drop_index(name, table_name=table)
    kwargs = {}
    if predicate_sql is not None:
        predicate = sa.text(predicate_sql)
        kwargs["sqlite_where"] = predicate
        kwargs["postgresql_where"] = predicate
    op.create_index(name, table, list(columns), unique=unique, **kwargs)


def _ensure_indexes(bind) -> None:
    # Batch CHECK repairs can rebuild SQLite tables and discard indexes, so index
    # repair always runs after all CHECK work and re-inspects each object.
    _ensure_index(
        bind,
        "pomodoro_pause_intervals",
        IX_PAUSE_SESSION_STARTED,
        columns=("session_id", "started_at"),
        unique=False,
    )
    _ensure_index(
        bind,
        "pomodoro_pause_intervals",
        UX_ONE_OPEN,
        columns=("session_id",),
        unique=True,
        predicate_sql="ended_at IS NULL",
        predicate_tokens=("ended_at", "isnull"),
    )
    _ensure_index(
        bind,
        "pomodoro_sessions",
        UX_ONE_ACTIVE,
        columns=("user_id",),
        unique=True,
        predicate_sql="status IN ('running', 'paused')",
        predicate_tokens=("status", "running", "paused"),
    )
    _ensure_index(
        bind,
        "pomodoro_sessions",
        UX_CLIENT_START,
        columns=("user_id", "client_start_id"),
        unique=True,
        predicate_sql="client_start_id IS NOT NULL",
        predicate_tokens=("client_start_id", "isnotnull"),
    )


def _verify_postconditions(bind) -> None:
    failures: list[str] = []
    if not _pause_check_matches(bind):
        failures.append(f"{CK_PAUSE_ENDED} definition")
    if not _completed_check_matches(bind):
        failures.append(f"{CK_SESSION_COMPLETED} definition")

    specs = (
        ("pomodoro_pause_intervals", IX_PAUSE_SESSION_STARTED, ("session_id", "started_at"), False, ()),
        ("pomodoro_pause_intervals", UX_ONE_OPEN, ("session_id",), True, ("ended_at", "isnull")),
        ("pomodoro_sessions", UX_ONE_ACTIVE, ("user_id",), True, ("status", "running", "paused")),
        ("pomodoro_sessions", UX_CLIENT_START, ("user_id", "client_start_id"), True, ("client_start_id", "isnotnull")),
    )
    for table, name, columns, unique, tokens in specs:
        if not _index_matches(
            bind,
            table,
            name,
            columns=columns,
            unique=unique,
            predicate_tokens=tokens,
        ):
            failures.append(f"{name} definition")
    if failures:
        raise RuntimeError(
            "Pomodoro definition verification failed: " + ", ".join(failures)
        )


def upgrade() -> None:
    bind = op.get_bind()
    _validate_legacy_data(bind)
    _ensure_checks(bind)
    _ensure_indexes(bind)
    _verify_postconditions(bind)


def downgrade() -> None:
    # No-op: all objects are canonical integrity invariants and may predate this
    # revision. Dropping them would weaken data safety.
    pass
