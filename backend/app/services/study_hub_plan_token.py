"""Signed attribution token for Home "today plan" practice entries.

The Home page may preselect a recommended practice scope, but the user is still
allowed to edit the configuration before starting.  Attribution is therefore
accepted only when the issued plan token still matches the actual practice
request.  A mismatch never blocks practice; it simply disables recommendation
completion analytics for that batch.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from app.core.config import settings

_PLAN_TOKEN_VERSION = 1
_PLAN_TOKEN_TTL_SEC = 60 * 60 * 48
_PLAN_SOURCE = "home_today_plan"


def _urlsafe_b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _urlsafe_b64decode(text_value: str) -> bytes:
    padding = "=" * (-len(text_value) % 4)
    return base64.urlsafe_b64decode((text_value + padding).encode("ascii"))


def _signing_key() -> bytes:
    return hmac.new(
        settings.APP_SECRET.encode("utf-8"),
        b"memograd:study-hub-plan:v1",
        hashlib.sha256,
    ).digest()


def _question_ids_digest(question_ids: str | None) -> str:
    raw = ",".join(
        part.strip()
        for part in str(question_ids or "").split(",")
        if part.strip()
    )
    if not raw:
        return ""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def issue_plan_task_token(
    *,
    user_id: int,
    plan_date: str,
    task_key: str,
    subject_id: int,
    mode: str,
    count: int,
    knowledge_point_id: int | None = None,
    include_descendants: bool = False,
    question_ids: str | None = None,
) -> str:
    now = int(time.time())
    payload = {
        "v": _PLAN_TOKEN_VERSION,
        "uid": int(user_id),
        "source": _PLAN_SOURCE,
        "date": str(plan_date),
        "key": str(task_key)[:128],
        "sid": int(subject_id),
        "mode": str(mode),
        "count": int(count),
        "kp": int(knowledge_point_id) if knowledge_point_id else None,
        "desc": bool(include_descendants),
        "qids": _question_ids_digest(question_ids),
        "iat": now,
        "exp": now + _PLAN_TOKEN_TTL_SEC,
    }
    body = _urlsafe_b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    signature = _urlsafe_b64encode(
        hmac.new(_signing_key(), body.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{body}.{signature}"


def _decode_plan_task_token(token: str) -> dict[str, Any] | None:
    try:
        body, signature = str(token or "").split(".", 1)
        expected = _urlsafe_b64encode(
            hmac.new(_signing_key(), body.encode("ascii"), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(_urlsafe_b64decode(body).decode("utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict) or int(payload.get("v") or 0) != _PLAN_TOKEN_VERSION:
        return None
    now = int(time.time())
    if int(payload.get("exp") or 0) < now or int(payload.get("iat") or 0) > now + 300:
        return None
    if str(payload.get("source") or "") != _PLAN_SOURCE:
        return None
    return payload


def validate_plan_task_token(
    token: str | None,
    *,
    user_id: int,
    subject_id: int,
    mode: str,
    count: int,
    knowledge_point_id: int | None = None,
    include_descendants: bool = False,
    question_ids: str | None = None,
) -> dict[str, Any] | None:
    """Return trusted plan attribution iff token and actual request still match."""
    payload = _decode_plan_task_token(str(token or ""))
    if payload is None:
        return None
    if int(payload.get("uid") or 0) != int(user_id):
        return None
    if int(payload.get("sid") or 0) != int(subject_id):
        return None
    if str(payload.get("mode") or "") != str(mode):
        return None
    if int(payload.get("count") or 0) != int(count):
        return None
    signed_kp = int(payload.get("kp") or 0)
    actual_kp = int(knowledge_point_id or 0)
    if signed_kp != actual_kp:
        return None
    if bool(payload.get("desc")) != bool(include_descendants):
        return None
    if str(payload.get("qids") or "") != _question_ids_digest(question_ids):
        return None
    return {
        "v": _PLAN_TOKEN_VERSION,
        "source": _PLAN_SOURCE,
        "plan_date": str(payload.get("date") or ""),
        "task_key": str(payload.get("key") or "")[:128],
    }
