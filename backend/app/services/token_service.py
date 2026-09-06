import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import utcnow
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
    expires_at = utcnow() + timedelta(days=REFRESH_TOKEN_DAYS)
    token = RefreshToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
    db.add(token)
    await db.commit()
    return raw


async def verify_refresh_token(db: AsyncSession, raw_token: str) -> RefreshToken | None:
    """Verify a raw refresh token. Revoked tokens are never accepted."""
    token_hash = _hash_token(raw_token)
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    token = result.scalar_one_or_none()
    if not token:
        return None

    now = utcnow()

    # Check expiry
    if token.expires_at < now:
        return None

    # A refresh token is single-use. A grace window would permit replay.
    if token.revoked_at is not None:
        return None

    return token


async def rotate_refresh_token(db: AsyncSession, current_token: RefreshToken) -> str:
    """Atomically consume the current token and issue a replacement."""
    now = utcnow()
    consumed = await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.id == current_token.id,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at >= now,
        )
        .values(revoked_at=now)
        .execution_options(synchronize_session=False)
    )
    if consumed.rowcount != 1:
        await db.rollback()
        raise ValueError("refresh token has already been consumed")

    raw = _generate_raw_token()
    token_hash = _hash_token(raw)
    expires_at = now + timedelta(days=REFRESH_TOKEN_DAYS)
    new_token = RefreshToken(
        user_id=current_token.user_id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(new_token)
    await db.commit()
    return raw


async def revoke_all_user_tokens(db: AsyncSession, user_id: int) -> None:
    """Revoke all active refresh tokens for a user."""
    now = utcnow()
    await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    await db.commit()


async def cleanup_expired_tokens(db: AsyncSession) -> int:
    """Delete expired or long-revoked refresh tokens. Returns count of deleted rows."""
    now = utcnow()
    result = await db.execute(
        delete(RefreshToken).where(
            (RefreshToken.expires_at < now)
            | ((RefreshToken.revoked_at.isnot(None)) & (RefreshToken.revoked_at < now - timedelta(hours=24)))
        )
    )
    await db.commit()
    return max(0, int(getattr(result, "rowcount", 0) or 0))
