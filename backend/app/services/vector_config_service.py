"""Embedding + vector config helpers.

模型身份与凭据统一由 ``admin_ai_model_configs`` 提供；``admin_ai_configs``
只保存向量检索参数和当前选中的 ``embedding_model_config_id``。
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.log_context import get_trace_headers
from app.core.secret_crypto import (
    SecretDecryptionError,
    SecretEncryptionError,
    decrypt_secret,
)
from app.models.admin_ai_config import AdminAiConfig, AdminAiModelConfig


class EmbeddingConfig:
    """解析后的 Embedding 运行时配置（包含调用期明文 key）。"""

    api_key: str = ""
    base_url: str = ""
    model: str = ""
    dim: int = 0
    timeout: int = 0
    batch_size: int = 0
    provider: str = ""
    model_config_id: int | None = None

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


@dataclass
class VectorSearchConfig:
    """向量检索运行时配置。"""

    enabled: bool = False
    mode: str = "off"
    allowlist: str = ""
    cache_ttl_sec: int = 300
    top_k: int = 100
    similarity_threshold: float = 0.15


async def _read_cfg(db: AsyncSession) -> dict[str, str]:
    result = await db.execute(select(AdminAiConfig))
    return {r.config_key: r.config_value for r in result.scalars().all()}


def _model_features(model: AdminAiModelConfig) -> list[str]:
    if isinstance(model.features, list):
        return [str(item) for item in model.features if str(item).strip()]
    if model.feature:
        return [model.feature]
    return []


async def resolve_embedding_model(
    db: AsyncSession,
    *,
    requested_model_config_id: int | None = None,
    configs: dict[str, str] | None = None,
) -> AdminAiModelConfig | None:
    """解析当前 Embedding 模型。

    优先级：显式 ``requested_model_config_id`` → 向量配置中保存的 model id →
    第一个启用且带 ``embedding`` capability 的模型。不会回退到 Chat 模型。
    """

    cfg = configs if configs is not None else await _read_cfg(db)
    selected_id = requested_model_config_id
    if selected_id is None:
        raw = (cfg.get("embedding_model_config_id") or "").strip()
        if raw:
            try:
                selected_id = int(raw)
            except ValueError:
                selected_id = None

    if selected_id is not None:
        model = await db.get(AdminAiModelConfig, selected_id)
        if model is None:
            raise ValueError(
                f"Embedding 模型配置 #{selected_id} 不存在，请重新选择模型"
            )
        if not model.is_enabled:
            raise ValueError(
                f"Embedding 模型「{model.display_name}」已禁用，请先启用或重新选择"
            )
        if "embedding" not in _model_features(model):
            raise ValueError(f"模型「{model.display_name}」未声明 Embedding 能力")
        return model

    result = await db.execute(
        select(AdminAiModelConfig)
        .where(AdminAiModelConfig.is_enabled == True)  # noqa: E712
        .order_by(
            AdminAiModelConfig.is_default.desc(), AdminAiModelConfig.sort_order.asc()
        )
    )
    for model in result.scalars().all():
        if "embedding" in _model_features(model):
            return model
    return None


async def resolve_embedding_config(
    db: AsyncSession,
    *,
    requested_model_config_id: int | None = None,
    dim: int | None = None,
    timeout: int | None = None,
    batch_size: int | None = None,
) -> EmbeddingConfig:
    """从模型注册中心 + 向量运行参数构建 EmbeddingConfig。"""

    cfg = await _read_cfg(db)
    model = await resolve_embedding_model(
        db,
        requested_model_config_id=requested_model_config_id,
        configs=cfg,
    )

    if model is None:
        return EmbeddingConfig(
            api_key="",
            base_url="",
            model="",
            dim=dim or int(cfg.get("embedding_dim", settings.EMBEDDING_DIM)),
            timeout=timeout
            or int(cfg.get("embedding_timeout", settings.EMBEDDING_TIMEOUT)),
            batch_size=batch_size
            or int(cfg.get("embedding_batch_size", settings.EMBEDDING_BATCH_SIZE)),
            provider="",
            model_config_id=None,
        )

    api_key = ""
    if model.api_key_encrypted:
        try:
            api_key = decrypt_secret(model.api_key_encrypted)
        except (SecretDecryptionError, SecretEncryptionError):
            api_key = ""

    return EmbeddingConfig(
        api_key=api_key,
        base_url=(model.api_base_url or "").rstrip("/"),
        model=model.name,
        dim=dim or int(cfg.get("embedding_dim", settings.EMBEDDING_DIM)),
        timeout=timeout
        or int(cfg.get("embedding_timeout", settings.EMBEDDING_TIMEOUT)),
        batch_size=batch_size
        or int(cfg.get("embedding_batch_size", settings.EMBEDDING_BATCH_SIZE)),
        provider=model.provider,
        model_config_id=model.id,
    )


def get_embedding_config_sync() -> EmbeddingConfig:
    """无 DB 上下文时的兼容兜底，仅供旧调用/测试使用。"""
    return EmbeddingConfig(
        api_key="",
        base_url=settings.EMBEDDING_BASE_URL,
        model=settings.EMBEDDING_MODEL,
        dim=settings.EMBEDDING_DIM,
        timeout=settings.EMBEDDING_TIMEOUT,
        batch_size=settings.EMBEDDING_BATCH_SIZE,
        provider=settings.EMBEDDING_PROVIDER,
        model_config_id=None,
    )


async def test_embedding_connection(
    api_base_url: str,
    api_key: str | None,
    model: str,
    dim: int | None = None,
    timeout: int = 30,
) -> "EmbeddingTestResponse":  # noqa: F821
    """对给定 Embedding 模型发起一次最小 OpenAI-compatible 调用。"""
    from app.schemas.admin_vector_config import EmbeddingTestResponse

    if not api_key:
        return EmbeddingTestResponse(
            success=False,
            status="auth_error",
            message="该模型未配置 API Key，请先在“模型配置”中保存凭据",
            latency_ms=0,
        )
    if not api_base_url or not model:
        return EmbeddingTestResponse(
            success=False,
            status="network_error",
            message="该 Embedding 模型缺少 Base URL 或模型标识",
            latency_ms=0,
        )

    import asyncio
    import json
    import time as _time

    try:
        from app.services.safe_remote_fetch import validate_remote_url

        validate_remote_url(api_base_url, allow_http=settings.AI_ALLOW_HTTP_BASE_URLS)
    except ValueError as exc:
        return EmbeddingTestResponse(
            success=False,
            status="network_error",
            message=str(exc),
            latency_ms=0,
        )

    from app.services.embedding_service import build_embeddings_url

    url = build_embeddings_url(api_base_url)
    headers = {
        **get_trace_headers(),
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {"model": model, "input": "test"}
    start = _time.monotonic()

    try:
        from app.services.safe_remote_fetch import request_remote_bytes

        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        remote = await asyncio.to_thread(
            request_remote_bytes,
            url,
            method="POST",
            body=body,
            max_bytes=64 * 1024 * 1024,
            timeout=float(timeout),
            allow_http=settings.AI_ALLOW_HTTP_BASE_URLS,
            follow_redirects=False,
            headers=headers,
        )
    except Exception as exc:
        return EmbeddingTestResponse(
            success=False,
            status="network_error",
            message=str(exc)[:200],
            latency_ms=int((_time.monotonic() - start) * 1000),
        )

    latency_ms = int((_time.monotonic() - start) * 1000)
    response_text = remote.data.decode("utf-8", errors="replace")
    if remote.status in (401, 403):
        return EmbeddingTestResponse(
            success=False,
            status="auth_error",
            message=f"认证失败 (HTTP {remote.status})",
            latency_ms=latency_ms,
        )
    if remote.status != 200:
        message = f"HTTP {remote.status}: {response_text[:200]}"
        if remote.status == 404:
            from urllib.parse import urlparse

            parsed = urlparse(url)
            host = (parsed.hostname or "").lower()
            if host.endswith(".maas.aliyuncs.com") or "dashscope" in host:
                message = (
                    "HTTP 404：Embedding 接口或模型标识不存在。"
                    f"实际请求 {url}。"
                    "阿里云百炼 OpenAI-compatible Base URL 应以 /compatible-mode/v1 结尾，"
                    "文本 Embedding 模型请使用控制台实际 Model ID（例如 text-embedding-v4），"
                    "不要把 Qwen Chat 模型名称拼成 text-embedding 名称。"
                )
            else:
                message = (
                    "HTTP 404：Embedding 接口不存在。"
                    f"实际请求 {url}。请确认填写的是 SDK base_url，"
                    "并确认供应商支持 OpenAI-compatible /embeddings。"
                )
        return EmbeddingTestResponse(
            success=False,
            status="network_error",
            message=message,
            latency_ms=latency_ms,
        )

    try:
        data = json.loads(response_text)
        embedding = data["data"][0]["embedding"]
        returned_dim = len(embedding)
    except (KeyError, IndexError, TypeError, ValueError):
        return EmbeddingTestResponse(
            success=False,
            status="format_error",
            message="API 返回格式异常：未找到 data[0].embedding",
            latency_ms=latency_ms,
        )

    if dim is not None and returned_dim != dim:
        return EmbeddingTestResponse(
            success=False,
            status="dimension_mismatch",
            message=f"连接成功，但期望维度 {dim}，实际返回 {returned_dim}",
            latency_ms=latency_ms,
            returned_dim=returned_dim,
        )

    suffix = f"，返回维度 {returned_dim}" if returned_dim else ""
    return EmbeddingTestResponse(
        success=True,
        status="ok",
        message=f"连接成功{suffix}",
        latency_ms=latency_ms,
        returned_dim=returned_dim,
    )
