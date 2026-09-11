"""Structured logging configuration with unified trace context.

Provides two output modes controlled by ``LOG_FORMAT``:

* **text** (default) — human-readable lines with embedded context fields.
* **json** — machine-parseable JSON with all context fields.

A :class:`ContextFilter` is attached to every handler so that ``trace_id``,
``request_id``, ``pipeline_id``, ``stage``, and other context fields are
automatically injected into every log record regardless of which logger
emits it.
"""

import json
import logging
import logging.config
import os
from datetime import UTC, datetime

try:
    import coloredlogs
except ImportError:  # pragma: no cover - requirements install provides this dependency
    coloredlogs = None

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
_USE_JSON = os.environ.get("LOG_FORMAT", "").lower() == "json"

# Context fields injected by ContextFilter (must match log_context._CONTEXT_FIELDS)
_CONTEXT_KEYS = (
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


class ContextFilter(logging.Filter):
    """Inject current log-context fields into every :class:`logging.LogRecord`."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            from app.core.log_context import get_log_context

            ctx = get_log_context()
        except Exception:
            ctx = {}

        for key in _CONTEXT_KEYS:
            if not hasattr(record, key):
                value = ctx.get(key, "-")
                setattr(record, key, value if value is not None else "-")

        if not hasattr(record, "event"):
            record.event = "-"

        return True


class _JsonFormatter(logging.Formatter):
    """Minimal JSON formatter — no external dependency required.

    Outputs one JSON object per log line with timestamp, level, logger name,
    message, event, and all context fields.  Extra fields attached via
    ``logger.info(..., extra={...})`` are included as-is.
    """

    # Keys that are part of the standard LogRecord and should not be
    # duplicated in the JSON "extra" section.
    _STANDARD_KEYS = {
        "name",
        "msg",
        "args",
        "created",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "exc_info",
        "exc_text",
        "thread",
        "threadName",
        "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        # Use record.created for accurate timestamp (not format-time)
        try:
            record.message = record.getMessage()
        except (TypeError, ValueError):
            record.message = str(record.msg)
        if not hasattr(record, "asctime"):
            record.asctime = self.formatTime(record, self.datefmt)

        output: dict = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "name": record.name,
            "message": record.message,
            "event": getattr(record, "event", "-"),
        }

        # Context fields
        for key in _CONTEXT_KEYS:
            output[key] = getattr(record, key, "-")

        # Exc info
        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            output["exc_text"] = record.exc_text

        # Non-standard extra keys
        for key, value in record.__dict__.items():
            if (
                key not in self._STANDARD_KEYS
                and key not in output
                and not key.startswith("_")
            ):
                try:
                    json.dumps(value)  # verify serializable
                    output[key] = value
                except (TypeError, ValueError):
                    output[key] = str(value)

        return json.dumps(output, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# dictConfig definition
# ---------------------------------------------------------------------------

_CONTEXT_FILTER = {"()": "app.core.logging_config.ContextFilter"}

_TEXT_FORMAT = (
    "%(asctime)s | %(levelname)-7s | %(name)s | "
    "trace=%(trace_id)s req=%(request_id)s user=%(user_id)s admin=%(admin_id)s "
    "pipeline=%(pipeline_id)s stage=%(stage)s event=%(event)s | %(message)s"
)

_LEVEL_STYLES = {
    "debug": {"color": "green"},
    "info": {"color": "cyan", "faint": True},
    "warning": {"color": "yellow", "bold": True},
    "error": {"color": "red", "bold": True},
    "critical": {"color": "red", "background": "white", "bold": True},
}


class _TerminalColoredFormatter(logging.Formatter):
    """Color text logs only when the configured stream is an interactive TTY."""

    def __init__(self, fmt=None, datefmt=None, stream=None):
        super().__init__(fmt=fmt, datefmt=datefmt)
        self._plain_formatter = logging.Formatter(fmt=fmt, datefmt=datefmt)
        self._colored_formatter = None
        if coloredlogs is not None:
            self._colored_formatter = coloredlogs.ColoredFormatter(
                fmt=fmt,
                datefmt=datefmt,
                level_styles=_LEVEL_STYLES,
                field_styles={
                    "asctime": {"color": "green"},
                    "name": {"color": "blue"},
                },
            )
        self._use_colors = bool(
            stream is not None and hasattr(stream, "isatty") and stream.isatty()
        )

    def format(self, record):
        if self._use_colors and self._colored_formatter is not None:
            rendered = self._colored_formatter.format(record)
            style = _LEVEL_STYLES.get(record.levelname.lower())
            if style:
                level_text = f"{record.levelname:<7}"
                colored_level = coloredlogs.ansi_wrap(level_text, **style)
                rendered = rendered.replace(level_text, colored_level, 1)
            return rendered
        return self._plain_formatter.format(record)


LOGGING_CONFIG: dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "context": _CONTEXT_FILTER,
    },
    "formatters": {
        "default": {
            "()": "app.core.logging_config._TerminalColoredFormatter",
            "format": _TEXT_FORMAT,
            "datefmt": "%Y-%m-%d %H:%M:%S",
            "stream": "ext://sys.stdout",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "filters": ["context"],
            "stream": "ext://sys.stdout",
        },
    },
    "root": {
        "level": LOG_LEVEL,
        "handlers": ["console"],
    },
    "loggers": {
        "uvicorn": {"level": LOG_LEVEL, "handlers": ["console"], "propagate": False},
        "uvicorn.access": {
            "level": LOG_LEVEL,
            "handlers": ["console"],
            "propagate": False,
        },
        "sqlalchemy.engine": {
            "level": "WARNING",
            "handlers": ["console"],
            "propagate": False,
        },
        "sqlalchemy.pool": {
            "level": "WARNING",
            "handlers": ["console"],
            "propagate": False,
        },
        "sqlalchemy.dialects": {
            "level": "WARNING",
            "handlers": ["console"],
            "propagate": False,
        },
        # Application-specific loggers
        "app.access": {"level": LOG_LEVEL, "handlers": ["console"], "propagate": False},
        "app.pipeline": {
            "level": LOG_LEVEL,
            "handlers": ["console"],
            "propagate": False,
        },
        "app.ai": {"level": LOG_LEVEL, "handlers": ["console"], "propagate": False},
        "app.ocr": {"level": LOG_LEVEL, "handlers": ["console"], "propagate": False},
        "app.db.slow_query": {
            "level": LOG_LEVEL,
            "handlers": ["console"],
            "propagate": False,
        },
        "app.audit": {"level": LOG_LEVEL, "handlers": ["console"], "propagate": False},
    },
}

# Switch to JSON formatter when requested
if _USE_JSON:
    LOGGING_CONFIG["formatters"]["json"] = {
        "()": "app.core.logging_config._JsonFormatter",
    }
    LOGGING_CONFIG["handlers"]["console"]["formatter"] = "json"


def setup_logging():
    logging.config.dictConfig(LOGGING_CONFIG)
