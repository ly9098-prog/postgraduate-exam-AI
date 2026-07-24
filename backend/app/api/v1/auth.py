from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import create_token, get_current_user
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


@router.post("/auth/login", response_model=TokenResponse)
async def login(data: WechatLogin, db: AsyncSession = Depends(get_db)):
    try:
        token, expires_at, user = await user_service.wechat_login(db, data.code)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

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

    # Rotate: issue new, revoke old
    new_refresh_token = await token_service.rotate_refresh_token(db, token_record)

    # Issue new JWT
    result = await db.execute(select(User).where(User.id == token_record.user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")

    new_jwt, new_expires_at = create_token(user.id)

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

    return DeletionResponse(
        message="账号注销申请已提交，相关数据将按隐私政策处理",
        deleted_at=int(now.timestamp()),
    )
