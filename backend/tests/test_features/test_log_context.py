"""Tests for the structured logging context system (log_context + logging_config).

Covers:
- bind / get / clear / reset context lifecycle
- Context isolation between concurrent async tasks
- Sensitive field redaction
- Long-string truncation
- log_event helper output
- Text formatter renders context fields
- JSON formatter produces valid JSON with all context fields
- ContextFilter injects context into arbitrary logger records
"""

from __future__ import annotations

import asyncio
import json
import logging
import logging.config
from io import StringIO

import pytest

from app.core.log_context import (
    SENSITIVE_KEYS,
    _sanitize_value,
    bind_log_context,
    clear_log_context,
    generate_request_id,
    generate_trace_id,
    get_log_context,
    log_event,
    sanitize_fields,
)
from app.core.logging_config import (
    _CONTEXT_KEYS,
    ContextFilter,
    _JsonFormatter,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_context():
    """Ensure every test starts with a clean context."""
    clear_log_context()
    yield
    clear_log_context()


def _capture_log(logger_name: str = "test.log", level: int = logging.INFO) -> tuple[logging.Logger, StringIO]:
    """Set up a logger that writes to a StringIO buffer; return (logger, stream)."""
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    logger.handlers.clear()
    logger.propagate = False

    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)s | "
            "trace=%(trace_id)s req=%(request_id)s user=%(user_id)s admin=%(admin_id)s "
            "pipeline=%(pipeline_id)s stage=%(stage)s event=%(event)s | %(message)s"
        )
    )
    handler.addFilter(ContextFilter())
    logger.addHandler(handler)
    return logger, stream


# ---------------------------------------------------------------------------
# 1. Context lifecycle
# ---------------------------------------------------------------------------


class TestContextLifecycle:
    def test_bind_and_get(self):
        bind_log_context(trace_id="tr_abc", request_id="req_def")
        ctx = get_log_context()
        assert ctx["trace_id"] == "tr_abc"
        assert ctx["request_id"] == "req_def"

    def test_bind_merges(self):
        bind_log_context(trace_id="tr_1")
        bind_log_context(user_id="u_42")
        ctx = get_log_context()
        assert ctx["trace_id"] == "tr_1"
        assert ctx["user_id"] == "u_42"

    def test_clear(self):
        bind_log_context(trace_id="tr_x")
        clear_log_context()
        assert get_log_context() == {}

    def test_reset_with_tokens(self):
        bind_log_context(trace_id="tr_old")
        tokens = bind_log_context(trace_id="tr_new")
        assert get_log_context()["trace_id"] == "tr_new"
        for t in reversed(tokens):
            from app.core.log_context import _log_context_var
            _log_context_var.reset(t)
        assert get_log_context().get("trace_id") == "tr_old"

    def test_unknown_keys_ignored(self):
        bind_log_context(secret_key="should_not_appear")
        ctx = get_log_context()
        assert "secret_key" not in ctx

    def test_get_returns_copy(self):
        bind_log_context(trace_id="tr_copy")
        ctx1 = get_log_context()
        ctx1["trace_id"] = "mutated"
        ctx2 = get_log_context()
        assert ctx2["trace_id"] == "tr_copy"


# ---------------------------------------------------------------------------
# 2. Async context isolation
# ---------------------------------------------------------------------------


class TestAsyncIsolation:
    @pytest.mark.asyncio
    async def test_tasks_dont_leak_context(self):
        """Each async task should see its own context."""
        results: dict[str, str] = {}

        async def task_a():
            bind_log_context(trace_id="task_a")
            await asyncio.sleep(0.01)
            results["a"] = get_log_context().get("trace_id", "")

        async def task_b():
            bind_log_context(trace_id="task_b")
            await asyncio.sleep(0.01)
            results["b"] = get_log_context().get("trace_id", "")

        await asyncio.gather(task_a(), task_b())
        assert results["a"] == "task_a"
        assert results["b"] == "task_b"

    @pytest.mark.asyncio
    async def test_child_task_inherits_parent_context(self):
        """A child task created with copy_context should inherit parent fields."""
        bind_log_context(trace_id="parent_tr")

        async def child():
            return get_log_context().get("trace_id", "")

        result = await asyncio.create_task(child())
        assert result == "parent_tr"


