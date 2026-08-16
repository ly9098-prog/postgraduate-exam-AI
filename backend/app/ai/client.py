"""OpenAI-compatible chat-completions client.

This module is intentionally provider-neutral. Runtime credentials/model selection
come from ``admin_ai_model_configs`` and are passed explicitly by the gateway or
call site. Any provider exposing an OpenAI-compatible ``chat/completions`` API
with Bearer authentication can use the same adapter (OpenAI, DeepSeek, Qwen,
GLM, MiniMax, Moonshot, Volcengine Ark compatible endpoints, self-hosted vLLM,
etc.).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.ai_runtime_guard import AIResourceRejected, ai_runtime_guard
from app.core.config import settings
from app.core.log_context import get_trace_headers
from app.core.log_context import log_event
from app.services.safe_remote_fetch import request_remote_bytes
from app.utils.sentry_utils import capture_exception, set_tag, start_span

_ai_logger = logging.getLogger("app.ai")

def build_chat_completions_url(base_url: str) -> str:
    """Build a chat-completions URL using OpenAI SDK base-url semantics.

    Examples:
    - https://api.openai.com/v1 -> .../v1/chat/completions
    - https://dashscope.aliyuncs.com/compatible-mode/v1 -> .../v1/chat/completions
    - https://ark.cn-beijing.volces.com/api/v3 -> .../api/v3/chat/completions
    - https://api.deepseek.com -> .../v1/chat/completions (legacy root compatibility)
    - a full .../chat/completions endpoint is preserved as-is.
    """
    normalized = (base_url or "").strip().rstrip("/")
    if not normalized:
        raise RuntimeError("AI模型 API Base URL 未配置")

    parsed = urlparse(normalized)
    path = (parsed.path or "").rstrip("/")
    if path.endswith("/chat/completions"):
        return normalized
    # Historical DeepSeek config in this project stores the host root. Preserve
    # compatibility by inserting /v1 only when the URL has no path at all.
    if not path:
        return f"{normalized}/v1/chat/completions"
    return f"{normalized}/chat/completions"


def _normalise_message_content(content: Any) -> str:
    """Normalise common OpenAI-compatible content shapes to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    if content is None:
        return ""
    return str(content)


def _message_prompt_chars(content: Any) -> int:
    """Count textual prompt size without charging inline image base64 as text.

    Multimodal OpenAI-compatible messages represent images inside ``content``
    arrays. The image payload is bounded by the feature service; feeding its
    base64 representation into the text-char admission guard would reject every
    normal screenshot before the request reaches a vision model.
    """
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for item in content:
            if isinstance(item, str):
                total += len(item)
            elif isinstance(item, dict):
                if isinstance(item.get("text"), str):
                    total += len(item["text"])
                elif item.get("type") == "image_url":
                    total += 32  # small structural charge; image bytes are bounded separately
        return total
    return len(str(content)) if content is not None else 0


def _tokens_used(data: dict[str, Any]) -> int:
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return 0
    total = usage.get("total_tokens")
    if isinstance(total, (int, float)):
        return int(total)
    prompt = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
    completion = usage.get("completion_tokens") or usage.get("output_tokens") or 0
    try:
        return int(prompt) + int(completion)
    except (TypeError, ValueError):
        return 0


