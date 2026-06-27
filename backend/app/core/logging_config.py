"""结构化日志配置。"""

import logging.config
import os

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
_USE_JSON = os.environ.get("LOG_FORMAT") == "json"

_JSON_FORMATTER: dict | None = None
if _USE_JSON:
    try:
        import pythonjsonlogger.jsonlogger  # noqa: F401
        _JSON_FORMATTER = {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": "%(timestamp)s %(level)s %(name)s %(message)s",
        }
    except ImportError:
        pass

LOGGING_CONFIG: dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "stream": "ext://sys.stdout",
        },
    },
    "root": {
        "level": LOG_LEVEL,
        "handlers": ["console"],
    },
    "loggers": {
        "uvicorn": {"level": LOG_LEVEL, "handlers": ["console"], "propagate": False},
        "uvicorn.access": {"level": LOG_LEVEL, "handlers": ["console"], "propagate": False},
        "sqlalchemy.engine": {"level": "WARNING", "handlers": ["console"], "propagate": False},
        "sqlalchemy.pool": {"level": "WARNING", "handlers": ["console"], "propagate": False},
        "sqlalchemy.dialects": {"level": "WARNING", "handlers": ["console"], "propagate": False},
    },
}

if _JSON_FORMATTER:
    LOGGING_CONFIG["formatters"]["json"] = _JSON_FORMATTER
    LOGGING_CONFIG["handlers"]["console"]["formatter"] = "json"


def setup_logging():
    logging.config.dictConfig(LOGGING_CONFIG)
