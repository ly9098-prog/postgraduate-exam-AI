"""Backward compatibility wrapper for the former DeepSeek OCR fixer."""

from app.features.ocr_fix.openai_compatible_adapter import OpenAICompatibleFixer


class DeepSeekFixer(OpenAICompatibleFixer):
    """Deprecated alias. Use :class:`OpenAICompatibleFixer`."""

    adapter_name = "openai-compatible"