class OpenAICompatibleClient:
    """Provider-neutral OpenAI-compatible ``chat/completions`` client."""

    def __init__(self) -> None:
        # DB-managed runtime configuration; intentionally no provider-specific
        # process-global defaults.
        self._api_key = ""
        self._base_url = ""
        self.timeout = settings.AI_TIMEOUT
        self._client: httpx.AsyncClient | None = None

    @property
    def api_key(self) -> str:
        return self._api_key

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def client(self) -> httpx.AsyncClient:
        # Kept for backward compatibility with code/tests that inspect it.
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    def is_available(self) -> bool:
        """Whether process-global credentials exist (normally False).

        Runtime DB-backed code should resolve a model through ``app.ai.gateway``
        instead of relying on this legacy process-global check.
        """
        return bool(self._api_key and self._base_url)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        temperature: float | None = 0.3,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        provider: str | None = None,
        timeout: float | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        effective_key = api_key if api_key is not None else self._api_key
        effective_base_url = base_url if base_url is not None else self._base_url
        effective_provider = (provider or "openai_compatible").strip() or "openai_compatible"

        if not effective_key:
            raise RuntimeError("AI模型 API Key 未配置，请先在后台 AI 设置页面配置模型凭据")
        if not effective_base_url:
            raise RuntimeError("AI模型 API Base URL 未配置，请先在后台 AI 设置页面配置兼容接口地址")
        if not model:
            raise RuntimeError("AI模型标识未配置，请先在后台 AI 设置页面配置 model name")

        try:
            base_url_host = urlparse(effective_base_url).hostname or "-"
        except Exception:
            base_url_host = "-"

        prompt_chars = sum(_message_prompt_chars(m.get("content", "")) for m in messages)
        request_timeout = float(timeout if timeout is not None else self.timeout)
        if request_timeout <= 0:
            raise ValueError("timeout must be positive")

        endpoint_key = f"{effective_provider}:{base_url_host}"
        ai_runtime_guard.validate_prompt(prompt_chars)
        await ai_runtime_guard.enforce_rate_limit()
        ai_runtime_guard.record_request()

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if response_format is not None:
            payload["response_format"] = response_format
        if extra_body:
            # Explicit caller overrides are useful for compatible providers that
            # expose additional OpenAI-style fields (thinking, top_p, etc.).
            payload.update(extra_body)

        # Cost cap is applied last so extra_body cannot bypass it.
        requested_output_tokens = payload.get("max_tokens", max_tokens)
        effective_max_tokens = ai_runtime_guard.bounded_max_tokens(requested_output_tokens)
        if effective_max_tokens is not None:
            payload["max_tokens"] = effective_max_tokens

        log_event(
            _ai_logger,
            "ai.chat.start",
            provider=effective_provider,
            model=model,
            base_url_host=base_url_host,
            temperature=temperature,
            message_count=len(messages),
            prompt_chars=prompt_chars,
        )

        with start_span(op="ai.openai_compatible.chat", description=f"model={model}"):
            set_tag("ai.model", model)
            set_tag("ai.provider", effective_provider)

            start = time.time()
            provider_outcome_recorded = False
            try:
                url = build_chat_completions_url(effective_base_url)
                request_body = json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                sem, queue_wait_ms = await ai_runtime_guard.acquire_slot()
                try:
                    ai_runtime_guard.assert_circuit_available(endpoint_key)
                    remote = await asyncio.to_thread(
                        request_remote_bytes,
                        url,
                        method="POST",
                        body=request_body,
                        max_bytes=10 * 1024 * 1024,
                        timeout=request_timeout,
                        allow_http=settings.AI_ALLOW_HTTP_BASE_URLS,
                        follow_redirects=False,
                        headers={
                            **get_trace_headers(),
                            "Authorization": f"Bearer {effective_key}",
                            "Content-Type": "application/json",
                            "Accept": "application/json",
                        },
                    )
                finally:
                    ai_runtime_guard.release_slot(sem)

                response_text = remote.data.decode("utf-8", errors="replace")
                elapsed = int((time.time() - start) * 1000)

                if remote.status < 200 or remote.status >= 300:
                    error_body = response_text[:300]
                    retryable_status = remote.status == 429 or remote.status == 408 or remote.status >= 500
                    ai_runtime_guard.record_provider_failure(
                        endpoint_key, retryable=retryable_status
                    )
                    ai_runtime_guard.record_failure()
                    provider_outcome_recorded = True
                    log_event(
                        _ai_logger,
                        "ai.chat.error",
                        level="error",
                        provider=effective_provider,
                        model=model,
                        duration_ms=elapsed,
                        status_code=remote.status,
                        error_type="HTTPError",
                        error_message=error_body,
                    )
                    raise RuntimeError(
                        f"OpenAI-compatible API error: {remote.status} {error_body}"
                    )

                data = json.loads(response_text)
                choices = data.get("choices")
                if not isinstance(choices, list) or not choices:
                    raise RuntimeError("OpenAI-compatible API response missing choices[0]")
                choice = choices[0]
                if not isinstance(choice, dict):
                    raise RuntimeError("OpenAI-compatible API response has invalid choice format")
                message = choice.get("message")
                if not isinstance(message, dict):
                    raise RuntimeError("OpenAI-compatible API response missing choice.message")

                content = _normalise_message_content(message.get("content"))
                tokens = _tokens_used(data)
                response_chars = len(content)

                set_tag("ai.tokens", tokens)
                set_tag("ai.duration_ms", elapsed)
                ai_runtime_guard.record_provider_success(endpoint_key)
                ai_runtime_guard.record_success(tokens)
                provider_outcome_recorded = True

                log_event(
                    _ai_logger,
                    "ai.chat.finish",
                    provider=effective_provider,
                    model=model,
                    duration_ms=elapsed,
                    queue_wait_ms=round(queue_wait_ms, 1),
                    tokens_used=tokens,
                    response_chars=response_chars,
                )

                return {
                    "content": content,
                    "tokens_used": tokens,
                    "model": data.get("model") or model,
                    "provider": effective_provider,
                    "duration_ms": elapsed,
                    "finish_reason": choice.get("finish_reason"),
                }
            except AIResourceRejected as exc:
                log_event(
                    _ai_logger,
                    "ai.chat.rejected",
                    level="warning",
                    provider=effective_provider,
                    model=model,
                    reason=exc.reason,
                    retry_after_sec=exc.retry_after_sec,
                )
                raise
            except Exception as exc:
                if not provider_outcome_recorded:
                    ai_runtime_guard.record_provider_failure(endpoint_key, retryable=True)
                    ai_runtime_guard.record_failure()
                    provider_outcome_recorded = True
                if not (
                    isinstance(exc, RuntimeError)
                    and "OpenAI-compatible API error" in str(exc)
                ):
                    log_event(
                        _ai_logger,
                        "ai.chat.error",
                        level="error",
                        provider=effective_provider,
                        model=model,
                        duration_ms=int((time.time() - start) * 1000),
                        error_type=type(exc).__name__,
                        error_message=str(exc)[:300],
                    )
                capture_exception(
                    exc,
                    tags={"ai.model": model, "ai.provider": effective_provider},
                )
                raise

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
        await ai_runtime_guard.close()


# Canonical singleton used by new code.
llm = OpenAICompatibleClient()
openai_compatible = llm

# Backward-compatible aliases for extensions/tests that still import the old
# symbols. Internal project call sites are migrated to ``llm``/gateway.
DeepSeekClient = OpenAICompatibleClient
deepseek = llm
