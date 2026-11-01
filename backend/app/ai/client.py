"""Provider-neutral OpenAI-compatible chat-completions client.

Runtime credentials/model selection come from ``admin_ai_model_configs`` and are
passed explicitly by the gateway or call site.  Compatibility is negotiated at
the *protocol field* level instead of by hard-coding model names, so OpenAI,
DeepSeek, Qwen, GLM, MiniMax, Moonshot, Ark, vLLM and most relay/proxy services
can share the same adapter as long as they expose a Chat Completions-compatible
endpoint with Bearer authentication.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from app.ai.provider_error_signals import has_quota_error_marker
from app.core.ai_runtime_guard import AIResourceRejectedError, ai_runtime_guard
from app.core.config import settings
from app.core.log_context import get_trace_headers, log_event
from app.services.safe_remote_fetch import request_remote_bytes
from app.utils.sentry_utils import capture_exception, set_tag, start_span

_ai_logger = logging.getLogger("app.ai")


class OpenAICompatibleAPIError(RuntimeError):
    """Typed upstream HTTP failure without embedding provider response bodies.

    Provider error payloads may contain credential fragments or other sensitive
    diagnostics. Callers only need the HTTP status and retryability to choose a
    safe fallback, so keep the exception message deliberately compact.
    """

    def __init__(
        self,
        status_code: int,
        *,
        retryable: bool,
        error_kind: str | None = None,
    ) -> None:
        self.status_code = int(status_code)
        self.retryable = bool(retryable)
        self.error_kind = str(error_kind or "") or None
        super().__init__(f"OpenAI-compatible API error: {self.status_code}")


@dataclass(frozen=True)
class _CompatibilityProfile:
    """Learned request dialect for one endpoint/model pair.

    These are protocol capabilities, not vendor/model-name rules. A profile is
    learned only from successful requests (or explicit parameter rejections),
    then reused by later calls in the same worker process.
    """

    reasoning_control: str | None = "reasoning_effort"
    token_field: str | None = "max_tokens"
    allow_temperature: bool = True
    allow_response_format: bool = True


_REASONING_CONTROLS: tuple[str | None, ...] = (
    "reasoning_effort",  # OpenAI-style reasoning + recent vLLM
    "enable_thinking",  # several hosted compatible gateways
    "chat_template_enable_thinking",  # vLLM/Qwen-style chat template kwargs
    "chat_template_thinking",  # vLLM models using a thinking boolean
    "thinking",  # gateways exposing {"type": "disabled"}
    None,  # strict/minimal Chat Completions fallback
)
_TOKEN_FIELDS: tuple[str | None, ...] = (
    "max_tokens",
    "max_completion_tokens",
)
_PROFILE_CACHE_LIMIT = 256
_MAX_COMPATIBILITY_ATTEMPTS = 12


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
                # Common variants include {"type":"text","text":"..."},
                # {"type":"output_text","text":"..."} and wrappers where
                # ``text`` itself is an object containing ``value``.
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
                elif isinstance(text, dict):
                    nested = text.get("value") or text.get("content")
                    if isinstance(nested, str):
                        parts.append(nested)
        return "".join(parts)
    if isinstance(content, dict):
        for key in ("text", "value", "content"):
            if key in content:
                return _normalise_message_content(content.get(key))
        return ""
    if content is None:
        return ""
    return str(content)


def _message_prompt_chars(content: Any) -> int:
    """Count textual prompt size without charging inline image base64 as text."""
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
                    total += 32  # image bytes are bounded by the feature service
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


def _profile_cache_key(provider: str, base_url: str, model: str) -> str:
    """Create a non-secret endpoint/model key without retaining query/userinfo."""
    try:
        parsed = urlparse(base_url)
        host = (parsed.hostname or "").lower()
        port = f":{parsed.port}" if parsed.port else ""
        endpoint = f"{parsed.scheme.lower()}://{host}{port}{parsed.path.rstrip('/')}"
    except Exception:
        endpoint = base_url.split("?", 1)[0]
    return f"{provider.lower()}|{endpoint}|{model.lower()}"


def _compatibility_error_text(raw: str) -> str:
    """Bound provider diagnostics used only for local compatibility decisions."""
    # Do not log or surface this value. Limiting it also avoids pathological
    # provider bodies affecting local parsing cost.
    return (raw or "")[:8192].lower()


def _looks_like_parameter_rejection(status: int, raw: str) -> bool:
    if status not in {400, 422}:
        return False
    text = _compatibility_error_text(raw)
    strong_markers = (
        "unsupported parameter",
        "unsupported_param",
        "unknown parameter",
        "unrecognized parameter",
        "unrecognised parameter",
        "unexpected parameter",
        "invalid parameter",
        "extra inputs are not permitted",
        "extra_forbidden",
        "unexpected keyword",
    )
    if any(marker in text for marker in strong_markers):
        return True
    # A bare "not supported" can describe the model, image input or account
    # rather than a request field. Treat it as negotiable only when the body also
    # names one of the optional fields this adapter knows how to translate.
    optional_names = (
        "reasoning_effort",
        "enable_thinking",
        "chat_template_kwargs",
        "thinking",
        "max_tokens",
        "max_completion_tokens",
        "temperature",
        "response_format",
    )
    return "not supported" in text and any(name in text for name in optional_names)


def _classify_http_error_kind(status: int, raw: str) -> str | None:
    """Reduce an upstream body to a non-sensitive diagnostic category."""
    text = _compatibility_error_text(raw)
    if has_quota_error_marker(text):
        return "quota"
    if status in {401, 403}:
        return "auth"
    if status == 429:
        return "rate_limit"
    if status == 408 or status >= 500:
        return "transient"
    if status == 404:
        return "model_not_found"
    if status in {400, 422}:
        model_markers = (
            "model does not exist",
            "model not found",
            "model_not_found",
            "invalid model",
            "unknown model",
            "no such model",
        )
        if any(marker in text for marker in model_markers):
            return "model_not_found"
        vision_markers = ("image_url", "image input", "vision", "multimodal")
        if any(marker in text for marker in vision_markers) and any(
            marker in text
            for marker in ("not supported", "unsupported", "does not support")
        ):
            return "vision_unsupported"
        if _looks_like_parameter_rejection(status, raw):
            return "parameter_unsupported"
        return "invalid_request"
    return None


def _rejected_optional_field(raw: str) -> str | None:
    text = _compatibility_error_text(raw)
    # Longer/specific names first so ``thinking`` does not swallow
    # ``enable_thinking``.
    aliases: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("max_completion_tokens", ("max_completion_tokens", "max completion tokens")),
        ("reasoning_effort", ("reasoning_effort", "reasoning effort")),
        ("chat_template_kwargs", ("chat_template_kwargs", "chat template kwargs")),
        ("enable_thinking", ("enable_thinking", "enable thinking")),
        ("response_format", ("response_format", "response format")),
        ("max_tokens", ("max_tokens", "max tokens")),
        ("temperature", ("temperature",)),
        ("thinking", ('"thinking"', "'thinking'", " thinking ")),
    )
    for canonical, candidates in aliases:
        if any(candidate in text for candidate in candidates):
            return canonical
    return None


def _next_value(current: str | None, values: tuple[str | None, ...]) -> str | None:
    try:
        index = values.index(current)
    except ValueError:
        return values[0]
    if index + 1 >= len(values):
        return current
    return values[index + 1]


def _reasoning_payload(control: str | None) -> dict[str, Any]:
    if control == "reasoning_effort":
        return {"reasoning_effort": "none"}
    if control == "enable_thinking":
        return {"enable_thinking": False}
    if control == "chat_template_enable_thinking":
        return {"chat_template_kwargs": {"enable_thinking": False}}
    if control == "chat_template_thinking":
        return {"chat_template_kwargs": {"thinking": False}}
    if control == "thinking":
        return {"thinking": {"type": "disabled"}}
    return {}


def _profile_label(profile: _CompatibilityProfile, *, direct_answer: bool) -> str:
    reasoning = profile.reasoning_control if direct_answer else "default"
    return (
        f"reasoning={reasoning or 'provider_default'};"
        f"tokens={profile.token_field or 'provider_default'};"
        f"temperature={'on' if profile.allow_temperature else 'off'};"
        f"response_format={'on' if profile.allow_response_format else 'off'}"
    )


class OpenAICompatibleClient:
    """Provider-neutral OpenAI-compatible ``chat/completions`` client.

    The adapter performs bounded, rejection-driven compatibility negotiation for
    optional Chat Completions fields. It never branches on model names. A 400/422
    saying an optional field is unsupported causes an immediate retry with the
    next protocol dialect; successful dialects are cached per endpoint/model.
    """

    def __init__(self) -> None:
        # DB-managed runtime configuration; intentionally no provider-specific
        # process-global defaults.
        self._api_key = ""
        self._base_url = ""
        self.timeout = settings.AI_TIMEOUT
        self._client: httpx.AsyncClient | None = None
        self._compatibility_profiles: OrderedDict[str, _CompatibilityProfile] = (
            OrderedDict()
        )

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
        """Whether process-global credentials exist (normally False)."""
        return bool(self._api_key and self._base_url)

    def _get_profile(self, key: str) -> _CompatibilityProfile:
        cached = self._compatibility_profiles.get(key)
        if cached is not None:
            self._compatibility_profiles.move_to_end(key)
            return cached
        return _CompatibilityProfile()

    def _remember_profile(self, key: str, profile: _CompatibilityProfile) -> None:
        self._compatibility_profiles[key] = profile
        self._compatibility_profiles.move_to_end(key)
        while len(self._compatibility_profiles) > _PROFILE_CACHE_LIMIT:
            self._compatibility_profiles.popitem(last=False)

    @staticmethod
    def _build_payload(
        *,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float | None,
        response_format: dict[str, Any] | None,
        extra_body: dict[str, Any] | None,
        effective_max_tokens: int | None,
        prefer_direct_answer: bool,
        profile: _CompatibilityProfile,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": model, "messages": messages}
        explicit = dict(extra_body or {})

        explicit_reasoning = any(
            key in explicit
            for key in (
                "reasoning_effort",
                "enable_thinking",
                "chat_template_kwargs",
                "thinking",
            )
        )
        explicit_token_limit = any(
            key in explicit for key in ("max_tokens", "max_completion_tokens")
        )

        if temperature is not None and profile.allow_temperature:
            payload["temperature"] = temperature
        if response_format is not None and profile.allow_response_format:
            payload["response_format"] = response_format
        if prefer_direct_answer and not explicit_reasoning:
            payload.update(_reasoning_payload(profile.reasoning_control))
        if (
            effective_max_tokens is not None
            and not explicit_token_limit
            and profile.token_field
        ):
            payload[profile.token_field] = effective_max_tokens

        # Explicit caller extensions win over inferred compatibility fields. The
        # output-token cap is normalized again by the caller before this method.
        payload.update(explicit)
        return payload

    @staticmethod
    def _adapt_profile(
        profile: _CompatibilityProfile,
        *,
        rejected_field: str | None,
        prefer_direct_answer: bool,
        temperature_requested: bool,
        response_format_requested: bool,
        token_limit_requested: bool,
        generic_parameter_rejection: bool,
    ) -> _CompatibilityProfile | None:
        reasoning = profile.reasoning_control
        token_field = profile.token_field
        allow_temperature = profile.allow_temperature
        allow_response_format = profile.allow_response_format

        if rejected_field in {
            "reasoning_effort",
            "enable_thinking",
            "chat_template_kwargs",
            "thinking",
        }:
            if not prefer_direct_answer:
                return None
            next_reasoning = _next_value(reasoning, _REASONING_CONTROLS)
            if next_reasoning == reasoning:
                return None
            reasoning = next_reasoning
        elif rejected_field in {"max_tokens", "max_completion_tokens"}:
            if not token_limit_requested:
                return None
            next_token = _next_value(token_field, _TOKEN_FIELDS)
            if next_token == token_field:
                return None
            token_field = next_token
        elif rejected_field == "temperature":
            if not temperature_requested or not allow_temperature:
                return None
            allow_temperature = False
        elif rejected_field == "response_format":
            if not response_format_requested or not allow_response_format:
                return None
            allow_response_format = False
        elif generic_parameter_rejection:
            # Some relays only say "unsupported parameter" without naming it.
            # Remove/translate the least essential inferred fields in a stable
            # order; never mutate arbitrary caller-provided extra_body fields.
            if prefer_direct_answer and reasoning is not None:
                reasoning = _next_value(reasoning, _REASONING_CONTROLS)
            elif temperature_requested and allow_temperature:
                allow_temperature = False
            elif token_limit_requested and token_field is not None:
                token_field = _next_value(token_field, _TOKEN_FIELDS)
            elif response_format_requested and allow_response_format:
                allow_response_format = False
            else:
                return None
        else:
            return None

        candidate = _CompatibilityProfile(
            reasoning_control=reasoning,
            token_field=token_field,
            allow_temperature=allow_temperature,
            allow_response_format=allow_response_format,
        )
        return candidate if candidate != profile else None

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
        prefer_direct_answer: bool = False,
        connection_probe: bool = False,
    ) -> dict[str, Any]:
        """Invoke a Chat Completions-compatible endpoint.

        ``prefer_direct_answer`` is a semantic hint used by short synchronous
        tasks. Instead of checking model names, the client tries common
        no-thinking protocol controls only when the provider explicitly rejects
        the current optional field, then caches the successful dialect.

        ``connection_probe`` is reserved for the admin connection-test path. It
        bypasses user-traffic rate/circuit/concurrency accounting so an operator
        can retest a repaired endpoint even while its runtime circuit is open;
        prompt and output-token safety bounds still apply.
        """
        effective_key = api_key if api_key is not None else self._api_key
        effective_base_url = base_url if base_url is not None else self._base_url
        effective_provider = (
            provider or "openai_compatible"
        ).strip() or "openai_compatible"

        if not effective_key:
            raise RuntimeError(
                "AI模型 API Key 未配置，请先在后台 AI 设置页面配置模型凭据"
            )
        if not effective_base_url:
            raise RuntimeError(
                "AI模型 API Base URL 未配置，请先在后台 AI 设置页面配置兼容接口地址"
            )
        if not model:
            raise RuntimeError(
                "AI模型标识未配置，请先在后台 AI 设置页面配置 model name"
            )

        try:
            base_url_host = urlparse(effective_base_url).hostname or "-"
        except Exception:
            base_url_host = "-"

        prompt_chars = sum(
            _message_prompt_chars(m.get("content", "")) for m in messages
        )
        request_timeout = float(timeout if timeout is not None else self.timeout)
        if request_timeout <= 0:
            raise ValueError("timeout must be positive")

        endpoint_key = f"{effective_provider}:{base_url_host}"
        profile_key = _profile_cache_key(effective_provider, effective_base_url, model)
        profile = self._get_profile(profile_key)

        ai_runtime_guard.validate_prompt(prompt_chars)
        if not connection_probe:
            await ai_runtime_guard.enforce_rate_limit()
            ai_runtime_guard.record_request()

        # Cap either token-field dialect, including explicit extra_body values.
        explicit = dict(extra_body or {})
        requested_output_tokens = explicit.get(
            "max_completion_tokens",
            explicit.get("max_tokens", max_tokens),
        )
        effective_max_tokens = ai_runtime_guard.bounded_max_tokens(
            requested_output_tokens
        )
        if "max_completion_tokens" in explicit and effective_max_tokens is not None:
            explicit["max_completion_tokens"] = effective_max_tokens
        if "max_tokens" in explicit and effective_max_tokens is not None:
            explicit["max_tokens"] = effective_max_tokens

        temperature_requested = (
            temperature is not None and "temperature" not in explicit
        )
        response_format_requested = (
            response_format is not None and "response_format" not in explicit
        )
        token_limit_requested = effective_max_tokens is not None and not any(
            key in explicit for key in ("max_tokens", "max_completion_tokens")
        )

        log_event(
            _ai_logger,
            "ai.chat.start",
            provider=effective_provider,
            model=model,
            base_url_host=base_url_host,
            temperature=temperature,
            message_count=len(messages),
            prompt_chars=prompt_chars,
            max_tokens=effective_max_tokens,
            direct_answer=prefer_direct_answer,
            compatibility_profile=_profile_label(
                profile, direct_answer=prefer_direct_answer
            ),
            connection_probe=connection_probe,
        )

        with start_span(op="ai.openai_compatible.chat", description=f"model={model}"):
            set_tag("ai.model", model)
            set_tag("ai.provider", effective_provider)

            start = time.time()
            provider_outcome_recorded = False
            compatibility_retries = 0
            attempted_profiles: set[_CompatibilityProfile] = set()
            try:
                url = build_chat_completions_url(effective_base_url)
                sem = None
                queue_wait_ms = 0.0
                if not connection_probe:
                    sem, queue_wait_ms = await ai_runtime_guard.acquire_slot()
                try:
                    if not connection_probe:
                        ai_runtime_guard.assert_circuit_available(endpoint_key)
                    # ``timeout`` is a budget for the logical chat call, not for
                    # each compatibility retry individually. Parameter-rejection
                    # negotiation therefore shares one monotonic deadline.
                    request_deadline = time.monotonic() + request_timeout
                    while True:
                        if profile in attempted_profiles:
                            raise RuntimeError(
                                "OpenAI-compatible compatibility negotiation loop"
                            )
                        attempted_profiles.add(profile)

                        payload = self._build_payload(
                            messages=messages,
                            model=model,
                            temperature=temperature,
                            response_format=response_format,
                            extra_body=explicit,
                            effective_max_tokens=effective_max_tokens,
                            prefer_direct_answer=prefer_direct_answer,
                            profile=profile,
                        )
                        request_body = json.dumps(
                            payload,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ).encode("utf-8")
                        remaining_timeout = request_deadline - time.monotonic()
                        if remaining_timeout <= 0:
                            raise TimeoutError(
                                "OpenAI-compatible request budget exhausted"
                            )
                        remote = await asyncio.to_thread(
                            request_remote_bytes,
                            url,
                            method="POST",
                            body=request_body,
                            max_bytes=10 * 1024 * 1024,
                            timeout=max(0.05, remaining_timeout),
                            allow_http=settings.AI_ALLOW_HTTP_BASE_URLS,
                            follow_redirects=False,
                            headers={
                                **get_trace_headers(),
                                "Authorization": f"Bearer {effective_key}",
                                "Content-Type": "application/json",
                                "Accept": "application/json",
                            },
                        )
                        response_text = remote.data.decode("utf-8", errors="replace")

                        if 200 <= remote.status < 300:
                            break

                        generic_rejection = _looks_like_parameter_rejection(
                            remote.status, response_text
                        )
                        rejected_field = _rejected_optional_field(response_text)
                        next_profile = self._adapt_profile(
                            profile,
                            rejected_field=rejected_field,
                            prefer_direct_answer=prefer_direct_answer,
                            temperature_requested=temperature_requested,
                            response_format_requested=response_format_requested,
                            token_limit_requested=token_limit_requested,
                            generic_parameter_rejection=generic_rejection,
                        )
                        # Retry only deterministic optional-parameter incompatibility
                        # responses. Auth/rate/model/content errors still surface on
                        # the first response and are never replayed here.
                        if (
                            next_profile is not None
                            and remote.status in {400, 422}
                            and (rejected_field is not None or generic_rejection)
                            and len(attempted_profiles) < _MAX_COMPATIBILITY_ATTEMPTS
                        ):
                            compatibility_retries += 1
                            log_event(
                                _ai_logger,
                                "ai.chat.compat_retry",
                                provider=effective_provider,
                                model=model,
                                status_code=remote.status,
                                rejected_field=rejected_field or "unknown_optional",
                                attempt=compatibility_retries + 1,
                                compatibility_profile=_profile_label(
                                    next_profile, direct_answer=prefer_direct_answer
                                ),
                            )
                            profile = next_profile
                            continue

                        elapsed = int((time.time() - start) * 1000)
                        retryable_status = (
                            remote.status == 429
                            or remote.status == 408
                            or remote.status >= 500
                        )
                        if not connection_probe:
                            ai_runtime_guard.record_provider_failure(
                                endpoint_key, retryable=retryable_status
                            )
                            ai_runtime_guard.record_failure()
                        provider_outcome_recorded = True
                        log_event(
                            _ai_logger,
                            "ai.chat.error",
                            level="error" if retryable_status else "warning",
                            provider=effective_provider,
                            model=model,
                            duration_ms=elapsed,
                            status_code=remote.status,
                            error_type="HTTPError",
                            compatibility_retries=compatibility_retries,
                        )
                        raise OpenAICompatibleAPIError(
                            remote.status,
                            retryable=retryable_status,
                            error_kind=_classify_http_error_kind(
                                remote.status, response_text
                            ),
                        )
                finally:
                    if sem is not None:
                        ai_runtime_guard.release_slot(sem)

                elapsed = int((time.time() - start) * 1000)
                data = json.loads(response_text)
                choices = data.get("choices")
                if not isinstance(choices, list) or not choices:
                    raise RuntimeError(
                        "OpenAI-compatible API response missing choices[0]"
                    )
                choice = choices[0]
                if not isinstance(choice, dict):
                    raise RuntimeError(
                        "OpenAI-compatible API response has invalid choice format"
                    )
                message = choice.get("message")
                if isinstance(message, dict):
                    content = _normalise_message_content(message.get("content"))
                else:
                    # A few lightweight relays still return the legacy
                    # ``choices[0].text`` shape from a chat endpoint. Accept the
                    # text without changing the request protocol.
                    content = _normalise_message_content(choice.get("text"))
                    if not content:
                        raise RuntimeError(
                            "OpenAI-compatible API response missing choice.message"
                        )
                tokens = _tokens_used(data)
                response_chars = len(content)
                self._remember_profile(profile_key, profile)
                compatibility_profile = _profile_label(
                    profile, direct_answer=prefer_direct_answer
                )

                set_tag("ai.tokens", tokens)
                set_tag("ai.duration_ms", elapsed)
                if not connection_probe:
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
                    compatibility_retries=compatibility_retries,
                    compatibility_profile=compatibility_profile,
                )

                return {
                    "content": content,
                    "tokens_used": tokens,
                    "model": data.get("model") or model,
                    "provider": effective_provider,
                    "duration_ms": elapsed,
                    "finish_reason": choice.get("finish_reason"),
                    "compatibility_retries": compatibility_retries,
                    "compatibility_profile": compatibility_profile,
                }
            except AIResourceRejectedError as exc:
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
                    if not connection_probe:
                        ai_runtime_guard.record_provider_failure(
                            endpoint_key, retryable=True
                        )
                        ai_runtime_guard.record_failure()
                    provider_outcome_recorded = True
                if not isinstance(exc, OpenAICompatibleAPIError):
                    log_event(
                        _ai_logger,
                        "ai.chat.error",
                        level="error",
                        provider=effective_provider,
                        model=model,
                        duration_ms=int((time.time() - start) * 1000),
                        error_type=type(exc).__name__,
                        error_message=str(exc)[:300],
                        compatibility_retries=compatibility_retries,
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
