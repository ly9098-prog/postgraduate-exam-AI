"""本地规则兜底适配器 — 保留现有 AIOCR 纠错逻辑。"""

from __future__ import annotations

import logging
from typing import Any

from app.features.ocr_fix.interfaces import OCRFixResult

logger = logging.getLogger(__name__)


class RuleFixer:
    """本地规则兜底：保留现有 correct_ocr_blocks 检测逻辑，
    但不调用 AI，仅依靠规则修复。

    作为最后兜底，当所有 AI 模型都不可用或全部降级时使用。
    """

    model_name = "rule_fallback"

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    async def fix(
        self,
        image: bytes | None = None,
        ocr_text: str = "",
        context: dict[str, Any] | None = None,
    ) -> OCRFixResult:
        """纯规则纠错 — 不调用 AI。

        在现有系统中 rule 层不做实际修改（仅保留检测逻辑），
        因为实际的规则修复已在 text_normalizer 中完成。
        这里主要返回 noop 结果，供 pipeline 统计。
        """
        return OCRFixResult(
            fixed_text=ocr_text,
            confidence=None,
            model_used=self.model_name,
        )