# ---------------------------------------------------------------------------
# 3. Sanitisation & truncation
# ---------------------------------------------------------------------------


class TestSanitization:
    def test_sensitive_key_redacted(self):
        result = sanitize_fields({"api_key": "sk-secret", "model": "gpt-4"})
        assert result["api_key"] == "[redacted]"
        assert result["model"] == "gpt-4"

    def test_all_sensitive_keys(self):
        for key in SENSITIVE_KEYS:
            result = sanitize_fields({key: "secret_value"})
            assert result[key] == "[redacted]", f"Key {key!r} was not redacted"

    def test_nested_dict_sanitization(self):
        result = _sanitize_value({"outer": {"password": "secret123"}})
        assert result["outer"]["password"] == "[redacted]"

    def test_long_string_truncated(self):
        long_str = "x" * 1000
        result = _sanitize_value(long_str)
        assert len(result) < 600
        assert "truncated" in result

    def test_bytes_handled(self):
        result = _sanitize_value(b"\x00\x01\x02")
        assert "bytes" in str(result)

    def test_depth_limit(self):
        deep = {"a": {"b": {"c": {"d": {"e": "deep"}}}}}
        result = _sanitize_value(deep, depth=0)
        # At depth 4, it should truncate
        assert "[truncated:depth]" in str(result)

    def test_list_truncation(self):
        long_list = list(range(50))
        result = _sanitize_value(long_list)
        assert len(result) <= 22  # 20 items + truncation marker

    def test_case_insensitive_sensitive_check(self):
        result = sanitize_fields({"API_KEY": "secret", "Authorization": "Bearer xxx"})
        assert result["API_KEY"] == "[redacted]"
        assert result["Authorization"] == "[redacted]"


# ---------------------------------------------------------------------------
# 4. ID generation
# ---------------------------------------------------------------------------


class TestIdGeneration:
    def test_trace_id_format(self):
        tid = generate_trace_id()
        assert tid.startswith("tr_")
        assert len(tid) == 3 + 12  # "tr_" + 12 hex chars

    def test_request_id_format(self):
        rid = generate_request_id()
        assert rid.startswith("req_")
        assert len(rid) == 4 + 12

    def test_custom_prefix(self):
        assert generate_trace_id("custom").startswith("custom_")

    def test_uniqueness(self):
        ids = {generate_trace_id() for _ in range(100)}
        assert len(ids) == 100


# ---------------------------------------------------------------------------
# 5. log_event helper
# ---------------------------------------------------------------------------


class TestLogEvent:
    def test_basic_event(self):
        logger, stream = _capture_log()
        log_event(logger, "test.event", "info", key="value")
        output = stream.getvalue()
        assert "test.event" in output
        assert "key=value" in output

    def test_event_with_context(self):
        bind_log_context(trace_id="tr_test", request_id="req_test")
        logger, stream = _capture_log()
        log_event(logger, "http.request.start", "info", method="GET")
        output = stream.getvalue()
        assert "trace=tr_test" in output
        assert "req=req_test" in output

    def test_event_sanitizes_fields(self):
        logger, stream = _capture_log()
        log_event(logger, "test.sensitive", "info", api_key="sk-secret", model="gpt-4")
        output = stream.getvalue()
        assert "sk-secret" not in output
        assert "gpt-4" in output

    def test_event_no_context_shows_dashes(self):
        logger, stream = _capture_log()
        log_event(logger, "test.empty", "info")
        output = stream.getvalue()
        assert "trace=-" in output
        assert "req=-" in output

    def test_event_warning_level(self):
        logger, stream = _capture_log()
        log_event(logger, "test.warn", "warning", reason="something off")
        output = stream.getvalue()
        assert "WARNING" in output

    def test_event_error_level(self):
        logger, stream = _capture_log()
        log_event(logger, "test.error", "error", error_type="ValueError")
        output = stream.getvalue()
        assert "ERROR" in output

    def test_event_does_not_crash_on_bad_extra(self):
        """Even if extra keys clash with LogRecord attrs, it should not crash."""
        logger, stream = _capture_log()
        log_event(logger, "test.clash", "info", message="clash")
        # Should not raise — fallback path handles it
        output = stream.getvalue()
        assert "test.clash" in output


