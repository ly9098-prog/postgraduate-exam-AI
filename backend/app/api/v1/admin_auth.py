from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import blacklist_admin_token, get_current_admin
from app.core.database import get_db
from app.schemas.admin_auth import AdminChangePasswordRequest, AdminLoginRequest, AdminTokenResponse
from app.services.admin_auth_service import authenticate_admin, build_admin_login_response, change_admin_password

router = APIRouter(prefix="/api/admin/v1/auth", tags=["admin-auth"])


@router.post("/login", response_model=AdminTokenResponse)
async def login(data: AdminLoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        admin_user = await authenticate_admin(db, data)
        token, user, role = await build_admin_login_response(db, admin_user)
        response = AdminTokenResponse(access_token=token, user=user, role=role)
        admin_user.last_login_at = datetime.utcnow()
        admin_user.last_login_ip = request.client.host if request.client else None
        await db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    return response


@router.post("/logout")
async def logout(current_admin=Depends(get_current_admin)):
    payload = current_admin.token_payload
    await blacklist_admin_token(payload["jti"], int(payload["exp"]))
    return {"status": "ok"}


@router.get("/me")
async def me(current_admin=Depends(get_current_admin)):
    return {
        "id": current_admin.user.id,
        "username": current_admin.user.username,
        "roleId": current_admin.user.role_id,
        "isActive": current_admin.user.is_active,
    }


@router.post("/change-password")
async def update_password(
    data: AdminChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    try:
        await change_admin_password(db, current_admin.user, data)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    return {"status": "ok"}
