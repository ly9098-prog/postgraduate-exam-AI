from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger("postgraduate-ai.debug")

SENSITIVE_KEYS = {"token", "authorization", "secret", "password", "openid"}
MAX_STRING_LENGTH = 500
MAX_LIST_ITEMS = 20
MAX_DICT_ITEMS = 40
MAX_DEPTH = 4
MAX_JSON_LENGTH = 20000


def _is_sensitive_key(key: Any) -> bool:
    lowered = str(key).lower()
    return any(word in lowered for word in SENSITIVE_KEYS)


def _sanitize_debug_value(value: Any, depth: int = 0) -> Any:
    if depth >= MAX_DEPTH:
        return "[truncated:depth]"
    if isinstance(value, dict):
        sanitized = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_DICT_ITEMS:
                sanitized["_truncated_keys"] = len(value) - MAX_DICT_ITEMS
                break
            if _is_sensitive_key(key):
                sanitized[str(key)] = "[redacted]"
            else:
                sanitized[str(key)] = _sanitize_debug_value(item, depth + 1)
        return sanitized
    if isinstance(value, (list, tuple)):
        items = [
            _sanitize_debug_value(item, depth + 1) for item in value[:MAX_LIST_ITEMS]
        ]
        if len(value) > MAX_LIST_ITEMS:
            items.append({"_truncated_items": len(value) - MAX_LIST_ITEMS})
        return items
    if isinstance(value, str):
        if len(value) > MAX_STRING_LENGTH:
            return (
                value[:MAX_STRING_LENGTH]
                + f"...[truncated:{len(value) - MAX_STRING_LENGTH}]"
            )
        return value
    return value


def _safe_debug_payload(payload: dict) -> str:
    text = json.dumps(payload, ensure_ascii=False, default=str, indent=2)
    if len(text) <= MAX_JSON_LENGTH:
        return text
    payload = dict(payload)
    payload["data"] = {
        "_truncated": True,
        "summary": _sanitize_debug_value(payload.get("data"), 1),
    }
    text = json.dumps(payload, ensure_ascii=False, default=str, indent=2)
    if len(text) > MAX_JSON_LENGTH:
        text = text[:MAX_JSON_LENGTH] + "\n...[truncated]"
    return text


def create_trace_id() -> str:
    return f"TRACE_{datetime.now():%Y%m%d}_{secrets.token_hex(3)}"


def debug_enabled() -> bool:
    return settings.DEBUG_MODE is True


def debug_question_id() -> int | None:
    return settings.DEBUG_QUESTION_ID


def should_debug_question(question_id: Any) -> bool:
    if not debug_enabled():
        return False
    target = debug_question_id()
    if target is None:
        return True
    return str(question_id) == str(target)


def debug_log(trace_id: str | None, stage: str, data: dict | None = None) -> None:
    if not debug_enabled():
        return
    logger.info("[TRACE:%s][%s] %s", trace_id or "NO_TRACE", stage, data or {})


def save_debug_snapshot(
    trace_id: str | None, stage: str, data: dict | None = None
) -> None:
    if not debug_enabled() or not trace_id:
        return
    snapshot_dir = (
        Path.cwd().parent / "debug_snapshots"
        if Path.cwd().name == "backend"
        else Path.cwd() / "debug_snapshots"
    )
    try:
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{trace_id}_{stage}_{datetime.now():%Y%m%d%H%M%S%f}.json"
        payload = {
            "traceId": trace_id,
            "stage": stage,
            "savedAt": datetime.now().isoformat(),
            "data": _sanitize_debug_value(data or {}),
        }
        (snapshot_dir / filename).write_text(
            _safe_debug_payload(payload),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("[TRACE:%s][SNAPSHOT_ERROR] %s", trace_id, exc)
