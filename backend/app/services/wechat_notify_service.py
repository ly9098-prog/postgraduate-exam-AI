"""微信订阅消息通道。

职责：
- 缓存 access_token（Redis 优先，进程内变量兜底）
- 发送订阅消息（subscribeMessage.send）
- 处理 access_token 失效（40001）：强刷一次

不做任何业务判断，只负责"发出去"。
失败由调用方记录到 pomodoro_sessions.notification_error。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from app.core.cache import cache
from app.core.config import settings

logger = logging.getLogger("2240ai.wechat_notify")

ACCESS_TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token"
SUBSCRIBE_SEND_URL = "https://api.weixin.qq.com/cgi-bin/message/subscribe/send"

_TOKEN_CACHE_KEY = "wechat:access_token"
_TOKEN_LOCK_KEY = "wechat:access_token:lock"
_TOKEN_REFRESH_SAFETY_SEC = 600  # 提前 10 分钟过期

# 进程内兜底（Redis 不可用时使用）
_local_token: dict[str, Any] = {"value": None, "expires_at": 0}
_local_lock = asyncio.Lock()


class WeChatNotifyError(Exception):
    """微信接口业务错误。"""

    def __init__(self, errcode: int, errmsg: str):
        self.errcode = errcode
        self.errmsg = errmsg
        super().__init__(f"wechat errcode={errcode} errmsg={errmsg}")


async def _fetch_access_token(client: httpx.AsyncClient) -> tuple[str, int]:
    if not settings.WECHAT_APP_ID or not settings.WECHAT_APP_SECRET:
        raise WeChatNotifyError(-1, "WECHAT_APP_ID/SECRET not configured")
    resp = await client.get(
        ACCESS_TOKEN_URL,
        params={
            "grant_type": "client_credential",
            "appid": settings.WECHAT_APP_ID,
            "secret": settings.WECHAT_APP_SECRET,
        },
        timeout=10.0,
    )
    data = resp.json()
    if "access_token" not in data:
        raise WeChatNotifyError(int(data.get("errcode", -1)), str(data.get("errmsg", "no token")))
    token = data["access_token"]
    expires_in = int(data.get("expires_in", 7200))
    return token, expires_in


async def get_access_token(force_refresh: bool = False) -> str:
    """优先 Redis，回退进程内变量。"""
    now = int(time.time())

    if not force_refresh:
        cached = await cache.get(_TOKEN_CACHE_KEY)
        if isinstance(cached, dict):
            token = cached.get("value")
            expires_at = int(cached.get("expires_at", 0))
            if token and expires_at - now > 30:
                return token
        if _local_token["value"] and _local_token["expires_at"] - now > 30:
            return _local_token["value"]

    # 加锁防雪崩
    lock_value = f"{now}-{id(asyncio.current_task())}"
    got_redis_lock = await cache.acquire_lock(_TOKEN_LOCK_KEY, lock_value, ttl=15)

    try:
        # 双检
        if not force_refresh:
            cached = await cache.get(_TOKEN_CACHE_KEY)
            if isinstance(cached, dict):
                token = cached.get("value")
                expires_at = int(cached.get("expires_at", 0))
                if token and expires_at - now > 30:
                    return token

        async with _local_lock:
            if not force_refresh and _local_token["value"] and _local_token["expires_at"] - now > 30:
                return _local_token["value"]

            async with httpx.AsyncClient() as client:
                token, expires_in = await _fetch_access_token(client)
            ttl = max(60, expires_in - _TOKEN_REFRESH_SAFETY_SEC)
            expires_at = now + ttl

            _local_token["value"] = token
            _local_token["expires_at"] = expires_at
            await cache.set(_TOKEN_CACHE_KEY, {"value": token, "expires_at": expires_at}, ttl=ttl)
            logger.info("微信 access_token 已刷新, ttl=%ds", ttl)
            return token
    finally:
        if got_redis_lock:
            await cache.release_lock(_TOKEN_LOCK_KEY, lock_value)


async def send_subscribe_message(
    *,
    openid: str,
    template_id: str,
    data: dict[str, dict[str, str]],
    page: str | None = None,
    miniprogram_state: str | None = None,
    lang: str = "zh_CN",
) -> dict[str, Any]:
    """发送订阅消息。

    成功返回微信原始 JSON；失败抛 WeChatNotifyError。
    """
    if not template_id:
        raise WeChatNotifyError(-2, "template_id is empty")
    if not openid:
        raise WeChatNotifyError(-3, "openid is empty")

    payload: dict[str, Any] = {
        "touser": openid,
        "template_id": template_id,
        "data": data,
        "lang": lang,
    }
    if page:
        payload["page"] = page
    if miniprogram_state:
        payload["miniprogram_state"] = miniprogram_state

    async def _do_send(token: str) -> dict[str, Any]:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                SUBSCRIBE_SEND_URL,
                params={"access_token": token},
                json=payload,
                timeout=10.0,
            )
            return resp.json()

    token = await get_access_token()
    result = await _do_send(token)
    errcode = int(result.get("errcode", 0))

    # access_token 失效 → 强刷一次
    if errcode in (40001, 40014, 42001):
        token = await get_access_token(force_refresh=True)
        result = await _do_send(token)
        errcode = int(result.get("errcode", 0))

    if errcode != 0:
        raise WeChatNotifyError(errcode, str(result.get("errmsg", "unknown")))

    return result
