"""向量配置 API 路由 — 数据存储在 admin_ai_configs 表中。

GET / PATCH /api/admin/v1/vector-config
POST        /api/admin/v1/vector-config/test-embedding
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import require_roles
from app.core.database import get_db
from app.models.admin_ai_config import AdminAiConfig
from app.schemas.admin_vector_config import (
    EmbeddingTestRequest,
    EmbeddingTestResponse,
    VectorConfigResponse,
    _configs_to_response,
)
from app.services.vector_config_service import (
    resolve_embedding_config,
    test_embedding_connection,
)

router = APIRouter(prefix="/api/admin/v1", tags=["admin-vector-config"])

VECTOR_KEYS = frozenset({
    "vector_enabled",
    "vector_cache_ttl_sec", "vector_top_k", "vector_similarity_threshold",
    "embedding_api_key_encrypted", "embedding_provider", "embedding_base_url",
    "embedding_model",
    "embedding_dim", "embedding_timeout", "embedding_batch_size",
})


@router.get("/vector-config", response_model=VectorConfigResponse)
async def read_vector_config(
    _=Depends(require_roles("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AdminAiConfig).where(AdminAiConfig.config_key.in_(VECTOR_KEYS)))
    configs = {r.config_key: r.config_value for r in result.scalars().all()}
    return _configs_to_response(configs)


@router.patch("/vector-config", response_model=VectorConfigResponse)
async def update_vector_config(
    data: dict,
    request: Request,
    current_admin=Depends(require_roles("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    from app.core.secret_crypto import encrypt_secret
    from app.models.admin_ai_config import AdminAiConfig

    changed = []
    for key, value in data.items():
        if key == "embedding_api_key":
            encrypted_val = encrypt_secret(value) if value else ""
            row = AdminAiConfig(config_key="embedding_api_key_encrypted", config_value=encrypted_val)
            await db.merge(row)
            changed.append("embedding_api_key_encrypted")
            continue
        if key not in VECTOR_KEYS:
            continue
        str_value = str(value).lower() if isinstance(value, bool) else str(value)
        row = AdminAiConfig(config_key=key, config_value=str_value)
        await db.merge(row)
        changed.append(key)
    await db.flush()
    from app.services.admin_audit_service import write_admin_audit
    await write_admin_audit(
        db, current_admin, "vector_config.update",
        resource_type="vector_config", resource_id="config",
        severity="important", detail={"changed_fields": changed},
    )

    await db.commit()

    # Read back
    result = await db.execute(select(AdminAiConfig).where(AdminAiConfig.config_key.in_(VECTOR_KEYS)))
    configs = {r.config_key: r.config_value for r in result.scalars().all()}
    return _configs_to_response(configs)


@router.post("/vector-config/test-embedding", response_model=EmbeddingTestResponse)
async def test_embedding(
    data: EmbeddingTestRequest,
    _=Depends(require_roles("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    api_key = data.get_api_key_value()
    api_base_url = data.api_base_url
    model = data.model
    dim = data.dim
    timeout = data.timeout
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
