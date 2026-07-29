"""OCR Worker configuration — all settings in one place, driven by env vars."""

from __future__ import annotations

import os


class OCRWorkerConfig:
    """Worker configuration, loaded from environment variables.

    Attributes mirroring the spec in current_task.md section 5.
    """

    # Identity
    WORKER_ID: str = os.environ.get("OCR_WORKER_ID", "local-ocr-01")

    # Concurrency (hard-coded to 1 due to 4GB GPU limit)
    CONCURRENCY: int = 1

    # Polling / lease
    POLL_INTERVAL_SECONDS: int = int(os.environ.get("OCR_WORKER_POLL_INTERVAL_SECONDS", "5"))
    LEASE_SECONDS: int = int(os.environ.get("OCR_WORKER_LEASE_SECONDS", "300"))
    HEARTBEAT_SECONDS: int = int(os.environ.get("OCR_WORKER_HEARTBEAT_SECONDS", "45"))

    # Process management
    MAX_TASKS_PER_CHILD: int = int(os.environ.get("OCR_WORKER_MAX_TASKS_PER_CHILD", "20"))

    # Workspace
    WORKSPACE_ROOT: str = os.environ.get(
        "OCR_WORKER_WORKSPACE", "/data/ocr-worker"
    )
    MAX_WORKSPACE_GB: int = int(os.environ.get("OCR_WORKER_MAX_WORKSPACE_GB", "20"))
    RESULT_RETENTION_HOURS: int = int(os.environ.get("OCR_WORKER_RESULT_RETENTION_HOURS", "72"))

    # GPU / resource limits
    GPU_MEMORY_LIMIT_MB: int = int(os.environ.get("OCR_WORKER_GPU_MEMORY_LIMIT_MB", "3600"))
    CPU_FALLBACK: bool = os.environ.get("OCR_WORKER_CPU_FALLBACK", "false").lower() == "true"
    OCR_TIMEOUT_SECONDS: int = int(os.environ.get("OCR_WORKER_OCR_TIMEOUT_SECONDS", "600"))

    # Production server
    SERVER_URL: str = os.environ.get("OCR_WORKER_SERVER_URL", "")
    API_KEY: str = os.environ.get("OCR_WORKER_API_KEY", "")

    # Local OCR adapter mode
    ADAPTER_MODE: str = os.environ.get(
        "LOCAL_OCR_ADAPTER_MODE", "conversion_shadow"
    )  # "conversion_shadow" | "adapter"

    # Circuit breaker
    CIRCUIT_BREAKER_PATH: str = os.environ.get(
        "OCR_WORKER_CIRCUIT_BREAKER_PATH",
        os.path.join(WORKSPACE_ROOT, ".circuit_breaker.json"),
    )

    @classmethod
    def validate(cls) -> list[str]:
        """Validate configuration. Returns list of error messages (empty = valid)."""
        errors: list[str] = []
        if not cls.SERVER_URL:
            errors.append("OCR_WORKER_SERVER_URL is required")
        if not cls.API_KEY:
            errors.append("OCR_WORKER_API_KEY is required")
        if cls.WORKER_ID == "local-ocr-01" and "OCR_WORKER_ID" not in os.environ:
            pass  # default is fine
        if cls.CONCURRENCY != 1:
            errors.append("CONCURRENCY must be 1 (single GPU)")
        if cls.LEASE_SECONDS < 60:
            errors.append("LEASE_SECONDS must be >= 60")
        if cls.HEARTBEAT_SECONDS < 10:
            errors.append("HEARTBEAT_SECONDS must be >= 10")
        if cls.HEARTBEAT_SECONDS >= cls.LEASE_SECONDS // 2:
            errors.append("HEARTBEAT_SECONDS must be less than half LEASE_SECONDS")
        if cls.POLL_INTERVAL_SECONDS < 1:
            errors.append("POLL_INTERVAL_SECONDS must be >= 1")
        if cls.OCR_TIMEOUT_SECONDS < 1:
            errors.append("OCR_TIMEOUT_SECONDS must be >= 1")
        if cls.MAX_TASKS_PER_CHILD < 1:
            errors.append("MAX_TASKS_PER_CHILD must be >= 1")
        if cls.RESULT_RETENTION_HOURS < 0:
            errors.append("RESULT_RETENTION_HOURS must be >= 0")
        if cls.MAX_WORKSPACE_GB < 1:
            errors.append("MAX_WORKSPACE_GB must be >= 1")
        return errors
