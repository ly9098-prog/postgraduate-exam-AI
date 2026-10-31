"""Account lifecycle: cancelled-account erasure and inactive-account anonymization.

Cancellation tombstones ``users.openid`` immediately (``erasing:``); the sweep then
purges every user-scoped row and export file and marks the user ``erased:``.
Accounts inactive for ``INACTIVITY_DAYS`` only have their login identifier
anonymized (``anonymized:``). The state lives in the openid prefix so no schema
change is needed; every step is idempotent.
"""

import logging
import uuid
from datetime import timedelta

from sqlalchemy import delete, exists, select

from app.core.database import Base
from app.core.time_utils import utcnow
from app.models.practice_record import PracticeRecord
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.services.storage_backend import get_export_storage

logger = logging.getLogger(__name__)

ERASING_PREFIX = "erasing:"
ERASED_PREFIX = "erased:"
ANONYMIZED_PREFIX = "anonymized:"
INACTIVITY_DAYS = 365
_BATCH = 100

# Child rows of user-scoped tables that carry no user_id of their own; SQLite does
# not enforce the ON DELETE CASCADE that PostgreSQL applies to them.
_CHILD_TABLES = (
    ("pomodoro_pause_intervals", "session_id", "pomodoro_sessions"),
    ("pomodoro_subject_allocations", "session_id", "pomodoro_sessions"),
    ("study_plan_days", "plan_id", "study_plans"),
    ("exam_answers", "attempt_id", "exam_attempts"),
)


def _tombstone(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex}"


def tombstone_cancelled_user(user: User) -> None:
    """Drop the real WeChat identity at cancellation time (caller commits).

    Banned accounts keep their openid so cancelling cannot shed a ban; they are
    also left out of the erasure sweep (abuse-prevention retention).
    """
    user.nickname = None
    user.avatar_url = None
    if not user.is_banned:
        user.openid = _tombstone(ERASING_PREFIX)


async def _delete_export_files(db, user_id: int) -> None:
    from app.models.export_task import ExportTask

    keys = (
        await db.execute(
            select(ExportTask.file_key).where(
                ExportTask.user_id == user_id, ExportTask.file_key.isnot(None)
            )
        )
    ).scalars().all()
    if not keys:
        return
    storage = get_export_storage()
    for key in keys:
        if not await storage.delete(key) and await storage.exists(key):
            raise RuntimeError(f"export file could not be deleted for user_id={user_id}")


async def _purge_user_rows(db, user_id: int) -> None:
    import app.models  # noqa: F401 - register every table before walking metadata

    tables = Base.metadata.tables
    for child, fk_column, parent in _CHILD_TABLES:
        if child in tables and parent in tables:
            parent_ids = select(tables[parent].c.id).where(tables[parent].c.user_id == user_id)
            await db.execute(delete(tables[child]).where(tables[child].c[fk_column].in_(parent_ids)))
    # Reverse dependency order so referencing rows go before the rows they point at.
    for table in reversed(Base.metadata.sorted_tables):
        if table.name == "users" or "user_id" not in table.columns:
            continue
        await db.execute(delete(table).where(table.c.user_id == user_id))


async def purge_cancelled_user(db, user: User) -> None:
    await _delete_export_files(db, user.id)
    await _purge_user_rows(db, user.id)
    user.openid = _tombstone(ERASED_PREFIX)
    user.nickname = None
    user.avatar_url = None
    await db.commit()


async def _purge_pending(db) -> tuple[int, int]:
    user_ids = (
        await db.execute(
            select(User.id)
            .where(
                User.deleted_at.isnot(None),
                User.is_banned.is_(False),
                ~User.openid.startswith(ERASED_PREFIX),
            )
            .order_by(User.id)
            .limit(_BATCH)
        )
    ).scalars().all()
    purged = failed = 0
    for user_id in user_ids:
        try:
            user = await db.get(User, user_id)
            await purge_cancelled_user(db, user)
            purged += 1
        except Exception:
            await db.rollback()
            failed += 1
            logger.exception("Account erasure failed for user_id=%s; will retry", user_id)
    return purged, failed


async def _anonymize_inactive(db) -> int:
    cutoff = utcnow() - timedelta(days=INACTIVITY_DAYS)
    recent_token = exists().where(RefreshToken.user_id == User.id, RefreshToken.created_at >= cutoff)
    recent_practice = exists().where(PracticeRecord.user_id == User.id, PracticeRecord.created_at >= cutoff)
    users = (
        await db.execute(
            select(User)
            .where(
                User.deleted_at.is_(None),
                ~User.openid.startswith(ERASING_PREFIX),
                ~User.openid.startswith(ERASED_PREFIX),
                ~User.openid.startswith(ANONYMIZED_PREFIX),
                User.updated_at < cutoff,
                ~recent_token,
                ~recent_practice,
            )
            .limit(_BATCH)
        )
    ).scalars().all()
    for user in users:
        user.openid = _tombstone(ANONYMIZED_PREFIX)
        await db.execute(delete(RefreshToken).where(RefreshToken.user_id == user.id))
    if users:
        await db.commit()
    return len(users)


async def run_account_lifecycle_sweep(db) -> dict[str, int]:
    purged, failed = await _purge_pending(db)
    anonymized = await _anonymize_inactive(db)
    return {"purged": purged, "failed": failed, "anonymized": anonymized}
