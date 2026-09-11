"""Worker credential service — hash, verify, rotate credentials.

Plaintext keys are never stored. Only SHA-256 hashes are persisted.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import or_

from app.core.time_utils import normalize_to_naive_utc, utcnow
from app.models.worker_credential import WorkerCredential


def hash_key(key: str) -> str:
    """Return SHA-256 hex digest of the key."""
    return hashlib.sha256(key.encode()).hexdigest()


def generate_key() -> str:
    """Generate a new cryptographically random API key."""
    return secrets.token_hex(32)  # 64 hex chars = 256 bits


def constant_time_compare(a: str, b: str) -> bool:
    """Compare two same-format digests in constant time."""
    return secrets.compare_digest(a, b)


async def create_credential(
    db: AsyncSession,
    worker_id: str,
    *,
    expires_at: datetime | None = None,
) -> tuple[WorkerCredential, str]:
    """Create a new worker credential. Returns (credential, raw_key).

    The raw key is returned only once (at creation time). It is NOT stored.
    """
    raw_key = generate_key()
    credential = WorkerCredential(
        id=f"wc-{secrets.token_hex(8)}",
        worker_id=worker_id,
        key_hash=hash_key(raw_key),
        is_active=True,
        expires_at=normalize_to_naive_utc(expires_at)
        if expires_at is not None
        else None,
    )
    db.add(credential)
    await db.flush()
    return credential, raw_key


async def verify_credential(
    db: AsyncSession,
    worker_id: str,
    raw_key: str,
) -> WorkerCredential | None:
    """Verify a raw key against stored credentials for a worker.

    Checks all active, non-expired credentials for the worker.
    Uses constant-time comparison per credential. Returns the matching
    credential (or None if no match).
    """
    now = utcnow()

    result = await db.execute(
        select(WorkerCredential).where(
            WorkerCredential.worker_id == worker_id,
            WorkerCredential.is_active,
            or_(
                WorkerCredential.expires_at.is_(None),
                WorkerCredential.expires_at > now,
            ),
        )
    )
    credentials = list(result.scalars().all())

    candidate_hash = hash_key(raw_key)
    for cred in credentials:
        if constant_time_compare(candidate_hash, cred.key_hash):
            return cred

    return None


async def rotate_credential(
    db: AsyncSession,
    credential_id: str,
) -> tuple[WorkerCredential, str] | None:
    """Rotate a credential: disable old one, create new one.

    Returns (new_credential, raw_key) or None if credential_id not found.
    """
    old = await db.get(WorkerCredential, credential_id)
    if old is None:
        return None

    # Disable old credential
    old.is_active = False
    old.rotated_at = utcnow()

    # Create new credential for same worker
    return await create_credential(db, old.worker_id)


async def list_credentials(
    db: AsyncSession,
    worker_id: str | None = None,
    active_only: bool = False,
) -> list[WorkerCredential]:
    """List credentials, optionally filtered."""
    query = select(WorkerCredential)
    if worker_id is not None:
        query = query.where(WorkerCredential.worker_id == worker_id)
    if active_only:
        query = query.where(WorkerCredential.is_active)
    query = query.order_by(WorkerCredential.created_at.desc())

    result = await db.execute(query)
    return list(result.scalars().all())
