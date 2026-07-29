import hashlib
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import CacheUnavailableError, cache
from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user, issue_user_token, set_user_nbf
from app.models.user import User
from app.schemas.user import (
    DeletionResponse,
    RefreshRequest,
    TokenResponse,
    UserResponse,
    UserUpdate,
    WechatLogin,
)
from app.services import token_service, user_service

router = APIRouter(prefix="/api/v1")


def _user_login_rate_key(request: Request) -> str:
    client_ip = request.client.host if request.client else "unknown"
    digest = hashlib.sha256(client_ip.encode("utf-8")).hexdigest()
    return f"user:login:fail:{digest}"


@router.post("/auth/login", response_model=TokenResponse)
async def login(data: WechatLogin, request: Request, db: AsyncSession = Depends(get_db)):
    rate_key = _user_login_rate_key(request)
    try:
        failures = int(await cache.get_strict(rate_key) or 0)
    except CacheUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service temporarily unavailable",
        ) from exc
    if failures >= settings.USER_LOGIN_MAX_FAILURES:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="登录尝试过于频繁，请稍后重试",
            headers={"Retry-After": str(settings.USER_LOGIN_WINDOW_SEC)},
        )

    try:
        token, expires_at, user = await user_service.wechat_login(db, data.code)
    except ValueError as e:
        try:
            await cache.increment_strict(rate_key, ttl=settings.USER_LOGIN_WINDOW_SEC)
        except CacheUnavailableError as cache_exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication service temporarily unavailable",
            ) from cache_exc
        raise HTTPException(status_code=401, detail=str(e))

    try:
        await cache.delete_strict(rate_key)
    except CacheUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service temporarily unavailable",
        ) from exc

    refresh_token = await token_service.create_refresh_token(db, user.id)

    return TokenResponse(
        access_token=token,
        expires_at=expires_at,
        refresh_token=refresh_token,
        user=await user_service.get_user_response(db, user),
    )


@router.post("/auth/refresh", response_model=TokenResponse)
async def refresh(data: RefreshRequest, db: AsyncSession = Depends(get_db)):
    token_record = await token_service.verify_refresh_token(db, data.refresh_token)
    if not token_record:
        raise HTTPException(status_code=401, detail="刷新令牌无效或已过期")

    # Validate account state before consuming/rotating the token.
    result = await db.execute(select(User).where(User.id == token_record.user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    if user.deleted_at is not None:
        await token_service.revoke_all_user_tokens(db, user.id)
        raise HTTPException(status_code=401, detail="账号已注销")
    if user.is_banned:
        await token_service.revoke_all_user_tokens(db, user.id)
        raise HTTPException(status_code=403, detail="账号已封禁")

    # Rotate atomically: every refresh token can be consumed only once.
    try:
        new_refresh_token = await token_service.rotate_refresh_token(db, token_record)
    except ValueError:
        raise HTTPException(status_code=401, detail="刷新令牌无效或已使用")

    new_jwt, new_expires_at = await issue_user_token(user.id)

    return TokenResponse(
        access_token=new_jwt,
        expires_at=new_expires_at,
        refresh_token=new_refresh_token,
        user=await user_service.get_user_response(db, user),
    )


@router.get("/users/me", response_model=UserResponse)
async def get_me(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await user_service.get_user_response(db, current_user)


@router.put("/users/me", response_model=UserResponse)
async def update_me(
    data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = await user_service.update_user(
        db, current_user.id, data.nickname, data.avatar_url
    )
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return await user_service.get_user_response(db, user)


@router.post("/auth/logout", status_code=200)
async def logout(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Logout current device: revoke all active refresh tokens for the user.

    The frontend should also clear local auth state after this call.
    """
    await token_service.revoke_all_user_tokens(db, current_user.id)
    await set_user_nbf(current_user.id)
    return {"message": "已退出登录"}


@router.post("/users/me/deletion-request", response_model=DeletionResponse)
async def request_deletion(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Request account deletion: soft-deletes the user account.

    Effects:
    - Marks the user as deleted (deleted_at set)
    - Revokes all active refresh tokens
    - The account can no longer be used to authenticate
    - User data (practice records, wrong questions, etc.) remains
      in the database for a grace period, then is cleaned up by
      a background job.

    Note: This action is irreversible. The user must re-register
    (get a new account) to use the service again.
    """
    if current_user.deleted_at:
        raise HTTPException(status_code=400, detail="账号已注销")

    now = datetime.now(UTC)
    current_user.deleted_at = now
    await db.commit()

    # Revoke all tokens so ongoing sessions are immediately invalidated
    await token_service.revoke_all_user_tokens(db, current_user.id)
    await set_user_nbf(current_user.id)

    return DeletionResponse(
        message="账号注销申请已提交，相关数据将按隐私政策处理",
        deleted_at=int(now.timestamp()),
    )
