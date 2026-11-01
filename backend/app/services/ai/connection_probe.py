"""Minimal OpenAI-compatible connection probe shared by Admin and analysis."""

from __future__ import annotations

import json
import logging
import time
from urllib.parse import urlsplit

from app.ai.client import OpenAICompatibleAPIError, llm
from app.core.config import settings
from app.services.safe_remote_fetch import (
    UnsafeRemoteURLError,
    validate_remote_url,
)

logger = logging.getLogger(__name__)

PROBE_TIMEOUT_SECONDS = 55.0
PROBE_MAX_TOKENS = 8
PROBE_PROMPT = "Reply with OK only."
DETAIL_MAX_CHARS = 160
FORMAT_DETAIL_MAX_CHARS = 120


def validated_api_base_url(value: str | None) -> str | None:
    normalized = str(value or "").strip().rstrip("/")
    if not normalized:
        return None
    parsed = urlsplit(normalized)
    if parsed.query or parsed.fragment:
        raise ValueError("API Base URL 不能包含查询参数或片段")
    try:
        validate_remote_url(
            normalized,
            allow_http=settings.AI_ALLOW_HTTP_BASE_URLS,
        )
    except UnsafeRemoteURLError as exc:
        raise ValueError(f"API Base URL 不安全或不可用: {exc}") from exc
    return normalized


async def probe_chat_connection(
    api_base_url: str,
    api_key: str,
    model_name: str,
    *,
    provider: str | None = None,
) -> dict:
    """Exercise the same adaptive chat client used by production traffic."""
    start = time.monotonic()
    try:
        result = await _probe_chat(
            api_base_url,
            api_key,
            model_name,
            provider=provider,
        )
    except TimeoutError:
        return _failure(
            "timeout",
            "连接模型超时，请检查第三方接口可用性或模型响应速度",
            start,
        )
    except OpenAICompatibleAPIError as exc:
        return _provider_failure(exc, model_name, start)
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        message = (
            "接口返回格式不符合 OpenAI Chat Completions 规范: "
            f"{str(exc)[:FORMAT_DETAIL_MAX_CHARS]}"
        )
        return _failure("format_error", message, start)
    except ValueError as exc:
        return _failure(
            "network_error", _detail("请求失败", exc, DETAIL_MAX_CHARS), start
        )
    except RuntimeError as exc:
        return _runtime_failure(exc, start)
    except Exception as exc:
        logger.warning("ai.connection_probe.failed", exc_info=True)
        return _failure(
            "network_error", _detail("请求失败", exc, DETAIL_MAX_CHARS), start
        )
    return _success(result, model_name, start)


async def _probe_chat(
    api_base_url: str,
    api_key: str,
    model_name: str,
    *,
    provider: str | None,
) -> dict:
    return await llm.chat(
        [{"role": "user", "content": PROBE_PROMPT}],
        temperature=0.0,
        model=model_name,
        api_key=api_key,
        base_url=validated_api_base_url(api_base_url) or "",
        provider=provider or "openai_compatible",
        timeout=PROBE_TIMEOUT_SECONDS,
        max_tokens=PROBE_MAX_TOKENS,
        prefer_direct_answer=True,
        connection_probe=True,
    )


def _success(result: dict, model_name: str, start: float) -> dict:
    returned_model = str(result.get("model") or model_name)
    message = f"连接成功，模型「{returned_model}」响应正常"
    if int(result.get("compatibility_retries") or 0) > 0:
        message += "；已自动适配该接口的 OpenAI-compatible 参数格式"
    return {
        "success": True,
        "status": "ok",
        "message": message,
        "latency_ms": int(result.get("duration_ms") or _elapsed_ms(start)),
        "model_returned": returned_model or None,
    }


def _provider_failure(
    exc: OpenAICompatibleAPIError,
    model_name: str,
    start: float,
) -> dict:
    if exc.error_kind == "quota":
        return _failure("quota_error", "模型账户余额或调用额度不足", start)
    if exc.status_code in {401, 403}:
        return _failure(
            "auth_error",
            f"API Key 无效或无权限访问 (HTTP {exc.status_code})",
            start,
        )
    if exc.status_code == 404 or exc.error_kind == "model_not_found":
        return _failure(
            "model_not_found",
            f"模型「{model_name}」不存在，请检查模型名称是否正确",
            start,
        )
    return _failure(
        "unknown_error",
        f"接口返回异常状态码 {exc.status_code}",
        start,
    )


def _runtime_failure(exc: RuntimeError, start: float) -> dict:
    message = str(exc)
    if "OpenAI-compatible API response" in message:
        return _failure(
            "format_error",
            "接口返回格式不符合 OpenAI Chat Completions 规范",
            start,
        )
    return _failure(
        "network_error",
        _detail("请求失败", exc, DETAIL_MAX_CHARS),
        start,
    )


def _failure(status: str, message: str, start: float) -> dict:
    return {
        "success": False,
        "status": status,
        "message": message,
        "latency_ms": _elapsed_ms(start),
    }


def _detail(prefix: str, exc: Exception, limit: int) -> str:
    return f"{prefix}: {str(exc)[:limit]}"


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
