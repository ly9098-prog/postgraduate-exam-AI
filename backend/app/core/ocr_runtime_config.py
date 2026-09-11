"""OcrRuntimeConfig — 单一、不可变的 OCR 运行时配置。

统一 `core/config.py`（Settings）和 `core/ocr_profile.py`（OCRProfile）
中的重叠配置项，启动时完成校验，运行时只读。

原则：
- Settings 键优先（env var / .env → 运行时覆盖）
- OCRProfile 退位为环境预设（local / production 默认值）
- 所有最终生效值启动时日志输出
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.core.config import settings
from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile
from app.core.ocr_profile import get_ocr_profile

logger = logging.getLogger(__name__)


def sanitize_url(url: str) -> str:
    """Remove credentials from a URL for logging.

    Strips username:password from URLs like:
      http://user:pass@host:port/path → http://host:port/path
    Also strips query parameters in case tokens are passed via query string.
    """
    if not url:
        return ""
    try:
        parsed = __import__("urllib.parse", fromlist=["urlparse"]).urlparse(url)
        if parsed.username or parsed.password:
            # Rebuild without credentials
            clean = parsed._replace(
                netloc=(
                    (parsed.hostname or "") + (f":{parsed.port}" if parsed.port else "")
                ),
                query="",
            )
            return clean.geturl()
        # Remove query string for safety
        if parsed.query:
            clean = parsed._replace(query="")
            return clean.geturl()
        return url
    except Exception:
        # Parsing failed — return scheme+host only if possible, else empty
        if "://" in url:
            return url.split("://")[0] + "://<redacted>"
        return "<redacted>"


def sanitize_url_strip_credentials(url: str) -> str:
    """Strip credentials from a URL but preserve query parameters.

    Unlike ``sanitize_url``, this keeps the query string — suitable for
    non‑log uses such as engine fingerprint computation where the query
    parameters are semantically meaningful.
    """
    if not url:
        return ""
    try:
        parsed = __import__("urllib.parse", fromlist=["urlparse"]).urlparse(url)
        if parsed.username or parsed.password:
            clean = parsed._replace(
                netloc=(
                    (parsed.hostname or "") + (f":{parsed.port}" if parsed.port else "")
                ),
                query="",
            )
            return clean.geturl()
        return url
    except Exception:
        if "://" in url:
            return url.split("://")[0] + "://<redacted>"
        return "<redacted>"


@dataclass(frozen=True)
class OcrRuntimeConfig:
    """Immutable, validated runtime config for the OCR pipeline.

    All fields are resolved at construction time from Settings + OCRProfile,
    with Settings taking priority.
    """

    # ── Environment ──
    environment: str = "development"  # "development" | "production"
    profile: str = ""

    # ── Engine ──
    enabled: bool = False
    use_gpu: bool = False
    language: str = "ch"

    # ── Execution concurrency ──
    executor_workers: int = 2
    max_concurrency: int = 2
    max_queue_size: int = 10
    task_timeout_seconds: int = 600

    # ── Detection params ──
    det_db_thresh: float = 0.2
    det_db_box_thresh: float = 0.4
    det_db_unclip_ratio: float = 1.8
    drop_score: float = 0.3

    # ── Image preprocessing ──
    min_image_width: int = 1500
    enable_rotation: bool = True

    # ── AI correction ──
    enable_ai_correction: bool = True

    # ── Upload / page limits ──
    max_pdf_pages: int = 0
    max_upload_bytes: int = 10 * 1024 * 1024
    max_batch_files: int = 0
    allowed_source_types: tuple[str, ...] = field(
        default_factory=lambda: ("pdf", "excel", "image", "txt"),
    )

    # ── Process Worker Pool ──
    worker_count: int = 1  # number of worker processes
    queue_capacity: int = 20  # max pending tasks in parent queue
    start_method: str = "spawn"  # multiprocessing start method

    # ── Timeouts (seconds) ──
    startup_timeout: float = 30.0  # worker readiness handshake
    queue_wait_timeout: float = 120.0  # max time in parent queue
    execution_timeout: float = 600.0  # max OCR execution in worker
    total_deadline: float = 900.0  # total request deadline
    shutdown_grace_timeout: float = 5.0  # graceful shutdown wait
    kill_timeout: float = 10.0  # force kill wait

    # ── Heartbeat ──
    heartbeat_interval: float = 30.0
    heartbeat_timeout: float = 60.0

    # ── Worker lifecycle ──
    max_tasks_per_worker: int = 0  # 0 = unlimited
    max_rss_mb: int = 0  # 0 = no limit
    max_image_bytes: int = 20 * 1024 * 1024  # 20 MB
    max_image_pixels: int = 30_000_000  # ~6000x5000

    # ── Restart governance ──
    max_restarts_per_window: int = 5
    restart_window_seconds: float = 60.0

    # ── Fallback policy ──
    remote_fallback_enabled: bool = False
    unsafe_thread_fallback_enabled: bool = False  # only dev + explicit opt-in

    # ── GPU ──
    gpu_shards: int = 1

    # ── Remote execution backend ──
    execution_backend: str = (
        "local_process"  # "local_process" | "paddlex_http" | "disabled"
    )
    remote_url: str = ""
    remote_auth_token: str = field(
        repr=False, default=""
    )  # NEVER in repr, logs, metrics, exceptions, or response bodies
    remote_auth_header: str = "Authorization"  # configurable header name
    remote_auth_scheme: str = "Bearer"  # configurable scheme prefix
    remote_connect_timeout_sec: float = 5.0
    remote_read_timeout_sec: float = 600.0
    remote_health_timeout_sec: float = 3.0
    remote_max_concurrency: int = 1
    remote_request_max_bytes: int = (
        10 * 1024 * 1024
    )  # pre-request size limit (raw image)
    remote_response_max_bytes: int = 10 * 1024 * 1024  # max response body before abort
    remote_visualize: bool = False
    remote_fail_fast: bool = False
    remote_use_doc_orientation_classify: bool = False
    remote_use_doc_unwarping: bool = False
    remote_use_textline_orientation: bool = False


def _build_runtime_config() -> OcrRuntimeConfig:
    """Merge Settings + OCRProfile into a single validated config.

    Settings (env vars / .env) take priority over profile defaults.
    """
    import os

    profile = get_ocr_profile()
    dep_profile = detect_deployment_profile()

    # Use deployment profile for environment classification
    environment = (
        "production" if dep_profile == DeploymentProfile.CLOUD_API else "development"
    )

    return OcrRuntimeConfig(
        # Environment
        environment=environment,
        profile=dep_profile.value if dep_profile else "",
        # Engine
        enabled=settings.OCR_ENABLED,
        use_gpu=settings.OCR_USE_GPU
        if settings.OCR_USE_GPU is not None
        else profile.use_gpu,
        language=settings.OCR_LANGUAGE or "ch",
        # Threading / concurrency — Settings take priority
        executor_workers=settings.OCR_EXECUTOR_WORKERS,
        max_concurrency=settings.OCR_MAX_CONCURRENCY,
        max_queue_size=settings.OCR_MAX_QUEUE_SIZE,
        task_timeout_seconds=settings.OCR_TASK_TIMEOUT_SEC,
        # Detection params — from Settings only (no profile overlap)
        det_db_thresh=settings.OCR_DET_DB_THRESH,
        det_db_box_thresh=settings.OCR_DET_DB_BOX_THRESH,
        det_db_unclip_ratio=settings.OCR_DET_DB_UNCLIP_RATIO,
        drop_score=settings.OCR_DROP_SCORE,
        # Image preprocessing — merge Settings over profile
        min_image_width=settings.OCR_MIN_IMAGE_WIDTH or profile.min_image_width,
        enable_rotation=profile.enable_rotation,
        # AI correction — from profile only
        enable_ai_correction=profile.enable_ai_correction,
        # Upload / page limits — from profile
        max_pdf_pages=profile.max_pdf_pages,
        max_upload_bytes=profile.max_upload_bytes,
        max_batch_files=profile.max_batch_files,
        allowed_source_types=profile.allowed_source_types,
        # Process Worker Pool — from Settings with defaults
        worker_count=settings.OCR_WORKER_COUNT
        if hasattr(settings, "OCR_WORKER_COUNT")
        else 1,
        queue_capacity=settings.OCR_MAX_QUEUE_SIZE * 2,
        # Timeouts
        startup_timeout=float(os.environ.get("OCR_STARTUP_TIMEOUT", "30")),
        queue_wait_timeout=float(os.environ.get("OCR_QUEUE_WAIT_TIMEOUT", "120")),
        execution_timeout=float(
            os.environ.get("OCR_EXECUTION_TIMEOUT", str(settings.OCR_TASK_TIMEOUT_SEC))
        ),
        total_deadline=float(os.environ.get("OCR_TOTAL_DEADLINE", "900")),
        shutdown_grace_timeout=float(os.environ.get("OCR_SHUTDOWN_GRACE_TIMEOUT", "5")),
        kill_timeout=float(os.environ.get("OCR_KILL_TIMEOUT", "10")),
        # Heartbeat
        heartbeat_interval=float(os.environ.get("OCR_HEARTBEAT_INTERVAL", "30")),
        heartbeat_timeout=float(os.environ.get("OCR_HEARTBEAT_TIMEOUT", "60")),
        # Worker lifecycle
        max_tasks_per_worker=int(os.environ.get("OCR_MAX_TASKS_PER_WORKER", "0")),
        max_rss_mb=int(os.environ.get("OCR_MAX_RSS_MB", "0")),
        max_image_bytes=int(
            os.environ.get("OCR_MAX_IMAGE_BYTES", str(20 * 1024 * 1024))
        ),
        max_image_pixels=int(os.environ.get("OCR_MAX_IMAGE_PIXELS", str(30_000_000))),
        # Restart governance
        max_restarts_per_window=int(os.environ.get("OCR_MAX_RESTARTS_PER_WINDOW", "5")),
        restart_window_seconds=float(
            os.environ.get("OCR_RESTART_WINDOW_SECONDS", "60")
        ),
        # Fallback policy
        remote_fallback_enabled=os.environ.get("OCR_REMOTE_FALLBACK_ENABLED", "0")
        == "1",
        unsafe_thread_fallback_enabled=os.environ.get(
            "OCR_UNSAFE_THREAD_FALLBACK_ENABLED", "0"
        )
        == "1",
        # GPU
        gpu_shards=int(os.environ.get("OCR_GPU_SHARDS", "1")),
        # Remote execution backend
        execution_backend=settings.OCR_EXECUTION_BACKEND,
        remote_url=settings.OCR_REMOTE_URL,
        remote_auth_token=settings.OCR_REMOTE_TOKEN,
        remote_auth_header=settings.OCR_REMOTE_AUTH_HEADER,
        remote_auth_scheme=settings.OCR_REMOTE_AUTH_SCHEME,
        remote_connect_timeout_sec=settings.OCR_REMOTE_CONNECT_TIMEOUT_SEC,
        remote_read_timeout_sec=settings.OCR_REMOTE_READ_TIMEOUT_SEC,
        remote_health_timeout_sec=settings.OCR_REMOTE_HEALTH_TIMEOUT_SEC,
        remote_max_concurrency=settings.OCR_REMOTE_MAX_CONCURRENCY,
        remote_request_max_bytes=settings.PDF_MAX_FILE_BYTES,
        remote_response_max_bytes=settings.PDF_MAX_FILE_BYTES,
        remote_visualize=settings.OCR_REMOTE_VISUALIZE,
        remote_fail_fast=settings.OCR_REMOTE_FAIL_FAST,
        remote_use_doc_orientation_classify=settings.OCR_REMOTE_USE_DOC_ORIENTATION_CLASSIFY,
        remote_use_doc_unwarping=settings.OCR_REMOTE_USE_DOC_UNWARPING,
        remote_use_textline_orientation=settings.OCR_REMOTE_USE_TEXTLINE_ORIENTATION,
    )


def _validate_config(cfg: OcrRuntimeConfig) -> None:
    """Validate OcrRuntimeConfig invariants.

    Raises:
        ValueError: on invalid or unsafe configuration.
    """
    errors: list[str] = []

    # Production must not use thread fallback
    if cfg.environment == "production" and cfg.unsafe_thread_fallback_enabled:
        errors.append(
            "Production environment does not allow unsafe_thread_fallback_enabled=True. "
            "OCR must use process-isolated workers."
        )

    # GPU requires spawn start method (CUDA cannot fork)
    if cfg.use_gpu and cfg.start_method != "spawn":
        errors.append(
            f"GPU mode requires start_method='spawn', got '{cfg.start_method}'. "
            "CUDA context cannot be forked."
        )

    # Worker count must be >= 1 when enabled
    if cfg.enabled and cfg.worker_count < 1:
        errors.append(f"worker_count must be >= 1, got {cfg.worker_count}")

    # Queue/lifecycle limits must be usable; invalid values otherwise fail at
    # runtime with hangs, immediate queue-full errors, or divide-by-zero waits.
    if cfg.queue_capacity < 1:
        errors.append(f"queue_capacity must be >= 1, got {cfg.queue_capacity}")
    for name, value in (
        ("startup_timeout", cfg.startup_timeout),
        ("queue_wait_timeout", cfg.queue_wait_timeout),
        ("execution_timeout", cfg.execution_timeout),
        ("total_deadline", cfg.total_deadline),
        ("kill_timeout", cfg.kill_timeout),
        ("restart_window_seconds", cfg.restart_window_seconds),
    ):
        if value <= 0:
            errors.append(f"{name} must be > 0, got {value}")
    if cfg.total_deadline < cfg.queue_wait_timeout:
        errors.append(
            "total_deadline must be >= queue_wait_timeout "
            f"({cfg.total_deadline} < {cfg.queue_wait_timeout})"
        )
    if cfg.max_tasks_per_worker < 0:
        errors.append(
            f"max_tasks_per_worker must be >= 0, got {cfg.max_tasks_per_worker}"
        )
    if cfg.max_rss_mb < 0:
        errors.append(f"max_rss_mb must be >= 0, got {cfg.max_rss_mb}")

    # Remote backend validation
    valid_backends = ("local_process", "paddlex_http", "disabled")
    if cfg.execution_backend not in valid_backends:
        errors.append(
            f"execution_backend must be one of {valid_backends}, "
            f"got '{cfg.execution_backend}'"
        )

    if cfg.execution_backend == "paddlex_http":
        if not cfg.remote_url:
            errors.append(
                "remote_url must be set when execution_backend='paddlex_http'"
            )
        if cfg.remote_connect_timeout_sec <= 0:
            errors.append(
                f"remote_connect_timeout_sec must be > 0, got {cfg.remote_connect_timeout_sec}"
            )
        if cfg.remote_read_timeout_sec <= 0:
            errors.append(
                f"remote_read_timeout_sec must be > 0, got {cfg.remote_read_timeout_sec}"
            )
        if cfg.remote_health_timeout_sec <= 0:
            errors.append(
                f"remote_health_timeout_sec must be > 0, got {cfg.remote_health_timeout_sec}"
            )
        if cfg.remote_max_concurrency < 1:
            errors.append(
                f"remote_max_concurrency must be >= 1, got {cfg.remote_max_concurrency}"
            )

    # Production must have remote auth token for paddlex_http backend
    if cfg.execution_backend == "paddlex_http" and cfg.environment == "production":
        if not cfg.remote_auth_token:
            errors.append(
                "remote_auth_token must be set when execution_backend='paddlex_http' "
                "in production environment"
            )

    if errors:
        raise ValueError("OcrRuntimeConfig validation failed:\n" + "\n".join(errors))


# Module-level singleton — built once, never mutated
_runtime_config: OcrRuntimeConfig | None = None


def get_runtime_config() -> OcrRuntimeConfig:
    """Return the process-wide OcrRuntimeConfig singleton.

    Logs the effective config on first access.
    """
    global _runtime_config
    if _runtime_config is None:
        _runtime_config = _build_runtime_config()
        _validate_config(_runtime_config)
        _log_effective_config(_runtime_config)
    return _runtime_config


def _log_effective_config(cfg: OcrRuntimeConfig) -> None:
    """Log the effective OCR runtime configuration (no secrets)."""
    logger.info(
        "OCR runtime config: "
        "env=%s profile=%s enabled=%s use_gpu=%s lang=%s "
        "workers=%d concurrency=%d queue=%d task_timeout=%ds "
        "min_width=%d rotation=%s ai=%s "
        "max_pages=%d max_upload=%d "
        "worker_count=%d queue_capacity=%d start_method=%s "
        "startup_timeout=%.0fs queue_wait_timeout=%.0fs "
        "exec_timeout=%.0fs deadline=%.0fs "
        "shutdown_grace=%.0fs kill=%.0fs "
        "heartbeat_int=%.0fs heartbeat_to=%.0fs "
        "max_tasks_per_worker=%d max_rss=%dMB "
        "max_restarts=%d restart_window=%.0fs "
        "remote_fallback=%s unsafe_thread=%s gpu_shards=%d "
        "exec_backend=%s remote_url=%s remote_concurrency=%d "
        "remote_fail_fast=%s remote_visualize=%s",
        cfg.environment,
        cfg.profile,
        cfg.enabled,
        cfg.use_gpu,
        cfg.language,
        cfg.executor_workers,
        cfg.max_concurrency,
        cfg.max_queue_size,
        cfg.task_timeout_seconds,
        cfg.min_image_width,
        cfg.enable_rotation,
        cfg.enable_ai_correction,
        cfg.max_pdf_pages,
        cfg.max_upload_bytes,
        cfg.worker_count,
        cfg.queue_capacity,
        cfg.start_method,
        cfg.startup_timeout,
        cfg.queue_wait_timeout,
        cfg.execution_timeout,
        cfg.total_deadline,
        cfg.shutdown_grace_timeout,
        cfg.kill_timeout,
        cfg.heartbeat_interval,
        cfg.heartbeat_timeout,
        cfg.max_tasks_per_worker,
        cfg.max_rss_mb,
        cfg.max_restarts_per_window,
        cfg.restart_window_seconds,
        cfg.remote_fallback_enabled,
        cfg.unsafe_thread_fallback_enabled,
        cfg.gpu_shards,
        cfg.execution_backend,
        sanitize_url(cfg.remote_url),
        cfg.remote_max_concurrency,
        cfg.remote_fail_fast,
        cfg.remote_visualize,
    )


def reset_runtime_config() -> None:
    """Reset the runtime config singleton (for testing / config reload)."""
    global _runtime_config
    _runtime_config = None
