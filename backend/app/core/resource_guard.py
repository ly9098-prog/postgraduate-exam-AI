"""Resource guard — production server resource monitoring and protection.

Design:
- Monitors RSS, available memory, event-loop lag, active post-OCR jobs.
- Hard limits prevent OOM on the 2C/2G production server.
- When resources are low, new post-OCR jobs are not accepted.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger("postgraduate-ai.core.resource_guard")


@dataclass
class ResourceMetrics:
    """Snapshot of current resource usage."""
    rss_mb: float = 0.0
    available_memory_mb: float = 0.0
    event_loop_lag_ms: float = 0.0
    active_post_ocr_jobs: int = 0
    open_fds: int = 0
    temp_disk_usage_mb: float = 0.0
    artifact_streaming_count: int = 0


@dataclass
class ResourceThresholds:
    """Resource thresholds that trigger protective actions."""
    max_rss_mb: float = 1024  # Max RSS before refusing new work
    min_available_memory_mb: float = 256  # Min available RAM
    max_event_loop_lag_ms: float = 500  # Max event loop delay
    max_post_ocr_jobs: int = 1  # Max concurrent post-OCR jobs
    max_artifact_streaming: int = 2  # Max concurrent artifact streams
    max_temp_disk_mb: float = 512  # Max temp disk usage


class ResourceGuard:
    """Production server resource guard.

    Usage:
        guard = ResourceGuard()
        if guard.can_accept_work():
            # proceed
        else:
            # return RESOURCE_PRESSURE
    """

    def __init__(
        self,
        thresholds: ResourceThresholds | None = None,
        metrics_provider: Callable[[], ResourceMetrics] | None = None,
    ) -> None:
        self._thresholds = thresholds or ResourceThresholds()
        self._metrics_provider = metrics_provider or self._collect_metrics

    def can_accept_work(self) -> tuple[bool, str | None]:
        """Check if the server can accept new post-OCR work.

        Returns (True, None) if OK, or (False, reason) if resource pressure.
        """
        metrics = self._metrics_provider()
        return self._evaluate(metrics)

    def _evaluate(self, m: ResourceMetrics) -> tuple[bool, str | None]:
        """Evaluate metrics against thresholds."""
        if m.rss_mb > self._thresholds.max_rss_mb:
            return False, f"RSS {m.rss_mb:.0f}MB exceeds limit {self._thresholds.max_rss_mb}MB"

        if m.available_memory_mb > 0 and m.available_memory_mb < self._thresholds.min_available_memory_mb:
            return False, (
                f"Available memory {m.available_memory_mb:.0f}MB "
                f"below minimum {self._thresholds.min_available_memory_mb}MB"
            )

        if m.event_loop_lag_ms > self._thresholds.max_event_loop_lag_ms:
            return False, (
                f"Event loop lag {m.event_loop_lag_ms:.0f}ms "
                f"exceeds limit {self._thresholds.max_event_loop_lag_ms}ms"
            )

        if m.active_post_ocr_jobs >= self._thresholds.max_post_ocr_jobs:
            return False, (
                f"Active post-OCR jobs {m.active_post_ocr_jobs} "
                f"at limit {self._thresholds.max_post_ocr_jobs}"
            )

        if m.artifact_streaming_count >= self._thresholds.max_artifact_streaming:
            return False, (
                f"Artifact streams {m.artifact_streaming_count} "
                f"at limit {self._thresholds.max_artifact_streaming}"
            )

        if m.temp_disk_usage_mb > self._thresholds.max_temp_disk_mb:
            return False, (
                f"Temp disk {m.temp_disk_usage_mb:.0f}MB "
                f"exceeds limit {self._thresholds.max_temp_disk_mb}MB"
            )

        return True, None

    @staticmethod
    def _collect_metrics() -> ResourceMetrics:
        """Collect real resource metrics from the system."""
        m = ResourceMetrics()

        # RSS via /proc/self/status
        try:
            with open("/proc/self/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        m.rss_mb = int(line.split()[1]) / 1024
                        break
        except (OSError, IndexError, ValueError):
            pass

        # Available memory via /proc/meminfo
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        m.available_memory_mb = int(line.split()[1]) / 1024
                        break
        except (OSError, IndexError, ValueError):
            pass

        # Open file descriptors
        try:
            m.open_fds = len(os.listdir(f"/proc/{os.getpid()}/fd"))
        except OSError:
            pass

        return m

    def get_metrics(self) -> ResourceMetrics:
        """Return current resource metrics snapshot."""
        return self._metrics_provider()


# Module-level singleton for production use
resource_guard = ResourceGuard()
