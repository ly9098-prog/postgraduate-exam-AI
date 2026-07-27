"""向量检索 & Embedding 配置服务。

提供 DB-first 的配置读取，环境变量仅作为兜底。
参考 ``admin_ai_config_service.py`` 的 seed-on-read + TTL cache 模式。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import AdminPrincipal
from app.core.config import settings
from app.core.secret_crypto import (
    SecretDecryptionError,
    SecretEncryptionError,
    decrypt_secret,
    encrypt_secret,
)
from app.models.admin_vector_config import AdminVectorConfig
from app.schemas.admin_vector_config import (
    EmbeddingTestResponse,
    VectorConfigPatchRequest,
    VectorConfigResponse,
)
from app.services.admin_audit_service import write_admin_audit

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# TTL Cache — 避免每次向量操作都查 DB
# ---------------------------------------------------------------------------

_vector_config_cache: AdminVectorConfig | None = None
_vector_config_cache_time: float = 0
_VECTOR_CONFIG_CACHE_TTL = 30  # seconds


def _clear_cache() -> None:
    global _vector_config_cache, _vector_config_cache_time
    _vector_config_cache = None
    _vector_config_cache_time = 0


# ---------------------------------------------------------------------------
# Seed — 首次读取时从环境变量初始化 DB 记录
# ---------------------------------------------------------------------------


async def _seed_if_empty(db: AsyncSession) -> AdminVectorConfig:
    """DB 为空时从环境变量 seed 一条默认配置。"""
    result = await db.execute(select(AdminVectorConfig).limit(1))
    row = result.scalar_one_or_none()
    if row is not None:
        return row

    logger.info("admin_vector_configs 表为空，从环境变量 seed 默认配置")
    encrypted_key = None
    if settings.EMBEDDING_API_KEY:
        try:
            encrypted_key = encrypt_secret(settings.EMBEDDING_API_KEY)
        except SecretEncryptionError:
            logger.warning("AI_CONFIG_ENCRYPT_KEY not configured — skipping seed of embedding API key")
    row = AdminVectorConfig(
        vector_enabled=settings.VECTOR_ENABLED,
        vector_mode=settings.VECTOR_MODE,
        vector_allowlist=settings.VECTOR_ALLOWLIST,
        vector_cache_ttl_sec=settings.VECTOR_CACHE_TTL_SEC,
        vector_top_k=settings.VECTOR_TOP_K,
        vector_similarity_threshold=settings.VECTOR_SIMILARITY_THRESHOLD,
        embedding_provider=settings.EMBEDDING_PROVIDER,
        embedding_api_key_encrypted=encrypted_key,
        embedding_base_url=settings.EMBEDDING_BASE_URL,
        embedding_model=settings.EMBEDDING_MODEL,
        embedding_dim=settings.EMBEDDING_DIM,
        embedding_timeout=settings.EMBEDDING_TIMEOUT,
        embedding_batch_size=settings.EMBEDDING_BATCH_SIZE,
    )
    db.add(row)
    await db.flush()
    # flush 后属性过期，必须在 async 上下文中 refresh，
    # 否则后续 _to_response 访问属性时触发同步 lazy load → MissingGreenlet
    await db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def get_vector_config(db: AsyncSession) -> VectorConfigResponse:
    """读取向量配置（seed-on-read + TTL cache）。"""
    global _vector_config_cache, _vector_config_cache_time

    now = time.monotonic()
    if _vector_config_cache and (now - _vector_config_cache_time) < _VECTOR_CONFIG_CACHE_TTL:
        return _to_response(_vector_config_cache)

    row = await _seed_if_empty(db)
    _vector_config_cache = row
    _vector_config_cache_time = now
    return _to_response(row)


async def patch_vector_config(
    db: AsyncSession,
    data: VectorConfigPatchRequest,
    operator: AdminPrincipal,
    request: Any | None = None,
) -> VectorConfigResponse:
    """部分更新向量配置。"""
    row = await _seed_if_empty(db)
    update_data = data.model_dump(exclude_unset=True)

    # 记录实际变更字段（含 API key）
    changed_fields = list(update_data.keys())

    # API key 特殊处理：加密存储
    emb_key = data.get_embedding_api_key_value()
    if "embedding_api_key" in update_data:
        update_data.pop("embedding_api_key")
        # get_embedding_api_key_value returns:
        #   None  → not provided (keep existing)
        #   ""    → explicit clear
        #   other → new key to encrypt
        if emb_key is not None:
            row.embedding_api_key_encrypted = encrypt_secret(emb_key) if emb_key else None
        # If emb_key is None — keep existing, don't touch

    for field, value in update_data.items():
        if hasattr(row, field):
            setattr(row, field, value)

    row.updated_by = operator.id
    await db.flush()
    _clear_cache()

    await write_admin_audit(
        db, operator, "vector_config.update", "vector_config", str(row.id),
        severity="important",
        detail={"changed_fields": changed_fields},
        request=request,
    )

    # flush + audit 写入触发 autoflush，导致 row 属性过期；
    # 必须在 async 上下文中 refresh，否则 _to_response 访问属性时
    # 会触发同步 lazy load → MissingGreenlet (aiosqlite)
    await db.refresh(row)
    return _to_response(row)


# ---------------------------------------------------------------------------
# Runtime Resolver — 供 embedding_service / vector_retrieval_service 使用
# ---------------------------------------------------------------------------


@dataclass
class EmbeddingConfig:
    """解析后的 Embedding 运行时配置（明文 key）。"""

    api_key: str
    base_url: str
    model: str
    dim: int
    timeout: int
    batch_size: int
    provider: str


@dataclass
class VectorSearchConfig:
    """解析后的向量检索运行时配置。"""

    enabled: bool
    mode: str
    allowlist: str
    cache_ttl_sec: int
    top_k: int
    similarity_threshold: float


async def resolve_embedding_config(db: AsyncSession) -> EmbeddingConfig:
    """从 DB 读取 Embedding 配置，解密 API key。DB 无记录时 fallback 到环境变量。"""
    row = await _seed_if_empty(db)

    api_key = ""
    if row.embedding_api_key_encrypted:
        try:
            api_key = decrypt_secret(row.embedding_api_key_encrypted)
        except (SecretDecryptionError, SecretEncryptionError):
            api_key = ""

    # 如果 DB 中 key 为空但环境变量有值，fallback
    if not api_key and settings.EMBEDDING_API_KEY:
        api_key = settings.EMBEDDING_API_KEY

    return EmbeddingConfig(
        api_key=api_key,
        base_url=row.embedding_base_url or settings.EMBEDDING_BASE_URL,
        model=row.embedding_model or settings.EMBEDDING_MODEL,
        dim=row.embedding_dim or settings.EMBEDDING_DIM,
        timeout=row.embedding_timeout or settings.EMBEDDING_TIMEOUT,
        batch_size=row.embedding_batch_size or settings.EMBEDDING_BATCH_SIZE,
        provider=row.embedding_provider or settings.EMBEDDING_PROVIDER,
    )


async def resolve_vector_search_config(db: AsyncSession) -> VectorSearchConfig:
    """从 DB 读取向量检索配置。"""
    row = await _seed_if_empty(db)
    return VectorSearchConfig(
        enabled=row.vector_enabled,
        mode=row.vector_mode,
        allowlist=row.vector_allowlist,
        cache_ttl_sec=row.vector_cache_ttl_sec,
        top_k=row.vector_top_k,
        similarity_threshold=row.vector_similarity_threshold,
    )


def get_embedding_config_sync() -> EmbeddingConfig:
    """同步 fallback：当无 DB session 时直接读环境变量。

    仅用于无法获取 AsyncSession 的上下文（如纯函数调用）。
    """
    return EmbeddingConfig(
        api_key=settings.EMBEDDING_API_KEY,
        base_url=settings.EMBEDDING_BASE_URL,
        model=settings.EMBEDDING_MODEL,
        dim=settings.EMBEDDING_DIM,
        timeout=settings.EMBEDDING_TIMEOUT,
        batch_size=settings.EMBEDDING_BATCH_SIZE,
        provider=settings.EMBEDDING_PROVIDER,
    )


# ---------------------------------------------------------------------------
# Embedding API 连通性测试
# ---------------------------------------------------------------------------


async def test_embedding_connection(
    api_base_url: str,
    api_key: str | None,
    model: str,
    dim: int = 1024,
    timeout: int = 30,
) -> EmbeddingTestResponse:
    """对给定 Embedding 配置发起一次最小连通性测试。"""
    if not api_key:
        return EmbeddingTestResponse(
            success=False, status="auth_error",
            message="未配置 API Key，请先在上方输入并保存",
            latency_ms=0,
        )

    import time as _time

    url = f"{api_base_url.rstrip('/')}/v1/embeddings"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {"model": model, "input": "test"}

    start = _time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
    except httpx.TimeoutException:
        return EmbeddingTestResponse(
            success=False, status="timeout",
            message=f"请求超时 ({timeout}s)",
            latency_ms=int((_time.monotonic() - start) * 1000),
        )
    except httpx.ConnectError:
        return EmbeddingTestResponse(
            success=False, status="network_error",
            message="无法连接到 Embedding API 地址",
            latency_ms=int((_time.monotonic() - start) * 1000),
        )
    except Exception as exc:
        return EmbeddingTestResponse(
            success=False, status="network_error",
            message=str(exc)[:200],
            latency_ms=int((_time.monotonic() - start) * 1000),
        )

    latency_ms = int((_time.monotonic() - start) * 1000)

    if resp.status_code in (401, 403):
        return EmbeddingTestResponse(
            success=False, status="auth_error",
            message=f"认证失败 (HTTP {resp.status_code})",
            latency_ms=latency_ms,
        )

    if resp.status_code != 200:
        return EmbeddingTestResponse(
            success=False, status="network_error",
            message=f"HTTP {resp.status_code}: {resp.text[:200]}",
            latency_ms=latency_ms,
        )

    try:
        data = resp.json()
        embedding = data["data"][0]["embedding"]
        returned_dim = len(embedding)
    except (KeyError, IndexError, TypeError, ValueError):
        return EmbeddingTestResponse(
            success=False, status="format_error",
            message="API 返回格式异常",
            latency_ms=latency_ms,
        )

    if returned_dim != dim:
        return EmbeddingTestResponse(
            success=False, status="dimension_mismatch",
            message=f"期望维度 {dim}，实际返回 {returned_dim}",
            latency_ms=latency_ms,
            returned_dim=returned_dim,
        )

    return EmbeddingTestResponse(
        success=True, status="ok",
        message="连接成功，维度匹配",
        latency_ms=latency_ms,
        returned_dim=returned_dim,
    )


# ---------------------------------------------------------------------------
# Response Builder
# ---------------------------------------------------------------------------


def _to_response(row: AdminVectorConfig) -> VectorConfigResponse:
    """ORM 行 → 前端响应（API key 掩码处理，固定长度为 "********"）。"""
    key_configured = False
    key_masked = ""
    if row.embedding_api_key_encrypted:
        try:
            plain = decrypt_secret(row.embedding_api_key_encrypted)
            if plain:
                key_configured = True
                key_masked = "********"
        except (SecretDecryptionError, SecretEncryptionError):
            pass

    return VectorConfigResponse(
        vector_enabled=row.vector_enabled,
        vector_mode=row.vector_mode,
        vector_allowlist=row.vector_allowlist,
        vector_cache_ttl_sec=row.vector_cache_ttl_sec,
        vector_top_k=row.vector_top_k,
        vector_similarity_threshold=row.vector_similarity_threshold,
        embedding_provider=row.embedding_provider,
        embedding_api_key_configured=key_configured,
        embedding_api_key_masked=key_masked,
        embedding_base_url=row.embedding_base_url,
        embedding_model=row.embedding_model,
        embedding_dim=row.embedding_dim,
        embedding_timeout=row.embedding_timeout,
        embedding_batch_size=row.embedding_batch_size,
        updated_at=row.updated_at,
    )
