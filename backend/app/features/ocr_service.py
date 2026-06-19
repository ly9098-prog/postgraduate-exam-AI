"""OCR 增强服务 — 扫描版 PDF 图片文字识别。

通过 AI 视觉模型识别扫描版 PDF 中的文字，输出与 raw_blocks 兼容的格式，
无缝接入现有 ImportTextNormalizer → Pipeline 流程。

触发条件：PyMuPDF 提取文本 < 100 字符 + OCR_ENABLED=True。
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

_MIN_TEXT_LENGTH = 100  # 扫描版检测阈值（字符数）
_OCR_DPI = 200          # PDF 渲染 DPI
_OCR_MAX_TOKENS = 4096  # 单页 OCR 最大输出 token


def is_ocr_enabled() -> bool:
    """OCR 功能是否启用（通过环境变量 OCR_ENABLED 控制）。"""
    return bool(settings.OCR_ENABLED)


# ---------------------------------------------------------------------------
# reserved interfaces (Stage 9+)
# ---------------------------------------------------------------------------


def ocr_math_formula(image: bytes) -> str:
    """数学公式识别接口（预留）。"""
    raise NotImplementedError("数学公式 OCR 暂未实现")


def ocr_table(image: bytes) -> list[list[str]]:
    """表格识别接口（预留）。

    图像级表格 OCR 暂未实现。文本级 LaTeX tabular 解析请使用
    app.services.formula_normalizer.parse_latex_table / extract_tables_from_text。
    """
    raise NotImplementedError("表格 OCR 暂未实现，文本级解析见 formula_normalizer")


# ---------------------------------------------------------------------------
# scanned PDF detection
# ---------------------------------------------------------------------------


def is_scanned_pdf(content: bytes, min_text_length: int = _MIN_TEXT_LENGTH) -> bool:
    """检测是否为扫描版 PDF（无可复制文本层）。

    使用 PyMuPDF 提取文本，若总字符数 < min_text_length 则判定为扫描版。
    """
    try:
        import fitz
    except ImportError:
        logger.warning("PyMuPDF 未安装，无法检测扫描版 PDF")
        return False

    try:
        doc = fitz.open(stream=content, filetype="pdf")
        total_text = ""
        try:
            for page in doc:
                total_text += page.get_text()
        finally:
            doc.close()
        return len(total_text.strip()) < min_text_length
    except Exception as exc:
        logger.warning("扫描版 PDF 检测失败: %s", exc)
        return False


# ---------------------------------------------------------------------------
# PDF → image conversion
# ---------------------------------------------------------------------------


def _pdf_to_images(content: bytes, dpi: int = _OCR_DPI) -> list[dict]:
    """PDF 每页渲染为 PNG 图片。

    Returns:
        [{"page": int, "image": bytes, "format": "png"}, ...]
    """
    import fitz

    doc = fitz.open(stream=content, filetype="pdf")
    images: list[dict] = []
    try:
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=dpi)
            images.append({
                "page": i + 1,
                "image": pix.tobytes("png"),
                "format": "png",
            })
    finally:
        doc.close()

    if not images:
        raise ValueError("PDF 中没有可渲染的页面")

    return images


# ---------------------------------------------------------------------------
# AI OCR call
# ---------------------------------------------------------------------------


async def _call_ocr_api(image: bytes, page_num: int) -> dict | None:
    """调用 AI 视觉模型识别单页图片文字。

    Returns:
        {"page": int, "text": str, "confidence": float, "tokens_used": int} | None
    """
    from app.ai.client import deepseek

    if not deepseek.is_available():
        logger.warning("DeepSeek API 不可用，跳过 OCR")
        return None

    image_b64 = base64.b64encode(image).decode("ascii")

    messages = [
        {
            "role": "system",
            "content": (
                "你是一个 OCR 文字识别助手。请准确提取图片中的所有文字内容，"
                "保留原始格式和排版。对于数学公式，请用 LaTeX 格式输出"
                "（行内公式用 $...$，块级公式用 $$...$$）。"
                "禁止添加额外解释或评论，只输出识别到的文字内容。"
            ),
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": f"请逐字识别第 {page_num} 页中的所有文字，保留段落结构和公式格式。",
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{image_b64}",
                        "detail": "high",
                    },
                },
            ],
        },
    ]

    # DeepSeek 当前无多模态 API 模型，视觉 OCR 暂不可用
    # 待接入支持 vision 的模型后恢复
    payload = {
        "model": "",
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": _OCR_MAX_TOKENS,
    }

    start = time.monotonic()
    try:
        resp = await deepseek.client.post(
            f"{deepseek.base_url}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {deepseek.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)

        if resp.status_code != 200:
            logger.warning(
                "OCR API 返回 %d (page %d): %s",
                resp.status_code, page_num, resp.text[:300],
            )
            return None

        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        tokens = data["usage"]["total_tokens"]

        logger.info("OCR page %d: %d tokens, %dms", page_num, tokens, elapsed_ms)
        return {
            "page": page_num,
            "text": content.strip(),
            "confidence": 0.85,
            "tokens_used": tokens,
        }
    except Exception as exc:
        logger.warning("OCR API 调用异常 (page %d): %s", page_num, exc)
        return None


# ---------------------------------------------------------------------------
# main OCR fallback
# ---------------------------------------------------------------------------


def ocr_fallback(content: bytes, source_file: str = "") -> list[dict]:
    """扫描版 PDF OCR 识别主入口。

    将 PDF 每页渲染为图片，调用 AI 视觉模型识别文字，
    返回与 _extract_pdf_blocks 兼容的 raw_blocks 格式。

    Args:
        content: PDF 文件原始字节
        source_file: 原始文件名（仅用于日志）

    Returns:
        [{"page": int, "block_index": int, "text": str}, ...]

    Raises:
        ValueError: PDF 渲染或 OCR 全部失败
    """
    if not is_ocr_enabled():
        raise RuntimeError("OCR 功能未启用（OCR_ENABLED=false）")

    images = _pdf_to_images(content)

    async def _run_batch():
        tasks = [
            _call_ocr_api(img["image"], img["page"])
            for img in images
        ]
        return await asyncio.gather(*tasks)

    try:
        results = asyncio.run(_run_batch())
    except RuntimeError as exc:
        # asyncio.run 在已有 event loop 时会抛 RuntimeError
        logger.warning("无法在当前事件循环中运行 OCR，尝试新建事件循环: %s", exc)
        try:
            loop = asyncio.new_event_loop()
            results = loop.run_until_complete(_run_batch())
            loop.close()
        except Exception:
            raise RuntimeError(f"OCR 执行失败: {exc}") from exc
    except Exception as exc:
        logger.exception("OCR 批量调用失败")
        raise RuntimeError(f"OCR 调用异常: {exc}") from exc

    blocks: list[dict] = []
    failed_pages = 0

    for i, result in enumerate(results):
        if result is None or not result.get("text"):
            failed_pages += 1
            logger.warning("OCR 第 %d 页失败，跳过", images[i]["page"])
            continue

        text = result["text"]
        # 按双换行切分段落，每个段落作为一个 block
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if not paragraphs:
            paragraphs = [text]

        for j, para in enumerate(paragraphs):
            blocks.append({
                "page": result["page"],
                "block_index": len(blocks),
                "text": para,
            })

    if not blocks:
        raise RuntimeError(
            f"所有 {len(images)} 页 OCR 均失败"
            + (f"（{failed_pages} 页无结果）" if failed_pages else "")
        )

    if failed_pages:
        logger.warning(
            "%d/%d 页 OCR 失败，已跳过", failed_pages, len(images),
        )

    logger.info(
        "OCR 完成: %d 页 → %d blocks (源文件: %s)",
        len(images), len(blocks), source_file or "未知",
    )
    return blocks
