"""Admin connection tests for saved and unsaved AI model configurations."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from urllib.parse import urljoin

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.log_context import get_trace_headers
from app.core.secret_crypto import (
    SecretDecryptionError,
    SecretEncryptionError,
    decrypt_secret,
)
from app.models.admin_ai_config import AdminAiModelConfig
from app.services.ai.analysis_admin_health import test_matching_saved_model
from app.services.ai.connection_probe import (
    probe_chat_connection,
    validated_api_base_url,
)
from app.services.safe_remote_fetch import request_remote_bytes

logger = logging.getLogger(__name__)

PADDLE_PROBE_TIMEOUT_SECONDS = 15.0
PADDLE_PROBE_MAX_BYTES = 1024 * 1024
ERROR_DETAIL_MAX_CHARS = 160


@dataclass(frozen=True, slots=True)
class _ConnectionTarget:
    api_base_url: str
    api_key: str
    model_name: str
    model_id: int | None
    db: AsyncSession | None
    provider: str | None
    features: tuple[str, ...]


async def test_model_connection(
    api_base_url: str,
    api_key: str | None,
    model_name: str,
    model_id: int | None = None,
    db: AsyncSession | None = None,
    provider: str | None = None,
    feature: str | None = None,
    features: list[str] | None = None,
) -> dict:
    """Test one model through the same adapters used by production traffic."""
    target, error = await _build_target(
        api_base_url=api_base_url,
        api_key=api_key,
        model_name=model_name,
        model_id=model_id,
        db=db,
        provider=provider,
        feature=feature,
        features=features,
    )
    if error is not None:
        return error
    special_result = await _test_non_chat_target(target)
    if special_result is not None:
        return special_result
    saved_result = await test_matching_saved_model(
        target.db,
        target.model_id,
        base_url=target.api_base_url,
        api_key=target.api_key,
        model_name=target.model_name,
        provider=target.provider,
        features=target.features,
    )
    if saved_result is not None:
        return saved_result
    return await probe_chat_connection(
        target.api_base_url,
        target.api_key,
        target.model_name,
        provider=target.provider,
    )


async def _build_target(
    *,
    api_base_url: str,
    api_key: str | None,
    model_name: str,
    model_id: int | None,
    db: AsyncSession | None,
    provider: str | None,
    feature: str | None,
    features: list[str] | None,
) -> tuple[_ConnectionTarget, dict | None]:
    model, error = await _load_saved_model(db, model_id)
    if error is not None:
        return _empty_target(), error
    provider, feature_set = _resolve_model_defaults(
        provider,
        feature,
        features,
        model,
    )
    key, error = _resolve_api_key(api_key, model)
    if error is not None:
        return _empty_target(), error
    if not key:
        return _empty_target(), _auth_error(
            "未提供 API Key，请在上方输入后测试，或先保存模型配置"
        )
    try:
        base_url = validated_api_base_url(api_base_url) or ""
    except ValueError as exc:
        return _empty_target(), _network_error(str(exc))
    return (
        _ConnectionTarget(
            api_base_url=base_url,
            api_key=key,
            model_name=model_name,
            model_id=model_id,
            db=db,
            provider=provider,
            features=feature_set,
        ),
        None,
    )


async def _load_saved_model(
    db: AsyncSession | None,
    model_id: int | None,
) -> tuple[AdminAiModelConfig | None, dict | None]:
    if db is None or model_id is None:
        return None, None
    model = await db.get(AdminAiModelConfig, model_id)
    if model is not None and model.deleted_at is not None:
        return None, _deleted_model_error(model_id)
    if model is not None:
        return model, None

    from app.services.admin_ai_config_service import seed_models_if_empty

    await seed_models_if_empty(db)
    await db.flush()
    model = await db.get(AdminAiModelConfig, model_id)
    if model is not None and model.deleted_at is not None:
        return None, _deleted_model_error(model_id)
    return model, None


def _resolve_model_defaults(
    provider: str | None,
    feature: str | None,
    features: list[str] | None,
    model: AdminAiModelConfig | None,
) -> tuple[str | None, tuple[str, ...]]:
    resolved = list(features or [])
    if feature and feature not in resolved:
        resolved.append(feature)
    if model is None:
        return provider, tuple(resolved)
    resolved_provider = provider or model.provider
    if resolved:
        return resolved_provider, tuple(resolved)
    model_features = model.features or ([model.feature] if model.feature else [])
    return resolved_provider, tuple(model_features)


def _resolve_api_key(
    explicit_api_key: str | None,
    model: AdminAiModelConfig | None,
) -> tuple[str | None, dict | None]:
    key = (explicit_api_key or "").strip() or None
    if key is not None or model is None or not model.api_key_encrypted:
        return key, None
    try:
        return decrypt_secret(model.api_key_encrypted), None
    except (SecretDecryptionError, SecretEncryptionError):
        return None, _auth_error(
            "数据库中保存的 API Key 无法解密，请检查加密配置或重新保存凭据"
        )


async def _test_non_chat_target(target: _ConnectionTarget) -> dict | None:
    if "embedding" in target.features:
        return await _test_embedding_target(target)
    if _is_paddleocr_target(target):
        return await _test_paddleocr_vl_connection(target)
    return None


async def _test_embedding_target(target: _ConnectionTarget) -> dict:
    from app.services.vector_config_service import test_embedding_connection

    result = await test_embedding_connection(
        api_base_url=target.api_base_url,
        api_key=target.api_key,
        model=target.model_name,
        dim=None,
        timeout=15,
    )
    return {
        "success": result.success,
        "status": result.status,
        "message": result.message,
        "latency_ms": result.latency_ms,
        "model_returned": target.model_name if result.success else None,
    }


def _is_paddleocr_target(target: _ConnectionTarget) -> bool:
    provider = (target.provider or "").strip().lower().replace("_", "-")
    return (
        "vision" in target.features
        or provider == "paddle"
        or provider.startswith("paddleocr")
    )


async def _test_paddleocr_vl_connection(target: _ConnectionTarget) -> dict:
    start = time.monotonic()
    try:
        remote = await _request_paddle_probe(target)
    except Exception as exc:
        logger.warning("admin.ai_model.paddle_probe_failed", exc_info=True)
        return _network_error(
            f"请求失败: {str(exc)[:ERROR_DETAIL_MAX_CHARS]}",
            start=start,
        )
    return _paddle_result(remote.status, start)


async def _request_paddle_probe(target: _ConnectionTarget):
    url = urljoin(target.api_base_url + "/", "/api/v2/ocr/jobs")
    return await asyncio.to_thread(
        request_remote_bytes,
        url,
        method="GET",
        max_bytes=PADDLE_PROBE_MAX_BYTES,
        timeout=PADDLE_PROBE_TIMEOUT_SECONDS,
        allow_http=settings.AI_ALLOW_HTTP_BASE_URLS,
        follow_redirects=False,
        headers={
            **get_trace_headers(),
            "Authorization": f"Bearer {target.api_key}",
            "Accept": "application/json",
        },
    )


def _paddle_result(status: int, start: float) -> dict:
    elapsed = _elapsed_ms(start)
    if status in {401, 403}:
        return {
            "success": False,
            "status": "auth_error",
            "message": f"API Key 无效或无权限访问 (HTTP {status})",
            "latency_ms": elapsed,
        }
    if status in {301, 302, 303, 307, 308}:
        return {
            "success": False,
            "status": "network_error",
            "message": "服务返回重定向；为防止凭据泄露，测试请求不会跟随重定向",
            "latency_ms": elapsed,
        }
    return {
        "success": True,
        "status": "ok",
        "message": (
            f"连接成功（HTTP {status}），API Key 通过基本校验，"
            f"服务端响应时延 {elapsed}ms"
        ),
        "latency_ms": elapsed,
    }


def _deleted_model_error(model_id: int) -> dict:
    return {
        "success": False,
        "status": "model_not_found",
        "message": f"模型配置 #{model_id} 已删除，请重新选择模型",
        "latency_ms": 0,
    }


def _auth_error(message: str) -> dict:
    return {
        "success": False,
        "status": "auth_error",
        "message": message,
        "latency_ms": 0,
    }


def _network_error(message: str, *, start: float | None = None) -> dict:
    return {
        "success": False,
        "status": "network_error",
        "message": message,
        "latency_ms": _elapsed_ms(start) if start is not None else 0,
    }


def _empty_target() -> _ConnectionTarget:
    return _ConnectionTarget(
        api_base_url="",
        api_key="",
        model_name="",
        model_id=None,
        db=None,
        provider=None,
        features=(),
    )


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
