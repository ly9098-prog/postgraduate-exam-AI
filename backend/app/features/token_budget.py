"""Shared token budget tracker — used by both ocr_correction and ai_repair.

Provides a single module-level counter with asyncio.Lock for concurrency safety.
"""

import asyncio
import logging
import re
import time

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()

_token_usage: dict[str, int | str] = {
    "daily": 0, "monthly": 0, "daily_date": "", "monthly_month": "",
}


def estimate_tokens(text: str) -> int:
    chinese = len(re.findall(r"[一-鿿]", text))
    return int(chinese * 1.3 + (len(text) - chinese) * 0.3)


def _reset_counters_if_needed():
    today = time.strftime("%Y-%m-%d")
    month = time.strftime("%Y-%m")
    if _token_usage["daily_date"] != today:
        _token_usage["daily"] = 0
        _token_usage["daily_date"] = today
    if _token_usage["monthly_month"] != month:
        _token_usage["monthly"] = 0
        _token_usage["monthly_month"] = month


async def check_token_limit(estimated_tokens: int, config: dict) -> bool:
    async with _lock:
        _reset_counters_if_needed()
        daily_limit = config.get("daily_token_limit", 50000)
        monthly_limit = config.get("monthly_token_limit", 1000000)
        if int(_token_usage["daily"]) + estimated_tokens > daily_limit:
            return False
        if int(_token_usage["monthly"]) + estimated_tokens > monthly_limit:
            return False
        return True


async def record_token_usage(tokens: int):
    async with _lock:
        _reset_counters_if_needed()
        _token_usage["daily"] = int(_token_usage["daily"]) + tokens
        _token_usage["monthly"] = int(_token_usage["monthly"]) + tokens


def get_token_usage_snapshot() -> dict:
    """Return current daily/monthly total for stats reporting."""
    return {
        "daily": int(_token_usage["daily"]),
        "monthly": int(_token_usage["monthly"]),
    }
