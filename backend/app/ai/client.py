import asyncio
import json
import logging
import time
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.core.log_context import log_event
from app.services.safe_remote_fetch import request_remote_bytes
from app.utils.sentry_utils import capture_exception, set_tag, start_span

_ai_logger = logging.getLogger("app.ai")


class DeepSeekClient:
    def __init__(self):
        self._api_key = settings.DEEPSEEK_API_KEY
        self._base_url = settings.DEEPSEEK_BASE_URL
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
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    def is_available(self) -> bool:
        return bool(self._api_key) and self._api_key != "sk-your-key-here"

    async def chat(
        self,
        messages: list,
        temperature: float = 0.3,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> dict:
        _api_key = api_key if api_key is not None else self._api_key
        _base_url = base_url if base_url is not None else self._base_url

        if not _api_key or _api_key == "sk-your-key-here":
            raise RuntimeError("DEEPSEEK_API_KEY 未配置")

        # 兜底：显式传 None 不会覆盖默认值，确保 payload["model"] 永远是字符串
        model = model or getattr(settings, "DEEPSEEK_MODEL", None) or "deepseek-v4-flash"

        # Extract host only — never log full URL (may contain tokens)
        try:
            base_url_host = urlparse(_base_url).hostname or "-"
        except Exception:
            base_url_host = "-"

        # Estimate prompt size without logging content
        prompt_chars = sum(len(str(m.get("content", ""))) for m in messages)

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }

        log_event(
            _ai_logger, "ai.chat.start",
            provider="deepseek", model=model,
            base_url_host=base_url_host,
            temperature=temperature,
            message_count=len(messages),
            prompt_chars=prompt_chars,
        )

        with start_span(op="ai.deepseek.chat", description=f"model={model}"):
            set_tag("ai.model", model)
            set_tag("ai.provider", "deepseek")

            start = time.time()
            try:
                _url = _base_url.rstrip("/")
                if _url.endswith("/v1"):
                    _url = _url[:-3]
                request_body = json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                remote = await asyncio.to_thread(
                    request_remote_bytes,
                    f"{_url}/v1/chat/completions",
                    method="POST",
                    body=request_body,
                    max_bytes=10 * 1024 * 1024,
                    timeout=float(self.timeout),
                    allow_http=settings.AI_ALLOW_HTTP_BASE_URLS,
                    follow_redirects=False,
                    headers={
                        "Authorization": f"Bearer {_api_key}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                )
                response_text = remote.data.decode("utf-8", errors="replace")
                elapsed = int((time.time() - start) * 1000)

                if remote.status != 200:
                    # Truncate error body — never log full response
                    error_body = response_text[:300]
                    log_event(
                        _ai_logger, "ai.chat.error",
                        level="error",
                        provider="deepseek", model=model,
                        duration_ms=elapsed,
                        status_code=remote.status,
                        error_type="HTTPError",
                        error_message=error_body,
                    )
                    raise RuntimeError(
                        f"DeepSeek API error: {remote.status} {error_body}"
                    )

                data = json.loads(response_text)
                choice = data["choices"][0]
                tokens = data["usage"]["total_tokens"]
                response_chars = len(choice["message"].get("content", ""))

                set_tag("ai.tokens", tokens)
                set_tag("ai.duration_ms", elapsed)
                if elapsed >= self.timeout * 1000:
                    set_tag("ai.timeout", True)

                log_event(
                    _ai_logger, "ai.chat.finish",
                    provider="deepseek", model=model,
                    duration_ms=elapsed,
                    tokens_used=tokens,
                    response_chars=response_chars,
                )

                return {
                    "content": choice["message"]["content"],
                    "tokens_used": tokens,
                    "model": data["model"],
                    "duration_ms": elapsed,
                }
            except Exception as exc:
                # Only log if not already logged above (HTTP error path)
                if not isinstance(exc, RuntimeError) or "DeepSeek API error" not in str(exc):
                    log_event(
                        _ai_logger, "ai.chat.error",
                        level="error",
                        provider="deepseek", model=model,
                        duration_ms=int((time.time() - start) * 1000),
                        error_type=type(exc).__name__,
                        error_message=str(exc)[:300],
                    )
                capture_exception(
                    exc,
                    tags={"ai.model": model, "ai.provider": "deepseek"},
                )
                raise

    async def close(self):
        if self._client:
            await self._client.aclose()


deepseek = DeepSeekClient()
