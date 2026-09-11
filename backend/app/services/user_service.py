import asyncio
import hashlib
import io
import uuid

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.log_context import get_trace_headers
from app.core.security import issue_user_token
from app.models.admin import AdminUser, Permission, Role, RolePermission
from app.models.app_user_admin_binding import AppUserAdminBinding
from app.models.user import User
from app.schemas.user import UserResponse
from app.services.storage_backend import (
    LEGACY_USER_AVATAR_PREFIX,
    get_legacy_user_avatar_storage,
    get_user_avatar_storage,
)

WX_URL = "https://api.weixin.qq.com/sns/jscode2session"
LOCAL_APP_ENVS = {"development", "local", "test"}
AVATAR_SIZE = 512
AVATAR_JPEG_QUALITY = 88


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
        settings.WECHAT_APP_ID and settings.WECHAT_APP_ID != "your-app-id-here"
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
                    headers=get_trace_headers(),
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
    if settings.APP_ENV.lower() in {
        "development",
        "local",
        "test",
    } and user.openid.startswith("dev_"):
        return UserResponse(
            id=user.id,
            nickname=user.nickname,
            avatar_url=user.avatar_url,
            profile_completed=bool(user.nickname and user.nickname.strip()),
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
        profile_completed=bool(user.nickname and user.nickname.strip()),
        is_admin=is_admin,
        role=role_name,
        role_name=role_name,
        permissions=permissions,
    )


async def update_user(
    db: AsyncSession, user_id: int, nickname: str | None
) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return None
    if nickname is not None:
        user.nickname = " ".join(nickname.strip().split())
    await db.commit()
    await db.refresh(user)
    return user


def _normalize_avatar_bytes(data: bytes) -> bytes:
    """Decode and normalize a user supplied avatar into a bounded JPEG."""
    try:
        with Image.open(io.BytesIO(data)) as source:
            source.load()
            image = ImageOps.exif_transpose(source)
            if image.width <= 0 or image.height <= 0:
                raise ValueError("头像图片尺寸无效")
            # chooseAvatar normally returns a square crop.  ImageOps.fit also
            # gives us a stable square result for camera/gallery edge cases.
            image = ImageOps.fit(
                image.convert("RGB"),
                (AVATAR_SIZE, AVATAR_SIZE),
                method=Image.Resampling.LANCZOS,
            )
            output = io.BytesIO()
            image.save(
                output,
                format="JPEG",
                quality=AVATAR_JPEG_QUALITY,
                optimize=True,
            )
            return output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("头像文件不是有效图片") from exc


async def replace_user_avatar(db: AsyncSession, user: User, data: bytes) -> User:
    """Persist a normalized avatar and replace the user's previous avatar."""
    normalized = await asyncio.to_thread(_normalize_avatar_bytes, data)
    storage = get_user_avatar_storage()
    key = f"{user.id}/{uuid.uuid4().hex}.jpg"
    try:
        new_url = await storage.upload(key, normalized)
    except Exception as exc:
        raise RuntimeError("avatar storage upload failed") from exc
    previous_url = user.avatar_url

    user.avatar_url = new_url
    try:
        await db.commit()
        await db.refresh(user)
    except Exception:
        await db.rollback()
        try:
            await storage.delete(new_url)
        except Exception:
            pass
        raise

    # The new avatar is already durable at this point.  Deletion is best-effort
    # so a transient storage error never rolls the user's profile back.
    if previous_url and previous_url != new_url:
        await delete_user_avatar_file(previous_url, storage=storage)

    return user


async def delete_user_avatar_file(avatar_url: str | None, *, storage=None) -> None:
    """Best-effort removal of a persisted profile avatar.

    Avatars created before the dedicated namespace fix live below
    ``/static/formulas/avatars``.  Detect those URLs and use a legacy-scoped
    backend so replacing an old avatar also removes the old object instead of
    leaving it orphaned.
    """
    if not avatar_url:
        return
    normalized_url = str(avatar_url).replace("\\", "/")
    legacy_marker = f"/{LEGACY_USER_AVATAR_PREFIX.strip('/')}/"
    if legacy_marker in normalized_url or normalized_url.startswith(
        LEGACY_USER_AVATAR_PREFIX + "/"
    ):
        backend = get_legacy_user_avatar_storage()
    else:
        backend = storage or get_user_avatar_storage()
    try:
        await backend.delete(avatar_url)
    except Exception:
        # Profile/account updates must not fail only because old media cleanup
        # encountered a transient storage error.
        pass
