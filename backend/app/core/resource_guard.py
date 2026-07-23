"""Resource Guard — unified production resource protection.

Combines system-level monitoring (RSS, memory, event-loop lag) with
per-pipeline budgeting (input size, pages, pixels, OCR calls, artifacts).

Usage::

    from app.core.resource_guard import resource_guard

    # System-level check (before starting any pipeline)
    ok, reason = resource_guard.can_accept_work()
    if not ok:
        return {"error": "resource_pressure", "detail": reason}

    # Pipeline-level check (per-pipeline limits)
    guard = ResourceGuard.for_profile(profile)
    guard.check_input_bytes(file_size)
    guard.check_page_count(page_count)
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Callable

from app.core.deployment_profile import DeploymentProfile

logger = logging.getLogger("postgraduate-ai.resource_guard")


# ── Error Codes ──

RESOURCE_PRESSURE = "RESOURCE_PRESSURE"
INPUT_TOO_LARGE = "INPUT_TOO_LARGE"
PAGE_LIMIT_EXCEEDED = "PAGE_LIMIT_EXCEEDED"
PIXEL_BUDGET_EXCEEDED = "PIXEL_BUDGET_EXCEEDED"
CONCURRENCY_LIMIT_EXCEEDED = "CONCURRENCY_LIMIT_EXCEEDED"
REMOTE_OCR_CALL_BUDGET_EXCEEDED = "REMOTE_OCR_CALL_BUDGET_EXCEEDED"
ARTIFACT_SIZE_LIMIT_EXCEEDED = "ARTIFACT_SIZE_LIMIT_EXCEEDED"
PIPELINE_TIMEOUT = "PIPELINE_TIMEOUT"
PAGE_TIMEOUT = "PAGE_TIMEOUT"


class ResourceGuardError(ValueError):
    """Raised when a resource guard limit is exceeded."""
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


# ── System-level thresholds ──


@dataclass
class SystemThresholds:
    """System resource thresholds that trigger protective actions."""
    max_rss_mb: float = 1024
    min_available_memory_mb: float = 256
    max_event_loop_lag_ms: float = 500
    max_active_pipelines: int = 1
    max_temp_disk_mb: float = 512


@dataclass
class SystemMetrics:
    """Snapshot of current system resource usage."""
    rss_mb: float = 0.0
    available_memory_mb: float = 0.0
    event_loop_lag_ms: float = 0.0
    active_pipelines: int = 0
    temp_disk_usage_mb: float = 0.0


# ── Unified ResourceGuard ──


class ResourceGuard:
    """Combined system-level + per-pipeline resource guard.

    Provides:
    - ``can_accept_work()`` — system-level check before accepting new jobs
    - ``check_*()`` — per-pipeline budget checks
    - ``for_profile()`` — factory with profile-appropriate defaults
    """

    # ── Class-level active pipeline counter (cross-instance) ──
    _active_pipeline_count: int = 0

    # ── Construction ──

    def __init__(
        self,
        thresholds: SystemThresholds | None = None,
        metrics_provider: Callable[[], SystemMetrics] | None = None,
    ):
        # System-level
        self._thresholds = thresholds or SystemThresholds()
        self._metrics_provider = metrics_provider or self._collect_system_metrics

        # Per-pipeline limits (default: production cloud_api)
        self.max_input_bytes: int = 10 * 1024 * 1024
        self.max_pages: int = 50
        self.max_pixel_budget: int = 4000 * 4000 * 50
        self.max_concurrent_documents: int = 1
        self.max_concurrent_pages: int = 1
        self.max_remote_ocr_calls: int = 100
        self.max_artifact_bytes: int = 50 * 1024 * 1024
        self.max_pipeline_seconds: int = 1800
        self.max_page_seconds: int = 120

        # Per-pipeline mutable state
        self._render_pixels_consumed: int = 0
        self._remote_ocr_calls: int = 0
        self._artifact_bytes_written: int = 0

    @classmethod
    def for_profile(cls, profile: DeploymentProfile) -> ResourceGuard:
        """Create a ResourceGuard with defaults for the deployment profile."""
        guard = cls()
        if profile == DeploymentProfile.CLOUD_API:
            guard.max_input_bytes = 10 * 1024 * 1024
            guard.max_pages = 50
            guard.max_pixel_budget = 4000 * 4000 * 50
            guard.max_remote_ocr_calls = 100
            guard.max_artifact_bytes = 50 * 1024 * 1024
            guard.max_pipeline_seconds = 1800
            guard.max_page_seconds = 120
            guard._thresholds = SystemThresholds(
                max_active_pipelines=1,
            )
        else:
            guard.max_input_bytes = 200 * 1024 * 1024
            guard.max_pages = 600
            guard.max_pixel_budget = 4000 * 4000 * 600
            guard.max_concurrent_pages = 3
            guard.max_remote_ocr_calls = 500
            guard.max_artifact_bytes = 500 * 1024 * 1024
            guard.max_pipeline_seconds = 7200
            guard.max_page_seconds = 600
            guard._thresholds = SystemThresholds(
                max_active_pipelines=3,
                max_rss_mb=3072,
            )
        return guard

    # ── System-level check ──

    def can_accept_work(self) -> tuple[bool, str | None]:
        """Check if the server can accept new pipeline work.

        Returns (True, None) if OK, or (False, reason) if resource pressure.
        """
        metrics = self._metrics_provider()

        if metrics.rss_mb > self._thresholds.max_rss_mb:
            return False, f"RSS {metrics.rss_mb:.0f}MB exceeds limit {self._thresholds.max_rss_mb}MB"

        if metrics.available_memory_mb > 0 and metrics.available_memory_mb < self._thresholds.min_available_memory_mb:
            return False, f"Available memory {metrics.available_memory_mb:.0f}MB below minimum {self._thresholds.min_available_memory_mb}MB"

        if metrics.event_loop_lag_ms > self._thresholds.max_event_loop_lag_ms:
            return False, f"Event loop lag {metrics.event_loop_lag_ms:.0f}ms exceeds limit {self._thresholds.max_event_loop_lag_ms}ms"

        active = ResourceGuard._active_pipeline_count
        if active >= self._thresholds.max_active_pipelines:
            return False, f"Active pipelines {active} at limit {self._thresholds.max_active_pipelines}"

        if metrics.temp_disk_usage_mb > self._thresholds.max_temp_disk_mb:
            return False, f"Temp disk {metrics.temp_disk_usage_mb:.0f}MB exceeds limit {self._thresholds.max_temp_disk_mb}MB"

        return True, None

    @staticmethod
    def _collect_system_metrics() -> SystemMetrics:
        """Collect real resource metrics from the system."""
        m = SystemMetrics()

        try:
            with open("/proc/self/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        m.rss_mb = int(line.split()[1]) / 1024
                        break
        except OSError:
            pass

        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        m.available_memory_mb = int(line.split()[1]) / 1024
                        break
        except OSError:
            pass

        m.active_pipelines = ResourceGuard._active_pipeline_count

        return m

    def get_system_metrics(self) -> SystemMetrics:
        return self._metrics_provider()

    # ── Pipeline count tracking ──

    @classmethod
    def increment_pipeline_count(cls) -> None:
        cls._active_pipeline_count += 1

    @classmethod
    def decrement_pipeline_count(cls) -> None:
        cls._active_pipeline_count = max(0, cls._active_pipeline_count - 1)

    # ── Per-pipeline budget checks ──

    def check_input_bytes(self, size: int) -> None:
        if size > self.max_input_bytes:
            raise ResourceGuardError(
                INPUT_TOO_LARGE,
                f"Input {size} bytes exceeds limit {self.max_input_bytes}",
            )

    def check_page_count(self, count: int) -> None:
        if count > self.max_pages:
            raise ResourceGuardError(
                PAGE_LIMIT_EXCEEDED,
                f"Page count {count} exceeds limit {self.max_pages}",
            )

    def check_render_pixels(self, pixels: int) -> None:
        new_total = self._render_pixels_consumed + pixels
        if new_total > self.max_pixel_budget:
            raise ResourceGuardError(
                PIXEL_BUDGET_EXCEEDED,
                f"Render pixel budget {new_total} exceeds limit {self.max_pixel_budget}",
            )
        self._render_pixels_consumed = new_total

    def check_remote_ocr_call(self) -> None:
        if self._remote_ocr_calls >= self.max_remote_ocr_calls:
            raise ResourceGuardError(
                REMOTE_OCR_CALL_BUDGET_EXCEEDED,
                f"Remote OCR calls {self._remote_ocr_calls} exceeds limit {self.max_remote_ocr_calls}",
            )
        self._remote_ocr_calls += 1

    def check_artifact_bytes(self, size: int) -> None:
        new_total = self._artifact_bytes_written + size
        if new_total > self.max_artifact_bytes:
            raise ResourceGuardError(
                ARTIFACT_SIZE_LIMIT_EXCEEDED,
                f"Artifact size {new_total} exceeds limit {self.max_artifact_bytes}",
            )
        self._artifact_bytes_written = new_total


# ── Module-level singleton ──

resource_guard = ResourceGuard()
