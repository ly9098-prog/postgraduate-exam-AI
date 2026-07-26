"""OCR execution service — process-pool only (DEPRECATED).

All OCR execution now goes through ``OCRGateway`` → ``LocalOcrWorkerClient``.
This module is kept for backward compatibility and will be removed in P2.

Usage::

    from app.services.ocr_executor_service import ocr_executor
    text = await ocr_executor.run_ocr(image_bytes)
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings

logger = logging.getLogger("postgraduate-ai.ocr-executor")


class OcrQueueFullError(RuntimeError):
    """Raised when the OCR task queue has reached its capacity."""


class _OcrExecutorService:
    """Process-pool-based OCR executor (backward compat).

    All methods delegate to ``OcrProcessPool`` (process-isolated).
    No thread pool fallback — thread fallback may load PaddleOCR in the
    main process, which violates production safety requirements.
    """

    def __init__(self) -> None:
        self._shutdown = False
        self._task_timeout: int = settings.OCR_TASK_TIMEOUT_SEC

    @staticmethod
    def _ensure_not_cloud() -> None:
        """Raise RuntimeError if called in cloud_api deployment.

        The _OcrExecutorService uses local PaddleOCR, which must never
        be imported or initialized in cloud_api / production deployments.
        """
        from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile

        if detect_deployment_profile() == DeploymentProfile.CLOUD_API:
            raise RuntimeError(
                "_OcrExecutorService is forbidden in cloud_api deployment. "
                "Use OCRGateway.recognize_pages() instead."
            )

    async def run_ocr(
        self,
        image_bytes: bytes,
        timeout: int | None = None,
    ) -> str:
        """OCR a single image via process-isolated worker."""
        self._ensure_not_cloud()
        from app.core.ocr_process_pool import ocr_process_pool

        effective_timeout = timeout if timeout is not None else self._task_timeout
        loop = asyncio.get_event_loop()
        text = await asyncio.wait_for(
            loop.run_in_executor(
                None, ocr_process_pool.get_text, image_bytes, 0, effective_timeout,
            ),
            timeout=effective_timeout + 10,
        )
        return text

    async def run_ocr_pages(
        self,
        page_images: list[tuple[int, bytes]],
        timeout: int | None = None,
    ) -> dict[int, str]:
        """OCR multiple pages via process-isolated workers."""
        self._ensure_not_cloud()
        if not page_images:
            return {}

        from app.core.ocr_process_pool import ocr_process_pool

        effective_timeout = timeout if timeout is not None else self._task_timeout
        results: dict[int, str] = {}
        for idx, png in page_images:
            try:
                text = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None, ocr_process_pool.get_text, png, idx, effective_timeout,
                    ),
                    timeout=effective_timeout + 10,
                )
                results[idx] = text
            except Exception as exc:
                logger.warning("OCR process-pool page %d failed: %s", idx, exc)
                results[idx] = ""
        return results

    async def run_ocr_pages_with_boxes(
        self,
        page_images: list[tuple[int, bytes]],
        skip_rotation: bool = False,
        timeout: int | None = None,
    ) -> dict:
        """OCR pages with detection boxes via process-isolated workers."""
        self._ensure_not_cloud()
        if not page_images:
            return {}

        from app.core.ocr_process_pool import ocr_process_pool

        effective_timeout = timeout if timeout is not None else self._task_timeout
        results: dict = {}
        for idx, png in page_images:
            try:
                result = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None, ocr_process_pool.get_text_with_boxes,
                        png, idx, skip_rotation, effective_timeout,
                    ),
                    timeout=effective_timeout + 10,
                )
                results[idx] = result
            except Exception as exc:
                logger.warning("OCR process-pool boxed page %d failed: %s", idx, exc)
                results[idx] = {
                    "page_index": idx, "text": "", "boxes": [],
                    "failed": True, "error": str(exc),
                }
        return results

    # --- backward-compat delegates ---

    async def run_ocr_pages_in_process(
        self,
        page_images: list[tuple[int, bytes]],
        timeout: int | None = None,
    ) -> dict[int, str]:
        return await self.run_ocr_pages(page_images, timeout=timeout)

    async def run_ocr_pages_with_boxes_in_process(
        self,
        page_images: list[tuple[int, bytes]],
        skip_rotation: bool = False,
        timeout: int | None = None,
    ) -> dict:
        return await self.run_ocr_pages_with_boxes(
            page_images, skip_rotation=skip_rotation, timeout=timeout,
        )

    # --- lifecycle ---

    async def shutdown(self, wait: bool = True) -> None:
        """Shut down the OCR process pool.

        If *wait* is True (default), waits for running tasks to finish.
        If False, sends a non-blocking shutdown signal (cancels pending futures).
        After shutdown, new submissions raise ``RuntimeError``.

        Safe no-op in cloud_api deployments — the process pool is never
        started and importing ``ocr_process_pool`` would violate the
        cloud isolation contract.
        """
        from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile
        if detect_deployment_profile() == DeploymentProfile.CLOUD_API:
            self._shutdown = True
            logger.info("OCR executor shutdown skipped (cloud profile — no local pool)")
            return

        self._shutdown = True
        from app.core.ocr_process_pool import ocr_process_pool

        await asyncio.to_thread(ocr_process_pool.shutdown, wait)
        logger.info("OCR executor shut down (wait=%s)", wait)

    @property
    def stats(self) -> dict:
        return {
            "shutdown": self._shutdown,
        }


# Process-wide singleton
ocr_executor = _OcrExecutorService()
