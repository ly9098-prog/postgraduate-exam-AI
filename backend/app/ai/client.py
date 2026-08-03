import asyncio
import json
import logging
import threading
import time
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.core.log_context import log_event
from app.services.safe_remote_fetch import request_remote_bytes
from app.utils.sentry_utils import capture_exception, set_tag, start_span

_ai_logger = logging.getLogger("app.ai")

# DeepSeek 调用并发上限：裸 asyncio.to_thread 走默认线程池（2 核 ≈6 线程），
# 多并发 AI 调用（批量导入修复/错题分析）可占满该池并拖垮同一池上其它
# to_thread 工作（staging 文件复制、OCR base64 编码等）。按事件循环键控：
# 生产单 loop 即进程级限流；测试多 loop 各自限流，避免跨 loop 绑定错误。
_AI_MAX_CONCURRENT = 3
_ai_sem_lock = threading.Lock()
# 值存 (loop, semaphore)：持有 loop 强引用可防止 id(loop) 复用误取已关闭
# loop 的信号量；已关闭 loop 的条目在下次调用时清理，避免多 loop 环境（测试）
# 下 dict 与钉死的 loop 无界累积。
_ai_sems: dict[int, tuple[asyncio.AbstractEventLoop, asyncio.Semaphore]] = {}


def _ai_call_semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    key = id(loop)
    with _ai_sem_lock:
        _sweep_closed_ai_sems()
        entry = _ai_sems.get(key)
        if entry is None:
            sem = asyncio.Semaphore(_AI_MAX_CONCURRENT)
            _ai_sems[key] = (loop, sem)
            entry = (loop, sem)
    return entry[1]


def _sweep_closed_ai_sems() -> None:
    """清理已关闭事件循环的残留信号量条目（须持有 _ai_sem_lock 时调用）。"""
    for k in [k for k, (l, _) in _ai_sems.items() if l.is_closed()]:
        del _ai_sems[k]


class DeepSeekClient:
    def __init__(self):
        self._api_key = ""  # managed via admin_ai_model_configs
        self._base_url = ""  # managed per-model in admin_ai_model_configs
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
        return bool(self._api_key)

    async def chat(
        self,
        messages: list,
        temperature: float = 0.3,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> dict:
        _api_key = api_key if api_key is not None else self._api_key
        _base_url = base_url if base_url is not None else self._base_url

        if not _api_key:
            raise RuntimeError("AI模型API Key未配置，请先在后台AI设置页面配置模型API Key")

        # 兜底：显式传 None 不会覆盖默认值，确保 payload["model"] 永远是字符串
        model = model or "deepseek-v4-flash"

        # Extract host only — never log full URL (may contain tokens)
        try:
            base_url_host = urlparse(_base_url).hostname or "-"
        except Exception:
            base_url_host = "-"

        # Estimate prompt size without logging content
        prompt_chars = sum(len(str(m.get("content", ""))) for m in messages)

        request_timeout = float(timeout if timeout is not None else self.timeout)
        if request_timeout <= 0:
            raise ValueError("timeout must be positive")

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
                sem = _ai_call_semaphore()
                async with sem:
                    remote = await asyncio.to_thread(
                        request_remote_bytes,
                        f"{_url}/v1/chat/completions",
                        method="POST",
                        body=request_body,
                        max_bytes=10 * 1024 * 1024,
                        timeout=request_timeout,
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
                if elapsed >= request_timeout * 1000:
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
