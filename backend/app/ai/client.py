import time

import httpx

from app.core.config import settings


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
        model: str = "deepseek-v4-flash",
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> dict:
        _api_key = api_key if api_key is not None else self._api_key
        _base_url = base_url if base_url is not None else self._base_url

        if not _api_key or _api_key == "sk-your-key-here":
            raise RuntimeError("DEEPSEEK_API_KEY 未配置")

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }

        start = time.time()
        resp = await self.client.post(
            f"{_base_url}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        elapsed = int((time.time() - start) * 1000)

        if resp.status_code != 200:
            raise RuntimeError(f"DeepSeek API error: {resp.status_code} {resp.text}")

        data = resp.json()
        choice = data["choices"][0]
        return {
            "content": choice["message"]["content"],
            "tokens_used": data["usage"]["total_tokens"],
            "model": data["model"],
            "duration_ms": elapsed,
        }

    async def close(self):
        if self._client:
            await self._client.aclose()


deepseek = DeepSeekClient()
