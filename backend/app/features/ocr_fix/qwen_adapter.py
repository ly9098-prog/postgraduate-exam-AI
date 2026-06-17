"""通义千问视觉模型 OCR 纠错适配器。

对接通义千问视觉模型（Qwen-VL），
支持图片 + 文本联合纠错（OCR 校验模式）。
"""

from __future__ import annotations

import base64
import io
import logging
import time
from typing import Any

import httpx

from app.features.ocr_fix.interfaces import OCRFixResult
from app.utils.sentry_utils import capture_exception, set_tag, start_span

logger = logging.getLogger(__name__)

_QWEN_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# OCR 校验模式 Prompt：Qwen-VL 根据图片核对并修正 PaddleOCR 结果
_OCR_VERIFY_PROMPT = (
    "你是专业 OCR 校验助手。我会提供：\n"
    "1. 原始图片\n"
    "2. PaddleOCR 识别结果\n\n"
    "你的任务不是重新 OCR，而是根据图片核对 OCR 结果并修正识别错误。\n\n"
    "规则：\n"
    "1. 图片与 OCR 一致时不要修改\n"
    "2. 不允许补充图片中不存在的内容\n"
    "3. 不允许解释或添加备注\n"
    "4. 不允许输出 Markdown 格式\n"
    "5. 只输出最终修正后的文本\n"
    "6. 保持原有换行结构\n"
    "7. 保持题目格式和选项顺序\n\n"
    "重点检查：\n"
    "- 数学公式（LaTeX 格式，行内 $...$，块级 $$...$$）\n"
    "- 编程代码（保持缩进）\n"
    "- 英文变量名（大小写敏感）\n"
    "- 特殊符号（∑ ∫ √ → ≤ ≥ ± ∞ 等）\n"
    "- 括号匹配（() [] {}）\n"
    "- 箭头符号（→ ← ↑ ↓ ⇒ ⇐ ↔）\n"
    "- 运算符（+ - × ÷ · = ≠ < > ≤ ≥）\n"
    "- 下标上标（H₂O, x² 等）\n"
    "- OCR 常见错字（方武→方式、导敖→导数 等）\n"
    "- OCR 选项混淆（8→B、0→D、6→G、l→1、O→0 等）"
)

_IMAGE_MAX_DIMENSION = 2048
_IMAGE_MAX_BYTES = 2 * 1024 * 1024  # 2MB


def _compress_image(image: bytes) -> bytes:
    """压缩过大图片：限制最长边 <= _IMAGE_MAX_DIMENSION，控制在 ~1.5MB 以内。"""
    try:
        from PIL import Image
        import io as io_module

        img = Image.open(io_module.BytesIO(image))
        w, h = img.size
        max_side = max(w, h)

        if max_side > _IMAGE_MAX_DIMENSION or len(image) > _IMAGE_MAX_BYTES:
            scale = min(_IMAGE_MAX_DIMENSION / max_side, 1.0)
            new_size = (int(w * scale), int(h * scale))
            img = img.resize(new_size, Image.LANCZOS)

            quality = 85
            for _ in range(3):
                buf = io_module.BytesIO()
                img.save(buf, format="PNG", optimize=True)
                compressed = buf.getvalue()
                if len(compressed) <= _IMAGE_MAX_BYTES:
                    return compressed
                quality -= 15

            return compressed
    except Exception as exc:
        logger.debug("Image compression failed, using original: %s", exc)
    return image


class QwenFixer:
    """通义千问视觉模型 OCR 纠错适配器。

    使用 Qwen-VL 的视觉能力，根据原始图片校验并修正 PaddleOCR 结果。
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

        if not image and not ocr_text.strip():
            return OCRFixResult(
                fixed_text=ocr_text,
                model_used=self.model_name,
            )

        with start_span(op="ai.qwen.fix", description=f"model={self._model}"):
            set_tag("ai.model", self._model)
            set_tag("ai.provider", "qwen")

            start = time.monotonic()
            try:
                corrected = await self._call_qwen(image, ocr_text, context)
                duration_ms = int((time.monotonic() - start) * 1000)
                set_tag("ai.duration_ms", duration_ms)

                if corrected is None:
                    capture_exception(
                        RuntimeError("Qwen returned empty"),
                        tags={"ai.model": self._model, "ai.provider": "qwen"},
                    )
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
                capture_exception(
                    exc,
                    tags={"ai.model": self._model, "ai.provider": "qwen"},
                )
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
        """调用通义千问 API（OCR 校验模式）。"""
        messages = [
            {"role": "system", "content": _OCR_VERIFY_PROMPT},
        ]

        user_content: list[dict] = []

        # 如果有图片，先压缩再传入
        compressed_image = _compress_image(image) if image else None
        if compressed_image:
            image_b64 = base64.b64encode(compressed_image).decode("ascii")
            user_content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{image_b64}",
                },
            })

        # 传入 OCR 结果供校验
        if ocr_text.strip():
            text_prompt = (
                "以下是 PaddleOCR 的识别结果，请根据图片核对并修正错误：\n\n"
                f"{ocr_text}"
            )
            user_content.append({"type": "text", "text": text_prompt})
        else:
            user_content.append({
                "type": "text",
                "text": "请根据图片提取所有文字内容，保留段落结构和公式格式。",
            })

        messages.append({"role": "user", "content": user_content})

        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": self.config.get("max_tokens", 4096),
        }

        timeout = self.config.get("qwen_timeout", 60.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
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
