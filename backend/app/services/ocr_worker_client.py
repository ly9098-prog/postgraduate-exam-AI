"""OcrWorkerClient Protocol — unified interface for OCR execution backends.

All OCR worker clients (local process, PaddleX HTTP, etc.) must implement
this protocol so that ``OCRGateway`` can remain backend-agnostic.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

import httpx

from app.core.ocr_runtime_config import OcrRuntimeConfig, sanitize_url

logger = logging.getLogger(__name__)


@runtime_checkable
class OcrWorkerClient(Protocol):
    """Protocol that every OCR worker client must satisfy.

    Methods mirror ``LocalOcrWorkerClient`` so the Gateway can call
    them without knowing which backend is active.
    """

    async def recognize(
        self,
        image_bytes: bytes,
        page_index: int = 0,
        *,
        mode: str = "boxes",
        options: dict | None = None,
    ) -> Any:  # WorkerResult
        ...

    async def recognize_batch(
        self,
        images: list[tuple[int, bytes]],
        *,
        mode: str = "boxes",
        options: dict | None = None,
    ) -> list[Any]:  # list[WorkerResult]
        ...

    async def shutdown(self) -> None:
        ...

    @property
    def metrics(self) -> dict:
        ...


def create_ocr_worker_client(
    config: OcrRuntimeConfig,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> OcrWorkerClient | None:
    """Factory: create the appropriate worker client for the given config.

    Args:
        config: Resolved runtime config.
        http_client: Optional shared ``httpx.AsyncClient``.  If provided, the
            client will use this instance and will **not** close it on
            ``shutdown()`` (ownership remains with the caller).

    Returns:
        An ``OcrWorkerClient`` instance, or ``None`` if the backend is disabled.

    Raises:
        ValueError: If ``execution_backend`` is not a recognised value.
    """
    backend = config.execution_backend

    if backend == "disabled":
        logger.info("OCR execution backend is 'disabled' — no worker client created")
        return None

    if backend == "local_process":
        # Delay-import to avoid touching ``OcrWorkerPool`` / PaddleOCR at
        # module level when a different backend is configured.
        from app.services.ocr_local_worker_client import LocalOcrWorkerClient

        logger.info(
            "Creating LocalOcrWorkerClient (workers=%d, gpu=%s)",
            config.executor_workers, config.use_gpu,
        )
        return LocalOcrWorkerClient(config)

    if backend == "paddlex_http":
        # Delay-import so that ``PaddleXHttpOcrWorkerClient`` and its
        # httpx-only dependencies are loaded only when actually needed.
        from app.services.ocr_paddlex_http_client import PaddleXHttpOcrWorkerClient

        logger.info(
            "Creating PaddleXHttpOcrWorkerClient (url=%s, concurrency=%d)",
            sanitize_url(config.remote_url), config.remote_max_concurrency,
        )
        return PaddleXHttpOcrWorkerClient(config, http_client=http_client)

    raise ValueError(
        f"Unrecognised OCR execution_backend '{backend}'. "
        f"Expected one of: local_process, paddlex_http, disabled"
    )
