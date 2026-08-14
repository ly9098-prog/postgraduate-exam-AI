"""向量配置 API。

模型与凭据统一维护在 ``/ai-models``；本路由只保存向量检索参数及当前选择的
Embedding 模型 ID。
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import require_roles
from app.core.database import get_db
from app.models.admin_ai_config import AdminAiConfig
from app.schemas.admin_vector_config import (
    EmbeddingTestRequest,
    EmbeddingTestResponse,
    VectorConfigPatchRequest,
    VectorConfigResponse,
    _configs_to_response,
)
from app.services.vector_config_service import (
    resolve_embedding_config,
    resolve_embedding_model,
    test_embedding_connection,
)

router = APIRouter(prefix="/api/admin/v1", tags=["admin-vector-config"])

VECTOR_KEYS = frozenset({
    "vector_enabled",
    "vector_cache_ttl_sec",
    "vector_top_k",
    "vector_similarity_threshold",
    "embedding_model_config_id",
    "embedding_dim",
    "embedding_timeout",
    "embedding_batch_size",
})


async def _read_vector_rows(db: AsyncSession) -> dict[str, str]:
    result = await db.execute(select(AdminAiConfig).where(AdminAiConfig.config_key.in_(VECTOR_KEYS)))
    return {r.config_key: r.config_value for r in result.scalars().all()}


@router.get("/vector-config", response_model=VectorConfigResponse)
async def read_vector_config(
    _=Depends(require_roles("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    configs = await _read_vector_rows(db)
    response = _configs_to_response(configs)

    # 首次升级时如果还没保存 model id，但模型注册中心已有 embedding 模型，
    # 直接在响应中给出自动解析结果；保存后会固化成显式选择。
    if response.embedding_model_config_id is None:
        model = await resolve_embedding_model(db, configs=configs)
        if model is not None:
            response.embedding_model_config_id = model.id
    return response


@router.patch("/vector-config", response_model=VectorConfigResponse)
async def update_vector_config(
    data: VectorConfigPatchRequest,
    request: Request,
    current_admin=Depends(require_roles("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    payload = data.model_dump(exclude_unset=True)

    if "embedding_model_config_id" in data.model_fields_set and data.embedding_model_config_id is not None:
        # 显式验证：只能选择启用且声明 embedding capability 的模型。
        await resolve_embedding_model(db, requested_model_config_id=data.embedding_model_config_id)

    changed: list[str] = []
    for key, value in payload.items():
        if key not in VECTOR_KEYS:
            continue
        if value is None:
            str_value = ""
        elif isinstance(value, bool):
            str_value = str(value).lower()
        else:
            str_value = str(value)
        row = AdminAiConfig(config_key=key, config_value=str_value)
        await db.merge(row)
        changed.append(key)

    await db.flush()
    from app.services.admin_audit_service import write_admin_audit
    await write_admin_audit(
        db,
        current_admin,
        "vector_config.update",
        resource_type="vector_config",
        resource_id="config",
        severity="important",
        detail={"changed_fields": changed},
    )
    await db.commit()

    # 配置变更后清理 vector service 的短 TTL 缓存。
    try:
        from app.services.vector_retrieval_service import _reset_vector_enabled_cache
        _reset_vector_enabled_cache()
    except Exception:
        pass

    configs = await _read_vector_rows(db)
    return _configs_to_response(configs)


@router.post("/vector-config/test-embedding", response_model=EmbeddingTestResponse)
async def test_embedding(
    data: EmbeddingTestRequest,
    _=Depends(require_roles("super_admin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        config = await resolve_embedding_config(
            db,
            requested_model_config_id=data.model_config_id,
            dim=data.dim,
            timeout=data.timeout,
        )
    except ValueError as exc:
        return EmbeddingTestResponse(
            success=False,
            status="config_error",
            message=str(exc),
            latency_ms=0,
        )

    if config.model_config_id is None:
        return EmbeddingTestResponse(
            success=False,
            status="config_error",
            message="尚未注册可用的 Embedding 模型，请先在“模型配置”中添加并启用 Embedding 模型",
            latency_ms=0,
        )

    return await test_embedding_connection(
        api_base_url=config.base_url,
        api_key=config.api_key,
        model=config.model,
        dim=config.dim,
        timeout=config.timeout,
    )
