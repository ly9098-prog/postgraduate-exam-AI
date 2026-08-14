"""OpenAI-compatible text LLM OCR correction adapter."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from app.ai.client import llm
from app.features.ocr_fix.canonical_output import canonicalize
from app.features.ocr_fix.interfaces import OCRFixResult

logger = logging.getLogger(__name__)

try:
    from app.core.log_context import log_event
except ImportError:  # pragma: no cover
    def log_event(_lg, _ev, **_kw):  # type: ignore[misc]
        pass


class OpenAICompatibleFixer:
    """Use a configured OpenAI-compatible text model to correct OCR text."""

    adapter_name = "openai-compatible"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model_name: str | None = None,
        provider: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._model_name = model_name
        self._provider = provider or "openai_compatible"
        self.config = config or {}

    @property
    def model_name(self) -> str:
        return self._model_name or "openai-compatible"

    @property
    def is_available(self) -> bool:
        return bool(self._api_key and self._base_url and self._model_name)

    async def fix(
        self,
        image: bytes | None = None,
        ocr_text: str = "",
        context: dict[str, Any] | None = None,
    ) -> OCRFixResult:
        if not ocr_text.strip():
            return OCRFixResult(fixed_text=ocr_text, model_used=self.model_name)

        if not self.is_available:
            return OCRFixResult(
                fixed_text=ocr_text,
                confidence=None,
                model_used=self.model_name,
                raw_response="openai-compatible llm unavailable",
            )

        from app.ai.prompts import build_ocr_correction

        messages = build_ocr_correction(ocr_text)
        start = time.monotonic()
        log_event(
            logger,
            "ocr.fix.adapter.start",
            "info",
            adapter=self.adapter_name,
            provider=self._provider,
            model=self.model_name,
            ocr_text_chars=len(ocr_text),
        )
        try:
            result = await llm.chat(
                messages,
                temperature=0.1,
                model=self._model_name,
                api_key=self._api_key,
                base_url=self._base_url,
                provider=self._provider,
            )
            duration_ms = int((time.monotonic() - start) * 1000)

            corrected_raw = (result.get("content") or "").strip()
            corrected, _meta = canonicalize(corrected_raw, model_name=self.model_name)
            if not corrected:
                return OCRFixResult(
                    fixed_text=ocr_text,
                    model_used=self.model_name,
                    duration_ms=duration_ms,
                )

            original_len = len(ocr_text)
            if len(corrected) > original_len * 2 or len(corrected) < original_len * 0.5:
                return OCRFixResult(
                    fixed_text=ocr_text,
                    model_used=self.model_name,
                    duration_ms=duration_ms,
                    raw_response="output length out of bounds",
                )

            try:
                from app.features.code_integrity import detect_code_block_integrity

                original_code = detect_code_block_integrity(ocr_text)
                fixed_code = detect_code_block_integrity(corrected)
                if (
                    "code_garbled_text" in original_code.get("flags", [])
                    and "code_garbled_text" in fixed_code.get("flags", [])
                ):
                    original_score = original_code.get("score", 1.0)
                    fixed_score = fixed_code.get("score", 1.0)
                    if fixed_score >= original_score * 0.8:
                        logger.warning(
                            "LLM garbled code persisted: score %.2f->%.2f, reverting",
                            original_score,
                            fixed_score,
                        )
                        return OCRFixResult(
                            fixed_text=ocr_text,
                            model_used=self.model_name,
                            duration_ms=duration_ms,
                            raw_response="garbled_text_persists",
                        )
            except Exception:
                logger.warning("LLM garbled code check failed", exc_info=True)

            has_question_number = bool(
                re.search(r"^\s*\d+\s*[.．、]", ocr_text, re.MULTILINE)
            )
            first_line = corrected.split("\n")[0].strip()
            starts_with_option = bool(re.match(r"^[A-D]\s*[.．、:：)）]\s*", first_line))
            if (
                has_question_number
                and starts_with_option
                and not re.search(r"^\s*\d+\s*[.．、]", corrected, re.MULTILINE)
            ):
                logger.warning("LLM OCR correction dropped question stem; reverting")
                return OCRFixResult(
                    fixed_text=ocr_text,
                    model_used=self.model_name,
                    duration_ms=duration_ms,
                    raw_response="stem lost in correction",
                )

            log_event(
                logger,
                "ocr.fix.adapter.finish",
                "info",
                adapter=self.adapter_name,
                provider=self._provider,
                model=self.model_name,
                duration_ms=duration_ms,
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
            logger.warning("OpenAI-compatible OCR fix failed: %s", exc)
            log_event(
                logger,
                "ocr.fix.adapter.error",
                "error",
                adapter=self.adapter_name,
                provider=self._provider,
                model=self.model_name,
                error_type=type(exc).__name__,
                error_message=str(exc)[:200],
            )
            return OCRFixResult(
                fixed_text=ocr_text,
                model_used=self.model_name,
                raw_response=f"error: {exc}",
            )
