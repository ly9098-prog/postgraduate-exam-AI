from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from app.core.database import get_db
from app.core.security import create_token, get_current_user
from app.models.user import User
from app.schemas.user import RefreshRequest, TokenResponse, UserResponse, UserUpdate, WechatLogin
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
