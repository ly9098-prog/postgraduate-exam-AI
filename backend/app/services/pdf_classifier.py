"""PDF 页面类型分类器。

判断每一页是"可提取文本"还是"图片型（需要 OCR）"。
只负责分类，不负责提取文本或 OCR。
"""
import fitz  # PyMuPDF

# 一页文本少于这个字符数，视为图片型页面
_TEXT_THRESHOLD = 30


def classify_pages(pdf_bytes: bytes) -> list[dict]:
    """
    返回每页的分类结果：
    [
      {"page_index": 0, "needs_ocr": False, "text": "..."},
      {"page_index": 1, "needs_ocr": True,  "text": ""},
      ...
    ]
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    results: list[dict] = []

    for i, page in enumerate(doc):
        text = page.get_text().strip()
        needs_ocr = len(text) < _TEXT_THRESHOLD
        results.append({
            "page_index": i,
            "needs_ocr": needs_ocr,
            "text": text if not needs_ocr else "",
            # 仅图片型页面保存 page 对象引用（用于后续 OCR 转图）
            "_page": page if needs_ocr else None,
        })

    return results


def has_any_ocr_pages(classified: list[dict]) -> bool:
    return any(p["needs_ocr"] for p in classified)


def get_pixmap(page: fitz.Page, dpi: int = 150) -> bytes:
    """将 PDF 页面渲染为 PNG 字节，供 OCR 使用。dpi=150 平衡速度与精度。"""
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
    return pix.tobytes("png")
