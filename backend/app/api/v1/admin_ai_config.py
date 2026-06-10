from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import require_permissions
from app.core.database import get_db
from app.schemas.admin_ai_config import AdminAiModelConfigPatchRequest, AdminAiModelConfigResponse, AdminAiConfigsPatchRequest, AdminAiConfigsResponse
from app.services.admin_ai_config_service import get_all_configs, list_models, patch_configs, patch_model

router = APIRouter(prefix="/api/admin/v1", tags=["admin-ai-config"])


# ========== Model config ==========


@router.get("/ai-models", response_model=list[AdminAiModelConfigResponse])
async def read_models(
    _=Depends(require_permissions("ai_setting:read")),
    db: AsyncSession = Depends(get_db),
):
    return await list_models(db)


@router.patch("/ai-models/{model_id}", response_model=AdminAiModelConfigResponse)
async def update_model(
    model_id: int,
    data: AdminAiModelConfigPatchRequest,
    request: Request,
    current_admin=Depends(require_permissions("ai_setting:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await patch_model(db, model_id, data, current_admin)
        await db.commit()
        return result
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ========== Config key-value ==========


@router.get("/ai-configs", response_model=AdminAiConfigsResponse)
async def read_configs(
    _=Depends(require_permissions("ai_setting:read")),
    db: AsyncSession = Depends(get_db),
):
    configs = await get_all_configs(db)
    return AdminAiConfigsResponse(configs=configs)


@router.patch("/ai-configs", response_model=AdminAiConfigsResponse)
async def update_configs(
    data: AdminAiConfigsPatchRequest,
    request: Request,
    current_admin=Depends(require_permissions("ai_setting:write")),
    db: AsyncSession = Depends(get_db),
):
    configs = await patch_configs(db, data.configs, current_admin)
    await db.commit()
    return AdminAiConfigsResponse(configs=configs)
