"""DeepSeek 文本纠错适配器 — 作为低成本 fallback。"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.features.ocr_fix.canonical_output import canonicalize
from app.features.ocr_fix.interfaces import OCRFixResult

logger = logging.getLogger(__name__)

try:
    from app.core.log_context import log_event
except ImportError:  # pragma: no cover
    def log_event(_lg, _ev, **_kw):  # type: ignore[misc]
        pass


class DeepSeekFixer:
    """DeepSeek 文本模型 OCR 纠错适配器。

    通过 DeepSeek API 对 OCR 文本进行 AI 纠错。
    视觉能力有限，仅做文本纠错。
    """

    model_name = "deepseek"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        config: dict[str, Any] | None = None,
    ):
        from app.ai.client import deepseek

        self._deepseek = deepseek
        self._api_key = api_key
        self._base_url = base_url
        self.config = config or {}

    @property
    def is_available(self) -> bool:
        return bool(self._api_key) or self._deepseek.is_available()

    async def fix(
        self,
        image: bytes | None = None,
        ocr_text: str = "",
        context: dict[str, Any] | None = None,
    ) -> OCRFixResult:
        if not ocr_text.strip():
            return OCRFixResult(
                fixed_text=ocr_text,
                model_used=self.model_name,
            )

        if not self._api_key and not self._deepseek.is_available():
            return OCRFixResult(
                fixed_text=ocr_text,
                confidence=None,
                model_used=self.model_name,
                raw_response="deepseek unavailable",
            )

        from app.ai.prompts import build_ocr_correction

        messages = build_ocr_correction(ocr_text)

        start = time.monotonic()
        log_event(
            logger, "ocr.fix.adapter.start", "info",
            adapter="deepseek", ocr_text_chars=len(ocr_text),
        )
        try:
            result = await self._deepseek.chat(
                messages,
                temperature=0.1,
                api_key=self._api_key,
                base_url=self._base_url,
            )
            duration_ms = int((time.monotonic() - start) * 1000)

            corrected_raw = (result.get("content") or "").strip()
            corrected, _meta = canonicalize(corrected_raw, model_name="deepseek")
            if not corrected:
                return OCRFixResult(
                    fixed_text=ocr_text,
                    model_used=self.model_name,
                    duration_ms=duration_ms,
                )

            # Safety: reject if AI output is drastically different in length
            original_len = len(ocr_text)
            if len(corrected) > original_len * 2 or len(corrected) < original_len * 0.5:
                return OCRFixResult(
                    fixed_text=ocr_text,
                    model_used=self.model_name,
                    duration_ms=duration_ms,
                    raw_response="output length out of bounds",
                )

            # ── Garbled code persistence check (P0) ──
            # Pure-text LLMs cannot reliably reconstruct garbled code.
            # If the original text has code_garbled_text and the corrected
            # output still has it without significant improvement, reject.
            try:
                from app.features.code_integrity import detect_code_block_integrity
                _orig_code = detect_code_block_integrity(ocr_text)
                _fixed_code = detect_code_block_integrity(corrected)
                if (
                    "code_garbled_text" in _orig_code.get("flags", [])
                    and "code_garbled_text" in _fixed_code.get("flags", [])
                ):
                    _orig_score = _orig_code.get("score", 1.0)
                    _fixed_score = _fixed_code.get("score", 1.0)
                    if _fixed_score >= _orig_score * 0.8:
                        logger.warning(
                            "DeepSeek garbled code persisted: score %.2f->%.2f, "
                            "reverting to original | original_preview=%.80s",
                            _orig_score, _fixed_score, ocr_text[:80],
                        )
                        return OCRFixResult(
                            fixed_text=ocr_text,
                            model_used=self.model_name,
                            duration_ms=duration_ms,
                            raw_response="garbled_text_persists",
                        )
            except Exception:
                logger.warning("DeepSeek garbled code check failed", exc_info=True)
            # ── End garbled code persistence check ──

            # 检查是否丢失了题干：如果原文包含题号模式（如"06."或"1."）
            # 但校正后文本以选项字母开头，说明题干被丢弃了
            import re
            has_question_number = bool(re.search(r'^\s*\d+\s*[.．、]', ocr_text, re.MULTILINE))
            first_line = corrected.split('\n')[0].strip()
            starts_with_option = bool(re.match(r'^[A-D]\s*[.．、:：)）]\s*', first_line))
            if has_question_number and starts_with_option and not re.search(r'^\s*\d+\s*[.．、]', corrected, re.MULTILINE):
                logger.warning(
                    "DeepSeek output dropped the question stem, using original text | "
                    "first_line=%.80s", first_line,
                )
                return OCRFixResult(
                    fixed_text=ocr_text,
                    model_used=self.model_name,
                    duration_ms=duration_ms,
                    raw_response="stem lost in correction",
                )

            log_event(
                logger, "ocr.fix.adapter.finish", "info",
                adapter="deepseek", duration_ms=duration_ms,
                tokens_used=result.get("tokens_used"),
                corrected_chars=len(corrected),
            )
            return OCRFixResult(
                fixed_text=corrected,
                confidence=0.85,
                model_used=self.model_name,
                raw_response=corrected,
                tokens_used=result.get("tokens_used"),
                duration_ms=duration_ms,
            )
        except Exception as exc:
            logger.warning("DeepSeek OCR fix failed: %s", exc)
            log_event(
                logger, "ocr.fix.adapter.error", "error",
                adapter="deepseek", error_type=type(exc).__name__,
                error_message=str(exc)[:200],
            )
            return OCRFixResult(
                fixed_text=ocr_text,
                model_used=self.model_name,
                raw_response=f"error: {exc}",
            )
