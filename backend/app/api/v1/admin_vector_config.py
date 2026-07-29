"""向量配置 API 路由。

GET / PATCH /api/admin/v1/vector-config
POST        /api/admin/v1/vector-config/test-embedding
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import require_roles
from app.core.database import get_db
from app.core.secret_crypto import SecretDecryptionError, SecretEncryptionError
from app.schemas.admin_vector_config import (
    EmbeddingTestRequest,
    EmbeddingTestResponse,
    VectorConfigPatchRequest,
    VectorConfigResponse,
)
from app.services.vector_config_service import (
    get_vector_config,
    patch_vector_config,
    resolve_embedding_config,
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
    except SecretEncryptionError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="加密配置不可用，无法保存 API Key。请联系管理员检查 AI_CONFIG_ENCRYPT_KEY 配置。",
        )
    except SecretDecryptionError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="数据库中的凭据无法解密，请检查加密配置或重新保存凭据。",
        )
    except Exception:
        await db.rollback()
        raise


@router.post("/vector-config/test-embedding", response_model=EmbeddingTestResponse)
async def test_embedding(
    data: EmbeddingTestRequest,
    _=Depends(require_roles("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    """对给定 Embedding 配置发起一次最小连通性测试，不保存任何状态。"""
    api_key = data.get_api_key_value()
    api_base_url = data.api_base_url
    model = data.model
    dim = data.dim
    timeout = data.timeout
    # 前端未传 key 时（用户刷新页面后未重新输入），从 DB 读取已存储的 key
    if not api_key:
        stored = await resolve_embedding_config(db)
        api_key = stored.api_key
        api_base_url = stored.base_url
        model = stored.model
        dim = stored.dim
        timeout = stored.timeout
    return await test_embedding_connection(
        api_base_url=api_base_url,
        api_key=api_key,
        model=model,
        dim=dim,
        timeout=timeout,
    )
