"""通义千问视觉模型 OCR 纠错适配器。

对接通义千问视觉模型（Qwen-VL），
支持图片 + 文本联合纠错（OCR 纠错 + 图像理解）。
"""

from __future__ import annotations

import base64
import logging
import time
from typing import Any

import httpx

from app.features.ocr_fix.interfaces import OCRFixResult

logger = logging.getLogger(__name__)

_QWEN_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# 系统级 OCR 纠错 Prompt — 与 DeepSeek 版一致，要求模型专注提取文字
_OCR_SYSTEM_PROMPT = (
    "你是一个 OCR 文字识别纠错助手。请准确提取图片中的所有文字内容，"
    "保留原始格式和排版。对于数学公式，请用 LaTeX 格式输出"
    "（行内公式用 $...$，块级公式用 $$...$$）。"
    "修复 OCR 常见错误：错字、断行、选项错位、标点混用、题号缺失。"
    "禁止添加额外解释或评论，只输出识别到的文字内容。"
)


class QwenFixer:
    """通义千问视觉模型 OCR 纠错适配器。

    使用 Qwen-VL 系列模型的视觉能力，同时参考 OCR 文本结果进行纠错。
    """

    model_name = "qwen"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "qwen-vl-max",
        config: dict[str, Any] | None = None,
    ):
        self._api_key = api_key
        self._base_url = (base_url or _QWEN_DEFAULT_BASE_URL).rstrip("/")
        self._model = model
        self.config = config or {}

    @property
    def is_available(self) -> bool:
        return bool(self._api_key)

    async def fix(
        self,
        image: bytes | None = None,
        ocr_text: str = "",
        context: dict[str, Any] | None = None,
    ) -> OCRFixResult:
        if not self._api_key:
            return OCRFixResult(
                fixed_text=ocr_text,
                confidence=None,
                model_used=self.model_name,
                raw_response="qwen api_key not configured",
            )

        start = time.monotonic()
        try:
            corrected = await self._call_qwen(image, ocr_text, context)
            duration_ms = int((time.monotonic() - start) * 1000)

            if corrected is None:
                return OCRFixResult(
                    fixed_text=ocr_text,
                    model_used=self.model_name,
                    duration_ms=duration_ms,
                    raw_response="qwen returned empty",
                )

            return OCRFixResult(
                fixed_text=corrected,
                confidence=0.9,
                model_used=self.model_name,
                raw_response=corrected,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            logger.warning("Qwen OCR fix failed: %s", exc)
            return OCRFixResult(
                fixed_text=ocr_text,
                model_used=self.model_name,
                raw_response=f"error: {exc}",
            )

    async def _call_qwen(
        self,
        image: bytes | None,
        ocr_text: str,
        context: dict[str, Any] | None,
    ) -> str | None:
        """调用通义千问 API。"""
        messages = [
            {"role": "system", "content": _OCR_SYSTEM_PROMPT},
        ]

        user_content: list[dict] = []

        # 如果有图片，传入图片做视觉 OCR
        if image:
            image_b64 = base64.b64encode(image).decode("ascii")
            user_content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{image_b64}",
                    "detail": "high",
                },
            })

        # 传入 OCR 识别文本作为参考
        if ocr_text.strip():
            text_prompt = (
                f"以下为 OCR 识别的文本，请参考并结合图片进行纠错修正：\n\n{ocr_text}"
            )
            user_content.append({"type": "text", "text": text_prompt})
        else:
            user_content.append({
                "type": "text",
                "text": "请逐字识别图片中的所有文字，保留段落结构和公式格式。",
            })

        # 如果既无图片也无 OCR 文本，直接返回
        if not image and not ocr_text.strip():
            return None

        messages.append({"role": "user", "content": user_content})

        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": self.config.get("max_tokens", 4096),
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

            if resp.status_code != 200:
                logger.warning(
                    "Qwen API returned %d: %s",
                    resp.status_code, resp.text[:300],
                )
                return None

            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return content.strip()
