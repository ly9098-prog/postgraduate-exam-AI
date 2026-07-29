import hashlib

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import issue_user_token
from app.models.admin import AdminUser, Permission, Role, RolePermission
from app.models.app_user_admin_binding import AppUserAdminBinding
from app.models.user import User
from app.schemas.user import UserResponse

WX_URL = "https://api.weixin.qq.com/sns/jscode2session"
LOCAL_APP_ENVS = {"development", "local", "test"}


def _dev_openid(code: str) -> str:
    """开发环境：从 code 生成确定性 openid，绕过微信 jscode2session"""
    return "dev_" + hashlib.md5(code.encode()).hexdigest()[:16]


async def wechat_login(db: AsyncSession, code: str) -> tuple[str, int, User]:
    """Returns (token, expires_at, user) tuple."""
    code = code.strip()
    if not code:
        raise ValueError("微信登录凭证不能为空")

    openid: str | None = None

    has_app_id = bool(
        settings.WECHAT_APP_ID
        and settings.WECHAT_APP_ID != "your-app-id-here"
    )
    has_app_secret = bool(
        settings.WECHAT_APP_SECRET
        and settings.WECHAT_APP_SECRET != "your-app-secret-here"
    )

    if has_app_id and has_app_secret:
        # 生产环境：调用微信 jscode2session
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    WX_URL,
                    params={
                        "appid": settings.WECHAT_APP_ID,
                        "secret": settings.WECHAT_APP_SECRET,
                        "js_code": code,
                        "grant_type": "authorization_code",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ValueError("微信登录服务暂时不可用") from exc

        if "openid" not in data:
            raise ValueError("微信登录凭证无效")
        openid = str(data["openid"])
        # The WeChat session_key is not needed after jscode2session succeeds.
        # Do not persist it: it is a short-lived sensitive credential.
    elif settings.APP_ENV.lower() in LOCAL_APP_ENVS:
        # 开发环境：从 code 派生 openid
        openid = _dev_openid(code)
    else:
        # 生产环境禁止回退到可预测的开发身份。
        raise ValueError("微信登录服务未配置")

    # 查找或创建用户
    result = await db.execute(select(User).where(User.openid == openid))
    user = result.scalar_one_or_none()

    if user:
        if user.deleted_at is not None:
            raise ValueError("账号已注销")
        if user.is_banned:
            raise ValueError("账号已封禁")
    else:
        user = User(openid=openid)
        db.add(user)

    await db.commit()
    await db.refresh(user)

    token, expires_at = await issue_user_token(user.id)
    return token, expires_at, user


async def get_user_response(db: AsyncSession, user: User) -> UserResponse:
    """Build app user payload with miniprogram permission metadata.

    AppUser identity remains WeChat-openid based.  A miniprogram user receives
    admin-like metadata only through an explicit app_user_admin_bindings row.
    """
    if settings.APP_ENV.lower() in {"development", "local", "test"} and user.openid.startswith("dev_"):
        return UserResponse(
            id=user.id,
            nickname=user.nickname,
            avatar_url=user.avatar_url,
            is_admin=True,
            role="super_admin",
            role_name="super_admin",
            permissions=["*"],
        )

    role_name = "user"
    permissions: list[str] = []

    admin_result = await db.execute(
        select(AdminUser, Role)
        .join(AppUserAdminBinding, AppUserAdminBinding.admin_user_id == AdminUser.id)
        .join(Role, Role.id == AdminUser.role_id)
        .where(AppUserAdminBinding.user_id == user.id)
        .where(AdminUser.is_active.is_(True))
        .order_by(AppUserAdminBinding.id.desc())
    )
    admin_row = admin_result.first()
    if admin_row:
        _, role = admin_row
        role_name = role.name
        permission_result = await db.execute(
            select(Permission.name)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role.id)
            .order_by(Permission.name.asc())
        )
        permissions = list(permission_result.scalars().all())

    is_admin = role_name in {"admin", "super_admin"} or "import:write" in permissions
    return UserResponse(
        id=user.id,
        nickname=user.nickname,
        avatar_url=user.avatar_url,
        is_admin=is_admin,
        role=role_name,
        role_name=role_name,
        permissions=permissions,
    )



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
