"""可插拔多模型 OCR 纠错层。

提供统一接口 OCRFixer，各模型适配器实现该接口，
OCRFixRouter 根据 admin 配置自动路由和降级。
"""

from app.features.ocr_fix.canonical_output import (
    OUTPUT_EMPTY,
    OUTPUT_JSON,
    OUTPUT_JSON_CODEBLOCK,
    OUTPUT_MARKDOWN,
    OUTPUT_MIXED,
    OUTPUT_PLAIN,
    canonicalize,
)
from app.features.ocr_fix.deepseek_adapter import DeepSeekFixer
from app.features.ocr_fix.interfaces import OCRFixResult, OCRFixerProtocol
from app.features.ocr_fix.qwen_adapter import QwenFixer
from app.features.ocr_fix.router import OCRFixRouter, STRATEGY_AUTO, STRATEGY_MANUAL
from app.features.ocr_fix.rule_adapter import RuleFixer

__all__ = [
    "OCRFixResult",
    "OCRFixerProtocol",
    "RuleFixer",
    "DeepSeekFixer",
    "QwenFixer",
    "OCRFixRouter",
    "STRATEGY_AUTO",
    "STRATEGY_MANUAL",
    # Canonical Output Layer
    "canonicalize",
    "OUTPUT_PLAIN",
    "OUTPUT_MARKDOWN",
    "OUTPUT_JSON",
    "OUTPUT_JSON_CODEBLOCK",
    "OUTPUT_MIXED",
    "OUTPUT_EMPTY",
]
