import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.refresh_token import RefreshToken


REFRESH_TOKEN_DAYS = 90


def _generate_raw_token() -> str:
    """Generate a cryptographically random opaque token (64 hex chars, 256-bit entropy)."""
    return secrets.token_hex(32)


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def create_refresh_token(db: AsyncSession, user_id: int) -> str:
    """Create a new refresh token for user. Returns the raw token (only time it's available)."""
    raw = _generate_raw_token()
    token_hash = _hash_token(raw)
    expires_at = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_DAYS)
    token = RefreshToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
    db.add(token)
    await db.commit()
    return raw


async def verify_refresh_token(db: AsyncSession, raw_token: str) -> RefreshToken | None:
    """Verify a raw refresh token. Returns the token record if valid, None otherwise.

    Handles rotation grace period: a token revoked within the last 60 seconds
    is still accepted to handle concurrent refresh race conditions.
    """
    token_hash = _hash_token(raw_token)
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    token = result.scalar_one_or_none()
    if not token:
        return None

    now = datetime.utcnow()

    # Check expiry
    if token.expires_at < now:
        return None

    # Check revocation with 60-second grace period for rotation races
    if token.revoked_at is not None:
        if (now - token.revoked_at).total_seconds() > 60:
            return None

    return token


async def rotate_refresh_token(db: AsyncSession, current_token: RefreshToken) -> str:
    """Revoke current token and issue a new one. Returns the new raw token.

    INSERT (new) → UPDATE (revoke old) ordering in a single transaction:
    if the second step fails, the old token remains valid (safe degradation).
    """
    raw = _generate_raw_token()
    token_hash = _hash_token(raw)
    expires_at = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_DAYS)
    new_token = RefreshToken(
        user_id=current_token.user_id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(new_token)
    current_token.revoked_at = datetime.utcnow()
    await db.commit()
    return raw


async def revoke_all_user_tokens(db: AsyncSession, user_id: int) -> None:
    """Revoke all active refresh tokens for a user."""
    now = datetime.utcnow()
    await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    await db.commit()
