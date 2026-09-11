"""Unified log context — request-level trace correlation via contextvars.

Provides a per-asyncio-task context dict that is automatically merged into
every structured log event.  The HTTP middleware seeds ``trace_id`` /
``request_id``; auth dependencies layer on ``user_id`` / ``admin_id``;
background tasks re-bind from explicit ``options["_trace_id"]`` propagation.

Usage::

    from app.core.log_context import bind_log_context, log_event, get_log_context

    bind_log_context(trace_id="tr_abc123", request_id="req_def456")
    log_event(logger, "http.request.start", method="GET", path="/health")

    ctx = get_log_context()          # {"trace_id": "tr_abc123", ...}
"""

from __future__ import annotations

import contextvars
import hashlib
import logging
import re
import uuid
from typing import Any

# ---------------------------------------------------------------------------
# Context storage
# ---------------------------------------------------------------------------

_CONTEXT_FIELDS = (
    "trace_id",
    "request_id",
    "user_id",
    "admin_id",
    "pipeline_id",
    "job_id",
    "batch_id",
    "chunk_index",
    "stage",
    "source_type",
    "source_file",
)

_log_context_var: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "log_context", default={}
)


# ---------------------------------------------------------------------------
# ID generators
# ---------------------------------------------------------------------------


def generate_trace_id(prefix: str = "tr") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def generate_request_id(prefix: str = "req") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


_CORRELATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_TRACEPARENT_RE = re.compile(
    r"^[0-9a-fA-F]{2}-([0-9a-fA-F]{32})-([0-9a-fA-F]{16})-[0-9a-fA-F]{2}$"
)


def normalize_trace_id(value: str | None, traceparent: str | None = None) -> str:
    """Accept a safe client trace ID or derive one from W3C traceparent.

    Invalid/unbounded header values are never copied into logs.
    """
    candidate = (value or "").strip()
    if candidate and _CORRELATION_ID_RE.fullmatch(candidate):
        return candidate

    parent = (traceparent or "").strip()
    match = _TRACEPARENT_RE.fullmatch(parent)
    if match and match.group(1) != "0" * 32:
        return f"tr_{match.group(1).lower()}"

    return generate_trace_id()


def normalize_request_id(value: str | None) -> str:
    """Accept a safe client request ID or generate a new one."""
    candidate = (value or "").strip()
    if candidate and _CORRELATION_ID_RE.fullmatch(candidate):
        return candidate
    return generate_request_id()


def get_trace_headers() -> dict[str, str]:
    """Return correlation headers for outbound HTTP calls.

    Empty context produces no headers, so scheduled/health traffic is unchanged.
    """
    ctx = get_log_context()
    headers: dict[str, str] = {}
    trace_id = ctx.get("trace_id")
    request_id = ctx.get("request_id")
    if isinstance(trace_id, str) and trace_id and trace_id != "-":
        headers["X-Trace-ID"] = trace_id
    if isinstance(request_id, str) and request_id and request_id != "-":
        headers["X-Request-ID"] = request_id
    return headers


# ---------------------------------------------------------------------------
# Context manipulation
# ---------------------------------------------------------------------------


def bind_log_context(**kwargs: Any) -> list[contextvars.Token]:
    """Merge *kwargs* into the current log context.

    Only keys present in ``_CONTEXT_FIELDS`` are stored; unknown keys are
    silently ignored to prevent accidental leakage of sensitive data into
    log records.

    Returns a list of ``contextvars.Token`` objects (one per key) so the
    caller can selectively reset with :func:`reset_log_context`.
    """
    current = dict(_log_context_var.get())
    tokens: list[contextvars.Token] = []
    for key in _CONTEXT_FIELDS:
        if key in kwargs:
            current[key] = kwargs[key]
    token = _log_context_var.set(current)
    tokens.append(token)
    try:
        sync_sentry_tags()
    except Exception:
        pass
    return tokens


def reset_log_context(tokens: list[contextvars.Token]) -> None:
    """Reset context using tokens returned by :func:`bind_log_context`."""
    for token in reversed(tokens):
        _log_context_var.reset(token)
    try:
        sync_sentry_tags()
    except Exception:
        pass


def get_log_context() -> dict[str, Any]:
    """Return a *copy* of the current log context dict."""
    return dict(_log_context_var.get())


def clear_log_context() -> None:
    """Reset the log context to an empty dict."""
    _log_context_var.set({})
    try:
        sync_sentry_tags()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Sanitisation & truncation
# ---------------------------------------------------------------------------

SENSITIVE_KEYS: set[str] = {
    "authorization",
    "token",
    "access_token",
    "refresh_token",
    "password",
    "password_hash",
    "secret",
    "api_key",
    "apikey",
    "openid",
    "wechat_code",
}

_MAX_STRING_LENGTH = 500
_MAX_LIST_ITEMS = 20
_MAX_DICT_ITEMS = 40
_MAX_DEPTH = 4


