
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import (
    REFRESH_COOKIE_KEY,
    blacklist_admin_token,
    decode_admin_refresh_token,
    delete_refresh_cookie,
    get_current_admin,
    set_refresh_cookie,
)
from app.core.database import get_db
from app.core.time_utils import utcnow
from app.schemas.admin_auth import (
    AdminChangePasswordRequest,
    AdminLoginRequest,
    AdminMeResponse,
    AdminTokenResponse,
)
from app.services.admin_auth_service import (
    authenticate_admin,
    build_admin_login_response,
    change_admin_password,
    get_admin_me_response,
    refresh_admin_access_token,
)

router = APIRouter(prefix="/api/admin/v1/auth", tags=["admin-auth"])


@router.post("/login", response_model=AdminTokenResponse)
async def login(data: AdminLoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    try:
        admin_user = await authenticate_admin(db, data)
        token, refresh_token, user, role, permissions = await build_admin_login_response(db, admin_user)
        token_response = AdminTokenResponse(access_token=token, user=user, role=role, permissions=permissions)
        admin_user.last_login_at = utcnow()
        admin_user.last_login_ip = request.client.host if request.client else None
        await db.commit()
    except ValueError as exc:
        msg = str(exc)
        if "72字节" in msg:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=msg)

    set_refresh_cookie(response, refresh_token, request=request)
    return token_response


@router.post("/refresh", response_model=AdminTokenResponse)
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    refresh_token = request.cookies.get(REFRESH_COOKIE_KEY)
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    payload = decode_admin_refresh_token(refresh_token)
    try:
        token, user, role, permissions = await refresh_admin_access_token(db, int(payload["sub"]))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    # Re-set the refresh cookie on every refresh call so the cookie attributes
    # (Secure / SameSite / Max-Age) are always up-to-date with the current
    # deployment environment, even after a server restart or config change.
    set_refresh_cookie(response, refresh_token, request=request)
    return AdminTokenResponse(access_token=token, user=user, role=role, permissions=permissions)


@router.post("/logout")
async def logout(response: Response, current_admin=Depends(get_current_admin)):
    payload = current_admin.token_payload
    await blacklist_admin_token(payload["jti"], int(payload["exp"]))
    delete_refresh_cookie(response)
    return {"status": "ok"}


@router.get("/me", response_model=AdminMeResponse)
async def me(current_admin=Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    return await get_admin_me_response(db, current_admin.user)


@router.post("/change-password")
async def update_password(
    data: AdminChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    try:
        await change_admin_password(db, current_admin.user, data)
    except ValueError as exc:
        msg = str(exc)
        if "72字节" in msg:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=msg)
    return {"status": "ok"}
