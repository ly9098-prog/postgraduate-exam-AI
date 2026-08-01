"""PaddleOCR-VL adapter — OCRFixerProtocol-compatible adapter for PaddleOCR-VL API.

The adapter wraps ``PaddleOCRVLClient`` and conforms to the ``OCRFixerProtocol``
interface so it can be registered with ``OCRFixRouter`` and used alongside
DeepSeek and Rule fixers.

PaddleOCR-VL is a high-accuracy external OCR engine. Unlike the other adapters
which *correct* existing OCR text, this adapter performs its own OCR on the
original image and returns the recognized text.  In the router chain it sits
first so high-accuracy external OCR is tried before DeepSeek text correction.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.features.ocr_fix.interfaces import OCRFixResult

logger = logging.getLogger(__name__)


class PaddleOCRVLAdapter:
    """OCRFixerProtocol adapter for PaddleOCR-VL external OCR API."""

    model_name = "paddleocr-vl-1.6"

    def __init__(
        self,
        api_token: str = "",
        base_url: str = "https://paddleocr.aistudio-app.com",
        model: str = "PaddleOCR-VL-1.6",
        config: dict[str, Any] | None = None,
    ):
        self._api_token = api_token
        self._base_url = base_url
        self._model = model
        self.config = config or {}

    @property
    def is_available(self) -> bool:
        return bool(self._api_token)

    async def fix(
        self,
        image: bytes | None = None,
        ocr_text: str = "",
        context: dict[str, Any] | None = None,
    ) -> OCRFixResult:
        """Run OCR via PaddleOCR-VL API and return recognized text.

        Unlike DeepSeek adapter which *corrects* existing OCR text,
        this adapter performs its own OCR from the original image.  The
        ``ocr_text`` parameter is ignored when ``image`` is available.

        Args:
            image: Original page image bytes (PNG recommended).
            ocr_text: Ignored when image is present; used as fallback.
            context: Optional metadata (page_num, filename, etc.).

        Returns:
            OCRFixResult with the recognized text from PaddleOCR-VL.
        """
        if not self.is_available:
            logger.warning("PaddleOCR-VL not configured (no API token)")
            return OCRFixResult(
                fixed_text=ocr_text,
                confidence=0.0,
                model_used=self.model_name,
                raw_response="error:no_api_token",
            )

        if not image:
            logger.warning("PaddleOCR-VL requires an image — no image provided, using fallback text")
            return OCRFixResult(
                fixed_text=ocr_text,
                confidence=0.0,
                model_used=self.model_name,
                raw_response="error:no_image",
            )

        ctx = context or {}
        filename = ctx.get("filename", f"page_{ctx.get('page_num', 'unknown')}.png")

        from app.features.ocr_vl.paddleocr_vl_client import PaddleOCRVLClient

        client = PaddleOCRVLClient(
            api_token=self._api_token,
            base_url=self._base_url,
            model=self._model,
        )

        start = time.monotonic()
        entry_point = ctx.get("entry_point", "adapter")
        try:
            result = await client.ocr_image(image_bytes=image, filename=filename)
            duration_ms = round((time.monotonic() - start) * 1000)
            logger.info(
                "PaddleOCR-VL succeeded (entry=%s, %.2fs, conf=%.2f, text_len=%d)",
                entry_point, duration_ms / 1000, result.confidence, len(result.text),
            )
            return OCRFixResult(
                fixed_text=result.text or ocr_text,
                confidence=result.confidence,
                model_used=self.model_name,
                tokens_used=0,
                duration_ms=duration_ms,
                metadata={
                    "layout_blocks": result.layout_blocks,
                    "raw_entries": result.raw_entries[:200],
                },
            )
        except Exception as exc:
            duration_ms = round((time.monotonic() - start) * 1000)
            logger.warning(
                "PaddleOCR-VL failed (entry=%s, %.2fs): %s — falling through",
                entry_point, duration_ms / 1000, exc,
            )
            return OCRFixResult(
                fixed_text=ocr_text,
                confidence=0.0,
                model_used=self.model_name,
                raw_response=f"error:{exc}",
                duration_ms=duration_ms,
            )
        finally:
            await client.close()
