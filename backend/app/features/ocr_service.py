"""OCR 增强服务 — 扫描版 PDF 检测与图片转换工具。

提供扫描版 PDF 检测、PDF→图片渲染等基础设施函数。
PaddleOCR-VL 调用已收敛至 ocr_fix/router.py（唯一入口），
不再在此模块中直接调用。
"""

from __future__ import annotations

import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

_MIN_TEXT_LENGTH = 100  # 扫描版检测阈值（字符数）
_OCR_DPI = 200  # PDF 渲染 DPI


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


# ---------------------------------------------------------------------------
# OCR fallback — 已废弃，PaddleOCR-VL 调用收敛至 ocr_fix/router.py
# ---------------------------------------------------------------------------


def ocr_fallback(
    content: bytes, source_file: str = "", config: dict | None = None
) -> list[dict]:
    """扫描版 PDF OCR 识别（已废弃）。

    PaddleOCR-VL 调用已统一收敛至 ``ocr_fix/router.py``（通过 ocr_correction stage）。
    此函数不再直接调用 PaddleOCR-VL。

    Raises:
        NotImplementedError: 提示使用 pipeline 的 ocr_correction stage。
    """
    raise NotImplementedError(
        "ocr_fallback 已废弃 — PaddleOCR-VL 调用统一由 OCRFixRouter 处理。"
        "请使用 pipeline_orchestrator 的 ocr_correction stage。"
    )
