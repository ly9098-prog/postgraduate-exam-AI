"""Standalone entry guards, scratch configuration and failure reporting."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import Settings
    from app.core.deployment_profile import DeploymentProfile

STANDALONE_ROLES = frozenset({"worker", "scheduler"})


def reject_standalone_http_launch(role: str) -> None:
    """Raise SystemError if a worker or scheduler role is started over HTTP.

    Detects Gunicorn/uvicorn by checking whether this process was launched
    by a web server (argv contains gunicorn/uvicorn or GUNICORN_CMD_ARGS
    / UVICORN_CMD_ARGS env vars are set).

    Workers and schedulers must be started as standalone processes via
    ``python -m app.worker_main`` / ``python -m app.scheduler_main``.
    Starting them over HTTP would expose an unnecessary port and waste
    resources on connection handling.
    """
    if role not in STANDALONE_ROLES:
        return
    is_http = (
        "gunicorn" in (sys.argv[0] if sys.argv else "").lower()
        or "uvicorn" in (sys.argv[0] if sys.argv else "").lower()
        or bool(os.environ.get("GUNICORN_CMD_ARGS"))
        or bool(os.environ.get("UVICORN_CMD_ARGS"))
    )
    if is_http:
        raise SystemError(
            f"PROCESS_ROLE={role} started over HTTP (Gunicorn/uvicorn). "
            f"This role must be started as a standalone process: "
            f"python -m app.{role}_main"
        )


def create_standalone_failure_reporter(
    profile: DeploymentProfile, config: Settings, logger: logging.Logger,
) -> Callable[[str, Exception], None]:
    """Return a callable that reports component startup failures.

    In cloud_api/production, raises SystemError; in development, logs warning.
    """
    from app.core.deployment_profile import DeploymentProfile

    is_restricted = (
        profile == DeploymentProfile.CLOUD_API or config.APP_ENV == "production"
    )

    def _report(component: str, exc: Exception) -> None:
        if is_restricted:
            logger.critical("%s start failed \u2014 fatal in production", component)
            raise SystemError(f"{component} start failed: {exc}") from exc
        logger.warning("%s start failed (non-fatal): %s", component, exc)

    return _report


def ensure_worker_scratch_directory(config: Settings) -> str:
    """Ensure worker scratch directory exists, raising on misconfiguration."""
    scratch = config.WORKER_SCRATCH_DIR
    if not scratch or scratch == "/tmp" or scratch == "/tmp/worker-scratch":
        # In production, WORKER_SCRATCH_DIR must be explicitly configured.
        # In development, fall back to a safe location.
        from app.core.deployment_profile import (
            DeploymentProfile,
            detect_deployment_profile,
        )

        profile = detect_deployment_profile()
        if profile == DeploymentProfile.CLOUD_API or config.APP_ENV == "production":
            raise SystemError(
                "WORKER_SCRATCH_DIR must be explicitly configured in production "
                "(pointing to a Docker volume or dedicated directory). "
                f"Current value: {scratch!r}"
            )
        scratch = os.path.join(
            os.path.dirname(config.STAGING_STORAGE_DIR or "/app/staging"),
            "scratch",
        )
    os.makedirs(scratch, exist_ok=True)
    return scratch
