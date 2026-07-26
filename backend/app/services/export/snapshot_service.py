"""Manage export snapshots — stable data for re-export independent of source changes."""

from __future__ import annotations

import json
import logging
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.export_task import ExportSnapshot

logger = logging.getLogger(__name__)

# Safety limits
_MAX_SNAPSHOT_BYTES = 5 * 1024 * 1024  # 5 MB
_MAX_QUESTION_CONTENT_BYTES = 100 * 1024  # 100 KB per question in snapshot


async def create_snapshot(
    db: AsyncSession,
    user_id: int,
    snapshot_data: dict,
) -> str:
    """Create and persist a snapshot, returning its UUID.

    Raises:
        ValueError: if the snapshot data exceeds size limits.
    """
    snapshot_id = str(uuid4())
    raw_bytes = len(json.dumps(snapshot_data, default=str))

    if raw_bytes > _MAX_SNAPSHOT_BYTES:
        raise ValueError(
            f"快照数据过大 ({raw_bytes} bytes)，超出限制 ({_MAX_SNAPSHOT_BYTES})"
        )

    snapshot = ExportSnapshot(
        id=snapshot_id,
        user_id=user_id,
        data=snapshot_data,
        data_size_bytes=raw_bytes,
    )
    db.add(snapshot)
    await db.flush()
    logger.info("Snapshot %s created (%d bytes)", snapshot_id, raw_bytes)
    return snapshot_id


async def load_snapshot(
    db: AsyncSession,
    snapshot_id: str,
    user_id: int,
) -> dict | None:
    """Load snapshot data, verifying it belongs to the user."""
    result = await db.execute(
        select(ExportSnapshot).where(
            ExportSnapshot.id == snapshot_id,
            ExportSnapshot.user_id == user_id,
        )
    )
    snap = result.scalar_one_or_none()
    if snap is None:
        return None
    return snap.data


async def delete_snapshot(
    db: AsyncSession,
    snapshot_id: str,
) -> bool:
    """Delete a snapshot by ID."""
    result = await db.execute(
        select(ExportSnapshot).where(ExportSnapshot.id == snapshot_id)
    )
    snap = result.scalar_one_or_none()
    if snap is None:
        return False
    await db.delete(snap)
    return True


async def delete_snapshots_by_user(
    db: AsyncSession,
    user_id: int,
) -> int:
    """Delete all snapshots for a user (e.g., on account deletion)."""
    result = await db.execute(
        select(ExportSnapshot).where(ExportSnapshot.user_id == user_id)
    )
    snaps = result.scalars().all()
    for snap in snaps:
        await db.delete(snap)
    return len(snaps)