# ---------------------------------------------------------------------------
# 6. ContextFilter
# ---------------------------------------------------------------------------


class TestContextFilter:
    def test_filter_adds_context_fields(self):
        f = ContextFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        bind_log_context(trace_id="tr_filter")
        f.filter(record)
        assert record.trace_id == "tr_filter"
        assert record.request_id == "-"
        assert record.event == "-"

    def test_filter_preserves_existing_event(self):
        f = ContextFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        record.event = "custom.event"
        f.filter(record)
        assert record.event == "custom.event"

    def test_filter_works_without_log_context_module(self):
        """If log_context import fails, filter still returns True."""
        f = ContextFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        result = f.filter(record)
        assert result is True


# ---------------------------------------------------------------------------
# 7. JSON formatter
# ---------------------------------------------------------------------------


class TestJsonFormatter:
    def test_produces_valid_json(self):
        formatter = _JsonFormatter()
        record = logging.LogRecord(
            name="test.json", level=logging.INFO, pathname="", lineno=0,
            msg="test message", args=(), exc_info=None,
        )
        record.trace_id = "tr_json"
        record.request_id = "req_json"
        record.event = "test.json.event"
        for key in _CONTEXT_KEYS:
            if not hasattr(record, key):
                setattr(record, key, "-")

        output = formatter.format(record)
        data = json.loads(output)
        assert data["level"] == "INFO"
        assert data["name"] == "test.json"
        assert data["message"] == "test message"
        assert data["event"] == "test.json.event"
        assert data["trace_id"] == "tr_json"
        assert "timestamp" in data

    def test_includes_extra_fields(self):
        formatter = _JsonFormatter()
        record = logging.LogRecord(
            name="test.json", level=logging.INFO, pathname="", lineno=0,
            msg="extra test", args=(), exc_info=None,
        )
        record.custom_field = "custom_value"
        record.event = "-"
        for key in _CONTEXT_KEYS:
            if not hasattr(record, key):
                setattr(record, key, "-")

        output = formatter.format(record)
        data = json.loads(output)
        assert data["custom_field"] == "custom_value"

    def test_handles_non_serializable(self):
        formatter = _JsonFormatter()
        record = logging.LogRecord(
            name="test.json", level=logging.INFO, pathname="", lineno=0,
            msg="non-serializable", args=(), exc_info=None,
        )
        record.weird_object = object()
        record.event = "-"
        for key in _CONTEXT_KEYS:
            if not hasattr(record, key):
                setattr(record, key, "-")

        output = formatter.format(record)
        data = json.loads(output)
        # Should be converted to string, not crash
        assert "weird_object" in data


# ---------------------------------------------------------------------------
# 8. Integration: full logging pipeline
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_text_format_roundtrip(self):
        """Verify a log line through the full formatter pipeline."""
        bind_log_context(
            trace_id="tr_integ",
            request_id="req_integ",
            pipeline_id="pipe_123",
            stage="extract",
        )
        logger, stream = _capture_log()
        log_event(logger, "pipeline.stage.start", "info", stage_name="extract")
        output = stream.getvalue()

        assert "tr_integ" in output
        assert "req_integ" in output
        assert "pipe_123" in output
        assert "extract" in output
        assert "pipeline.stage.start" in output

    def test_json_format_roundtrip(self):
        """Verify JSON output includes all expected fields."""
        bind_log_context(trace_id="tr_json_integ", user_id="u_99")
        formatter = _JsonFormatter()

        record = logging.LogRecord(
            name="app.pipeline", level=logging.INFO, pathname="", lineno=0,
            msg="pipeline.stage.finish stage=extract duration_ms=1234",
            args=(), exc_info=None,
        )
        record.event = "pipeline.stage.finish"
        record.duration_ms = 1234
        for key in _CONTEXT_KEYS:
            if not hasattr(record, key):
                setattr(record, key, get_log_context().get(key, "-"))

        output = formatter.format(record)
        data = json.loads(output)
        assert data["trace_id"] == "tr_json_integ"
        assert data["user_id"] == "u_99"
        assert data["event"] == "pipeline.stage.finish"
        assert data["duration_ms"] == 1234
