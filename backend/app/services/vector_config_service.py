"""Embedding + vector config helpers — data stored in admin_ai_configs keys."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.admin_ai_config import AdminAiConfig


class EmbeddingConfig:
    """解析后的 Embedding 运行时配置（明文 key）。"""

    api_key: str = ""
    base_url: str = ""
    model: str = ""
    dim: int = 0
    timeout: int = 0
    batch_size: int = 0
    provider: str = ""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


@dataclass
class VectorSearchConfig:
    """向量检索运行时配置。"""

    enabled: bool = False
    cache_ttl_sec: int = 300
    top_k: int = 100
    similarity_threshold: float = 0.15


async def _read_cfg(db: AsyncSession) -> dict[str, str]:
    result = await db.execute(select(AdminAiConfig))
    return {r.config_key: r.config_value for r in result.scalars().all()}


async def resolve_embedding_config(db: AsyncSession) -> EmbeddingConfig:
    """从 DB (admin_ai_configs) 读取 Embedding 配置，解密 API key。"""
    cfg = await _read_cfg(db)
    from app.core.secret_crypto import SecretDecryptionError, SecretEncryptionError, decrypt_secret

    api_key = ""
    encrypted = cfg.get("embedding_api_key_encrypted", "")
    if encrypted:
        try:
            api_key = decrypt_secret(encrypted)
        except (SecretDecryptionError, SecretEncryptionError):
            api_key = ""

    return EmbeddingConfig(
        api_key=api_key,
        base_url=cfg.get("embedding_base_url") or settings.EMBEDDING_BASE_URL,
        model=cfg.get("embedding_model") or settings.EMBEDDING_MODEL,
        dim=int(cfg.get("embedding_dim", settings.EMBEDDING_DIM)),
        timeout=int(cfg.get("embedding_timeout", settings.EMBEDDING_TIMEOUT)),
        batch_size=int(cfg.get("embedding_batch_size", settings.EMBEDDING_BATCH_SIZE)),
        provider=cfg.get("embedding_provider") or settings.EMBEDDING_PROVIDER,
    )


def get_embedding_config_sync() -> EmbeddingConfig:
    return EmbeddingConfig(
        api_key="",
        base_url=settings.EMBEDDING_BASE_URL,
        model=settings.EMBEDDING_MODEL,
        dim=settings.EMBEDDING_DIM,
        timeout=settings.EMBEDDING_TIMEOUT,
        batch_size=settings.EMBEDDING_BATCH_SIZE,
        provider=settings.EMBEDDING_PROVIDER,
    )


async def test_embedding_connection(
    api_base_url: str,
    api_key: str | None,
    model: str,
    dim: int = 1024,
    timeout: int = 30,
) -> "EmbeddingTestResponse":
    """对给定 Embedding 配置发起一次最小连通性测试。"""
    from app.schemas.admin_vector_config import EmbeddingTestResponse
    if not api_key:
        return EmbeddingTestResponse(
            success=False, status="auth_error",
            message="未配置 API Key，请先在上方输入并保存",
            latency_ms=0,
        )

    import asyncio, json, time as _time

    try:
        from app.services.safe_remote_fetch import validate_remote_url as _validated_embedding_base_url
        api_base_url = _validated_embedding_base_url(api_base_url)
    except ValueError as exc:
        return EmbeddingTestResponse(
            success=False, status="network_error",
            message=str(exc), latency_ms=0,
        )

    url = f"{api_base_url}/v1/embeddings"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "input": "test"}
    start = _time.monotonic()

    try:
        from app.services.safe_remote_fetch import request_remote_bytes
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        remote = await asyncio.to_thread(
            request_remote_bytes, url,
            method="POST", body=body,
            max_bytes=64 * 1024 * 1024,
            timeout=float(timeout),
            allow_http=settings.AI_ALLOW_HTTP_BASE_URLS,
            follow_redirects=False, headers=headers,
        )
    except Exception as exc:
        return EmbeddingTestResponse(
            success=False, status="network_error",
            message=str(exc)[:200],
            latency_ms=int((_time.monotonic() - start) * 1000),
        )

    latency_ms = int((_time.monotonic() - start) * 1000)
    response_text = remote.data.decode("utf-8", errors="replace")
    if remote.status in (401, 403):
        return EmbeddingTestResponse(
            success=False, status="auth_error",
            message=f"认证失败 (HTTP {remote.status})", latency_ms=latency_ms,
        )
    if remote.status != 200:
        return EmbeddingTestResponse(
            success=False, status="network_error",
            message=f"HTTP {remote.status}: {response_text[:200]}", latency_ms=latency_ms,
        )

    try:
        import json as _json
        data = _json.loads(response_text)
        embedding = data["data"][0]["embedding"]
        returned_dim = len(embedding)
    except (KeyError, IndexError, TypeError, ValueError):
        return EmbeddingTestResponse(
            success=False, status="format_error",
            message="API 返回格式异常", latency_ms=latency_ms,
        )

    if returned_dim != dim:
        return EmbeddingTestResponse(
            success=False, status="dimension_mismatch",
            message=f"期望维度 {dim}，实际返回 {returned_dim}",
            latency_ms=latency_ms, returned_dim=returned_dim,
        )
    return EmbeddingTestResponse(
        success=True, status="ok",
        message="连接成功，维度匹配",
        latency_ms=latency_ms, returned_dim=returned_dim,
    )
