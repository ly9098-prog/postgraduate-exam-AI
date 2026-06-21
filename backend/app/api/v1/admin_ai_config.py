from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import require_roles
from app.core.database import get_db
from app.schemas.admin_ai_config import AdminAiModelConfigCreateRequest, AdminAiModelConfigPatchRequest, AdminAiModelConfigResponse, AdminAiConfigsPatchRequest, AdminAiConfigsResponse, ModelTestConnectionRequest, ModelTestConnectionResponse
from app.services.admin_ai_config_service import create_model, delete_model, get_all_configs, list_models, patch_configs, patch_model, test_model_connection

router = APIRouter(prefix="/api/admin/v1", tags=["admin-ai-config"])


# ========== Model config ==========


@router.get("/ai-models", response_model=list[AdminAiModelConfigResponse])
async def read_models(
    _=Depends(require_roles("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await list_models(db)
    await db.commit()  # 持久化 seed 数据，确保后续请求可见
    return result


@router.patch("/ai-models/{model_id}", response_model=AdminAiModelConfigResponse)
async def update_model(
    model_id: int,
    data: AdminAiModelConfigPatchRequest,
    request: Request,
    current_admin=Depends(require_roles("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await patch_model(db, model_id, data, current_admin)
        await db.commit()
        return result
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/ai-models", response_model=AdminAiModelConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_model_endpoint(
    data: AdminAiModelConfigCreateRequest,
    request: Request,
    current_admin=Depends(require_roles("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await create_model(db, data, current_admin)
    await db.commit()
    return result


@router.delete("/ai-models/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model_endpoint(
    model_id: int,
    request: Request,
    current_admin=Depends(require_roles("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        await delete_model(db, model_id, current_admin)
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        msg = str(exc)
        code = status.HTTP_404_NOT_FOUND if "不存在" in msg else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=msg)


@router.post("/ai-models/test-connection", response_model=ModelTestConnectionResponse)
async def test_connection(
    data: ModelTestConnectionRequest,
    _=Depends(require_roles("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """对给定模型配置发起一次最小连通性测试，不保存任何状态。"""
    result = await test_model_connection(
        api_base_url=data.api_base_url,
        api_key=data.api_key,
        model_name=data.model_name,
        model_id=data.model_id,
        db=db,
        provider=data.provider,
        feature=data.feature,
        features=data.features,
    )
    return result


# ========== Config key-value ==========


@router.get("/ai-configs", response_model=AdminAiConfigsResponse)
async def read_configs(
    _=Depends(require_roles("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    configs = await get_all_configs(db)
    return AdminAiConfigsResponse(configs=configs)


@router.patch("/ai-configs", response_model=AdminAiConfigsResponse)
async def update_configs(
    data: AdminAiConfigsPatchRequest,
    request: Request,
    current_admin=Depends(require_roles("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    configs = await patch_configs(db, data.configs, current_admin)
    await db.commit()
    return AdminAiConfigsResponse(configs=configs)