def _is_sensitive(key: Any) -> bool:
    lowered = str(key).lower()
    return any(word in lowered for word in SENSITIVE_KEYS)


def _sanitize_value(value: Any, depth: int = 0) -> Any:
    """Recursively sanitize and truncate a value for safe logging."""
    if depth >= _MAX_DEPTH:
        return "[truncated:depth]"

    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for idx, (k, v) in enumerate(value.items()):
            if idx >= _MAX_DICT_ITEMS:
                sanitized["_truncated_keys"] = len(value) - _MAX_DICT_ITEMS
                break
            if _is_sensitive(k):
                sanitized[str(k)] = "[redacted]"
            else:
                sanitized[str(k)] = _sanitize_value(v, depth + 1)
        return sanitized

    if isinstance(value, (list, tuple)):
        items = [_sanitize_value(item, depth + 1) for item in value[:_MAX_LIST_ITEMS]]
        if len(value) > _MAX_LIST_ITEMS:
            items.append({"_truncated_items": len(value) - _MAX_LIST_ITEMS})
        return items

    if isinstance(value, str):
        if len(value) > _MAX_STRING_LENGTH:
            return (
                value[:_MAX_STRING_LENGTH]
                + f"...[truncated:{len(value) - _MAX_STRING_LENGTH}]"
            )
        return value

    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"

    return value


def sanitize_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Sanitize a flat-ish dict of fields for safe inclusion in log extra."""
    return {
        k: "[redacted]" if _is_sensitive(k) else _sanitize_value(v)
        for k, v in fields.items()
    }


# ---------------------------------------------------------------------------
# OCR / document text safe-preview for logging
# ---------------------------------------------------------------------------

_TEXT_PREVIEW_MAX = 80  # maximum characters shown in log output


def safe_text_preview(text: str | None, max_len: int = _TEXT_PREVIEW_MAX) -> str:
    """Return a compact, non-sensitive summary of text for logging.

    Format: ``sha256:{hex12} len=N cjk=N preview:"..."``
    The preview portion is capped at *max_len* characters and should only
    be used to distinguish obviously different texts, never as a source of
    actual content.
    """
    if not text:
        return "<empty>"
    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    cjk = sum(1 for c in text if "一" <= c <= "鿿")
    total = len(text)
    preview = text[:max_len].replace("\n", "\\n").replace("\r", "\\r")
    return f'sha256:{text_hash} len={total} cjk={cjk} preview:"{preview}"'


# ---------------------------------------------------------------------------
# Structured log event helper
# ---------------------------------------------------------------------------


def log_event(
    logger: logging.Logger,
    event: str,
    level: str = "info",
    **fields: Any,
) -> None:
    """Emit a structured log event with automatic context merge.

    *event* is placed into ``record.event``.  All current log-context fields
    are merged into ``record.__dict__`` so the formatter can reference them.
    Extra *fields* are sanitized and truncated before being attached.

    Args:
        logger: the ``logging.Logger`` instance to use.
        event: dot-separated event name (e.g. ``"http.request.start"``).
        level: one of ``debug``, ``info``, ``warning``, ``error``, ``exception``.
        **fields: additional key-value pairs, sanitized before logging.
    """
    try:
        ctx = get_log_context()
        safe_fields = sanitize_fields(fields)

        # Build the extra dict — context fields + event + sanitized user fields
        extra: dict[str, Any] = {}
        for key in _CONTEXT_FIELDS:
            extra[key] = ctx.get(key, "-")
        extra["event"] = event

        # Merge user-supplied fields (non-context keys only)
        for k, v in safe_fields.items():
            if k not in _CONTEXT_FIELDS and k != "event":
                extra[k] = v

        # Build human-readable message from event + key fields
        msg = event
        if safe_fields:
            parts = [f"{k}={v}" for k, v in list(safe_fields.items())[:8]]
            msg = f"{event} {' '.join(parts)}"

        log_fn = getattr(logger, level, logger.info)
        try:
            log_fn(msg, extra=extra)
        except Exception:
            # Fallback: if extra keys clash with LogRecord attributes, log bare
            try:
                log_fn(msg)
            except Exception:
                pass  # Never let logging failure crash the application
    except Exception:
        # Outer guard: sanitize_fields or other logic failed — never crash caller
        pass


# ---------------------------------------------------------------------------
# Sentry context sync (best-effort)
# ---------------------------------------------------------------------------


def sync_sentry_tags() -> None:
    """Push current log context as Sentry tags (best-effort, no-op if Sentry unavailable)."""
    try:
        from app.utils.sentry_utils import set_tag
    except ImportError:
        return
    try:
        ctx = get_log_context()
        for key in _CONTEXT_FIELDS:
            value = ctx.get(key)
            set_tag(f"log.{key}", value if value not in (None, "") else "-")
    except Exception:
        pass  # Never let Sentry sync crash the application
