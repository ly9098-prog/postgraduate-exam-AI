from datetime import datetime

from fastapi import Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import AdminPrincipal
from app.models.practice_record import PracticeRecord
from app.models.user import User
from app.models.wrong_question import WrongQuestion
from app.schemas.admin_app_users import AdminAppUserBanRequest, AdminAppUserUpdateRequest
from app.services.admin_audit_service import write_admin_audit


async def list_app_users(
    db: AsyncSession,
    page: int,
    page_size: int,
    keyword: str | None = None,
    is_banned: bool | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> tuple[list[User], int]:
    conditions = []
    if keyword:
        pattern = f"%{keyword}%"
        conditions.append(or_(User.openid.ilike(pattern), User.nickname.ilike(pattern)))
    if is_banned is not None:
        conditions.append(User.is_banned.is_(is_banned))
    if created_from:
        conditions.append(User.created_at >= created_from)
    if created_to:
        conditions.append(User.created_at <= created_to)

    query = select(User)
    count_query = select(func.count()).select_from(User)
    for condition in conditions:
        query = query.where(condition)
        count_query = count_query.where(condition)

    total = await db.scalar(count_query)
    result = await db.execute(
        query.order_by(User.created_at.desc(), User.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result.scalars().all()), int(total or 0)


async def get_app_user_detail(db: AsyncSession, user_id: int) -> dict:
    user = await db.get(User, user_id)
    if not user:
        raise ValueError("用户不存在")

    practice_count = await db.scalar(select(func.count()).select_from(PracticeRecord).where(PracticeRecord.user_id == user_id))
    wrong_count = await db.scalar(select(func.count()).select_from(WrongQuestion).where(WrongQuestion.user_id == user_id))
    recent_active_at = await db.scalar(select(func.max(PracticeRecord.answered_at)).where(PracticeRecord.user_id == user_id))

    return {
        "id": user.id,
        "openid": user.openid,
        "nickname": user.nickname,
        "avatar_url": user.avatar_url,
        "is_banned": user.is_banned,
        "banned_reason": user.banned_reason,
        "banned_at": user.banned_at,
        "banned_by": user.banned_by,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
        "practice_count": int(practice_count or 0),
        "wrong_count": int(wrong_count or 0),
        "recent_active_at": recent_active_at,
    }


async def update_app_user(
    db: AsyncSession,
    user_id: int,
    data: AdminAppUserUpdateRequest,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> User:
    user = await db.get(User, user_id)
    if not user:
        raise ValueError("用户不存在")

    before = {"nickname": user.nickname}
    update_data = data.model_dump(exclude_unset=True)
    if "nickname" in update_data:
        user.nickname = update_data["nickname"]
    after = {"nickname": user.nickname}

    await write_admin_audit(
        db,
        operator,
        "app_user.update",
        "app_user",
        user.id,
        detail={"before": before, "after": after},
        request=request,
    )
    return user


async def ban_app_user(
    db: AsyncSession,
    user_id: int,
    data: AdminAppUserBanRequest,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> User:
    user = await db.get(User, user_id)
    if not user:
        raise ValueError("用户不存在")

    before = {
        "is_banned": user.is_banned,
        "banned_reason": user.banned_reason,
        "banned_at": user.banned_at.isoformat() if user.banned_at else None,
        "banned_by": user.banned_by,
    }
    user.is_banned = True
    user.banned_reason = data.reason
    user.banned_at = datetime.utcnow()
    user.banned_by = operator.id
    after = {
        "is_banned": user.is_banned,
        "banned_reason": user.banned_reason,
        "banned_at": user.banned_at.isoformat() if user.banned_at else None,
        "banned_by": user.banned_by,
    }

    await write_admin_audit(
        db,
        operator,
        "app_user.ban",
        "app_user",
        user.id,
        severity="critical",
        detail={"before": before, "after": after},
        request=request,
    )
    return user


async def unban_app_user(
    db: AsyncSession,
    user_id: int,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> User:
    user = await db.get(User, user_id)
    if not user:
        raise ValueError("用户不存在")

    before = {
        "is_banned": user.is_banned,
        "banned_reason": user.banned_reason,
        "banned_at": user.banned_at.isoformat() if user.banned_at else None,
        "banned_by": user.banned_by,
    }
    user.is_banned = False
    user.banned_reason = None
    user.banned_at = None
    user.banned_by = None
    after = {
        "is_banned": user.is_banned,
        "banned_reason": user.banned_reason,
        "banned_at": None,
        "banned_by": None,
    }

    await write_admin_audit(
        db,
        operator,
        "app_user.unban",
        "app_user",
        user.id,
        severity="critical",
        detail={"before": before, "after": after},
        request=request,
    )
    return user
