"""LocalOcrWorkerClient — OCRGateway 的本地进程执行后端。

封装 ``OcrWorkerPool``，提供 async 和 sync 两种调用方式。
sync 方法内部使用 ``asyncio.run()`` 或检测 event loop。

不在已有 event loop 中无条件使用 ``asyncio.run()``。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.ocr_types import STABLE_ERROR_CODES, WorkerResult
from app.core.ocr_worker_pool import OcrWorkerPool

logger = logging.getLogger(__name__)


class LocalOcrWorkerClient:
    """本地 OCR worker client。封装 worker pool，供 Gateway 调用。

    Usage::

        client = LocalOcrWorkerClient(config)
        results = await client.recognize_batch(images, mode="boxes")
    """

    def __init__(self, config: Any) -> None:
        self._pool = OcrWorkerPool(config)

    # ── Async API ───────────────────────────────────────────────────────────

    async def recognize(
        self,
        image_bytes: bytes,
        page_index: int = 0,
        *,
        mode: str = "boxes",
        options: dict | None = None,
    ) -> WorkerResult:
        """Single page OCR."""
        return await self._pool.submit(
            image_bytes, page_index, mode=mode, options=options,
        )

    async def recognize_batch(
        self,
        images: list[tuple[int, bytes]],
        *,
        mode: str = "boxes",
        options: dict | None = None,
    ) -> list[WorkerResult]:
        """Batch OCR. Results are sorted by ``page_index``.

        Each page is submitted independently. A single page failure
        does not block others.
        """
        if not images:
            return []

        tasks = [
            self._pool.submit(png, idx, mode=mode, options=options)
            for idx, png in images
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        resolved: list[WorkerResult] = []
        for i, r in enumerate(results):
            if isinstance(r, WorkerResult):
                resolved.append(r)
            else:
                # Exception from gather (shouldn't happen with return_exceptions)
                resolved.append(WorkerResult(
                    request_id="",
                    page_index=images[i][0],
                    status="failed",
                    stable_error_code=STABLE_ERROR_CODES["ENGINE_ERROR"],
                    error_type=str(r) if r is not None else "Unknown error",
                ))

        # Sort by page_index
        resolved.sort(key=lambda wr: wr.page_index)
        return resolved

    async def shutdown(self) -> None:
        """Graceful shutdown."""
        await self._pool.shutdown()

    @property
    def metrics(self) -> dict:
        return self._pool.metrics

    @property
    def pool(self) -> OcrWorkerPool:
        return self._pool
