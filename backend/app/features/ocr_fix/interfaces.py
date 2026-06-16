"""OCR 纠错统一接口定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class OCRFixResult:
    """OCR 纠错结果。"""

    fixed_text: str
    confidence: float | None = None
    model_used: str = "unknown"
    raw_response: str | None = None
    tokens_used: int | None = None
    duration_ms: int | None = None


@runtime_checkable
class OCRFixerProtocol(Protocol):
    """所有 OCR 纠错模型必须实现的接口。"""

    async def fix(
        self,
        image: bytes | None = None,
        ocr_text: str = "",
        context: dict[str, Any] | None = None,
    ) -> OCRFixResult:
        """对 OCR 文本进行纠错。

        Args:
            image: 原始图片字节（可选，视觉模型需要）。
            ocr_text: OCR 识别出的原始文本。
            context: 额外上下文（如 page_num, config 等）。

        Returns:
            OCRFixResult 包含纠错后的文本。
        """
        ...
