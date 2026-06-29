"""向量配置 API 路由。

GET / PATCH /api/admin/v1/vector-config
POST        /api/admin/v1/vector-config/test-embedding
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import require_roles
from app.core.database import get_db
from app.schemas.admin_vector_config import (
    EmbeddingTestRequest,
    EmbeddingTestResponse,
    VectorConfigPatchRequest,
    VectorConfigResponse,
)
from app.services.vector_config_service import (
    get_vector_config,
    patch_vector_config,
    test_embedding_connection,
)

router = APIRouter(prefix="/api/admin/v1", tags=["admin-vector-config"])


@router.get("/vector-config", response_model=VectorConfigResponse)
async def read_vector_config(
    _=Depends(require_roles("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await get_vector_config(db)
    await db.commit()  # 持久化 seed 数据
    return result


@router.patch("/vector-config", response_model=VectorConfigResponse)
async def update_vector_config(
    data: VectorConfigPatchRequest,
    request: Request,
    current_admin=Depends(require_roles("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await patch_vector_config(db, data, current_admin, request)
        await db.commit()
        return result
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception:
        await db.rollback()
        raise


@router.post("/vector-config/test-embedding", response_model=EmbeddingTestResponse)
async def test_embedding(
    data: EmbeddingTestRequest,
    _=Depends(require_roles("super_admin")),
):
    """对给定 Embedding 配置发起一次最小连通性测试，不保存任何状态。"""
    return await test_embedding_connection(
        api_base_url=data.api_base_url,
        api_key=data.api_key,
        model=data.model,
        dim=data.dim,
        timeout=data.timeout,
    )
