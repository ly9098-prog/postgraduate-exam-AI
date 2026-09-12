"""repair and enforce pomodoro integrity constraints

This corrective migration closes two gaps left by the earlier V2 constraint
migration:

* missing CHECK/index objects are created independently, so a partial prior apply
  cannot attempt to recreate an object that already exists;
* invalid legacy data no longer causes a silent successful migration.  The
  deployment fails with a precise message until the data is repaired, ensuring
  Alembic can never mark the revision complete while an advertised invariant is
  absent.

The migration is intentionally idempotent and re-verifies every required object
at the end.  ``downgrade`` is a no-op because these are canonical data-integrity
invariants and the migration cannot know which objects already existed before the
corrective revision was applied.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "y9z0a1b2c3d4"
down_revision: str | None = "x8y9z0a1b2c3"
branch_labels = None
depends_on = None

CK_PAUSE_ENDED = "ck_pomodoro_pause_intervals_ended_at"
UX_ONE_OPEN = "ux_pomodoro_pause_intervals_one_open"
IX_PAUSE_SESSION_STARTED = "ix_pomodoro_pause_intervals_session_started"
CK_SESSION_COMPLETED = "ck_pomodoro_sessions_completed_duration"
UX_ONE_ACTIVE = "ux_pomodoro_sessions_one_active_per_user"
UX_CLIENT_START = "ux_pomodoro_sessions_user_client_start_id"


def _has_index(bind, table: str, index: str) -> bool:
    return index in {i["name"] for i in sa.inspect(bind).get_indexes(table)}


def _has_check(bind, table: str, name: str) -> bool:
    return name in {c["name"] for c in sa.inspect(bind).get_check_constraints(table)}


def _scalar_count(bind, sql: str) -> int:
    return int(bind.execute(sa.text(sql)).scalar() or 0)


def _validate_legacy_data(bind) -> None:
    invalid_pause = _scalar_count(
        bind,
        "SELECT COUNT(*) FROM pomodoro_pause_intervals "
        "WHERE ended_at IS NOT NULL AND ended_at <= started_at",
    )
    if invalid_pause:
        raise RuntimeError(
            f"Cannot enforce {CK_PAUSE_ENDED}: {invalid_pause} pause interval(s) "
            "have ended_at <= started_at. Repair the rows before retrying the migration."
        )

    multiple_open = _scalar_count(
        bind,
        "SELECT COUNT(*) FROM ("
        "SELECT session_id FROM pomodoro_pause_intervals "
        "WHERE ended_at IS NULL GROUP BY session_id HAVING COUNT(*) > 1"
        ") AS duplicate_open_pauses",
    )
    if multiple_open:
        raise RuntimeError(
            f"Cannot enforce {UX_ONE_OPEN}: {multiple_open} session(s) have more than "
            "one open pause interval. Repair the rows before retrying the migration."
        )

    invalid_completed = _scalar_count(
        bind,
        "SELECT COUNT(*) FROM pomodoro_sessions "
        "WHERE status = 'completed' AND ("
        "end_time IS NULL OR actual_duration IS NULL OR "
        "actual_duration < 0 OR end_time < start_time)",
    )
    if invalid_completed:
        raise RuntimeError(
            f"Cannot enforce {CK_SESSION_COMPLETED}: {invalid_completed} completed "
            "session(s) have invalid end_time/actual_duration. Repair the rows before "
            "retrying the migration."
        )


def _ensure_pause_constraints(bind) -> None:
    if not _has_check(bind, "pomodoro_pause_intervals", CK_PAUSE_ENDED):
        with op.batch_alter_table("pomodoro_pause_intervals") as batch_op:
            batch_op.create_check_constraint(
                CK_PAUSE_ENDED,
                "ended_at IS NULL OR ended_at > started_at",
            )

    # SQLite batch table recreation can discard indexes that cannot be reflected.
    # Re-inspect after the CHECK is installed and recreate each index independently.
    if not _has_index(bind, "pomodoro_pause_intervals", IX_PAUSE_SESSION_STARTED):
        op.create_index(
            IX_PAUSE_SESSION_STARTED,
            "pomodoro_pause_intervals",
            ["session_id", "started_at"],
        )
    if not _has_index(bind, "pomodoro_pause_intervals", UX_ONE_OPEN):
        op.create_index(
            UX_ONE_OPEN,
            "pomodoro_pause_intervals",
            ["session_id"],
            unique=True,
            sqlite_where=sa.text("ended_at IS NULL"),
            postgresql_where=sa.text("ended_at IS NULL"),
        )


def _ensure_session_constraints(bind) -> None:
    if not _has_check(bind, "pomodoro_sessions", CK_SESSION_COMPLETED):
        with op.batch_alter_table("pomodoro_sessions") as batch_op:
            batch_op.create_check_constraint(
                CK_SESSION_COMPLETED,
                "status != 'completed' OR (end_time >= start_time AND actual_duration >= 0)",
            )

    # Preserve/recover the two uniqueness guards that make start idempotent and
    # prevent cross-device creation of multiple active sessions.
    if not _has_index(bind, "pomodoro_sessions", UX_ONE_ACTIVE):
        op.create_index(
            UX_ONE_ACTIVE,
            "pomodoro_sessions",
            ["user_id"],
            unique=True,
            sqlite_where=sa.text("status IN ('running', 'paused')"),
            postgresql_where=sa.text("status IN ('running', 'paused')"),
        )
    if not _has_index(bind, "pomodoro_sessions", UX_CLIENT_START):
        op.create_index(
            UX_CLIENT_START,
            "pomodoro_sessions",
            ["user_id", "client_start_id"],
            unique=True,
            sqlite_where=sa.text("client_start_id IS NOT NULL"),
            postgresql_where=sa.text("client_start_id IS NOT NULL"),
        )


def _verify_postconditions(bind) -> None:
    missing: list[str] = []
    if not _has_check(bind, "pomodoro_pause_intervals", CK_PAUSE_ENDED):
        missing.append(CK_PAUSE_ENDED)
    for name in (IX_PAUSE_SESSION_STARTED, UX_ONE_OPEN):
        if not _has_index(bind, "pomodoro_pause_intervals", name):
            missing.append(name)
    if not _has_check(bind, "pomodoro_sessions", CK_SESSION_COMPLETED):
        missing.append(CK_SESSION_COMPLETED)
    for name in (UX_ONE_ACTIVE, UX_CLIENT_START):
        if not _has_index(bind, "pomodoro_sessions", name):
            missing.append(name)
    if missing:
        raise RuntimeError(
            "Pomodoro corrective migration finished without required database "
            f"invariants: {', '.join(missing)}"
        )


def upgrade() -> None:
    bind = op.get_bind()
    _validate_legacy_data(bind)
    _ensure_pause_constraints(bind)
    _ensure_session_constraints(bind)
    _verify_postconditions(bind)


def downgrade() -> None:
    # No-op by design. These invariants are canonical and may have existed before
    # this corrective revision; dropping them would make downgrade destructive.
    pass
