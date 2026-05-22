import hashlib

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_token
from app.models.user import User

WX_URL = "https://api.weixin.qq.com/sns/jscode2session"


def _dev_openid(code: str) -> str:
    """开发环境：从 code 生成确定性 openid，绕过微信 jscode2session"""
    return "dev_" + hashlib.md5(code.encode()).hexdigest()[:16]


async def wechat_login(db: AsyncSession, code: str) -> tuple[str, User]:
    openid: str | None = None
    session_key: str | None = None

    if settings.WECHAT_APP_ID and settings.WECHAT_APP_ID != "your-app-id-here":
        # 生产环境：调用微信 jscode2session
        async with httpx.AsyncClient() as client:
            resp = await client.get(WX_URL, params={
                "appid": settings.WECHAT_APP_ID,
                "secret": settings.WECHAT_APP_SECRET,
                "js_code": code,
                "grant_type": "authorization_code",
            })
            data = resp.json()
            if "openid" not in data:
                raise ValueError(f"微信登录失败: {data.get('errmsg', '未知错误')}")
            openid = data["openid"]
            session_key = data.get("session_key")
    else:
        # 开发环境：从 code 派生 openid
        openid = _dev_openid(code)
        session_key = "dev_mode"

    # 查找或创建用户
    result = await db.execute(select(User).where(User.openid == openid))
    user = result.scalar_one_or_none()

    if user:
        user.session_key = session_key
    else:
        user = User(openid=openid, session_key=session_key)
        db.add(user)

    await db.commit()
    await db.refresh(user)

    token = create_token(user.id)
    return token, user


async def update_user(
    db: AsyncSession, user_id: int, nickname: str | None, avatar_url: str | None
) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return None
    if nickname is not None:
        user.nickname = nickname
    if avatar_url is not None:
        user.avatar_url = avatar_url
    await db.commit()
    await db.refresh(user)
    return user
