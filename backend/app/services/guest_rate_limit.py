import hashlib

from fastapi import HTTPException, Request

from app.core.cache import CacheUnavailableError, cache

GUEST_REQUEST_WINDOW_SECONDS = 60
GUEST_REQUEST_LIMIT = 120


async def require_guest_request_budget(request: Request) -> None:
    client_ip = request.client.host if request.client else "unknown"
    digest = hashlib.sha256(client_ip.encode("utf-8")).hexdigest()
    key = f"guest:practice:requests:{digest}"
    try:
        count = await cache.increment_strict(key, ttl=GUEST_REQUEST_WINDOW_SECONDS)
    except CacheUnavailableError as exc:
        raise HTTPException(
            status_code=503, detail="体验服务暂时不可用，请稍后重试",
        ) from exc
    if count > GUEST_REQUEST_LIMIT:
        raise HTTPException(
            status_code=429, detail="体验请求过于频繁，请稍后重试",
            headers={"Retry-After": str(GUEST_REQUEST_WINDOW_SECONDS)},
        )
