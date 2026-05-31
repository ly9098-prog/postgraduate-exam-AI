from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.user import TokenResponse, UserResponse, UserUpdate, WechatLogin
from app.services import user_service

router = APIRouter(prefix="/api/v1")


@router.post("/auth/login", response_model=TokenResponse)
async def login(data: WechatLogin, db: AsyncSession = Depends(get_db)):
    try:
        token, user = await user_service.wechat_login(db, data.code)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    return TokenResponse(
        access_token=token,
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
