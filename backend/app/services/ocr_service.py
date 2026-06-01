"""OCR service：基于 PaddleOCR 的扫描版 PDF 识别。

设计原则：
- OCR 实例单例化，避免重复初始化
- 并发处理多页，max_workers 可通过配置控制
- OCR 失败的页面跳过，不崩溃整体流程
- 提供 clean_ocr_text() 清洗乱码/断行
"""
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from app.core.config import settings

logger = logging.getLogger(__name__)

_ocr_instance = None


_OCR_MAX_SIDE = 3000
_OCR_DEPENDENCY_ERROR = "OCR 依赖未安装：paddleocr，请先安装 requirements-ocr.txt"


@dataclass
class OcrPageResult:
    page_index: int
    text: str
    boxes: list[dict] | None = field(default=None)


def _get_ocr():
    """懒加载 PaddleOCR 单例，避免重复初始化的高成本。"""
    global _ocr_instance
    if _ocr_instance is None:
        try:
            from paddleocr import PaddleOCR  # 延迟导入，不影响未开启 OCR 的启动速度
        except ImportError as exc:
            raise RuntimeError(_OCR_DEPENDENCY_ERROR) from exc

        _ocr_instance = PaddleOCR(
            use_angle_cls=True,
            lang=settings.OCR_LANGUAGE,
            use_gpu=settings.OCR_USE_GPU,
            show_log=False,
        )
    return _ocr_instance


def _prepare_ocr_image(image_bytes: bytes):
    import io

    from PIL import Image, ImageOps

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    width, height = img.size
    if width < 1000:
        scale = min(1000 / width, _OCR_MAX_SIDE / height)
        if scale > 1:
            img = img.resize((int(width * scale), int(height * scale)), Image.Resampling.LANCZOS)
    img = ImageOps.autocontrast(img.convert("L"), cutoff=1).convert("RGB")
    return img


def _image_to_ocr_array(image_bytes: bytes):
    import numpy as np

    return np.array(_prepare_ocr_image(image_bytes))


def _ocr_one_page(page_png: bytes, page_index: int) -> tuple[int, str]:
    """对单页图片执行 OCR，返回 (page_index, text)。失败返回空字符串。"""
    try:
        ocr = _get_ocr()
        result = ocr.ocr(_image_to_ocr_array(page_png), cls=True)
        if not result or result[0] is None:
            logger.info("OCR 第 %d 页未检测到文本行", page_index)
            return page_index, ""
        lines = [line[1][0] for line in result[0] if line and line[1]]
        logger.info("OCR 第 %d 页识别到 %d 行文本", page_index, len(lines))
        return page_index, "\n".join(lines)
    except RuntimeError:
        raise
    except Exception as e:
        logger.warning("OCR 第 %d 页失败：%s", page_index, e)
        return page_index, ""


def _ocr_one_page_with_boxes(page_png: bytes, page_index: int) -> tuple[int, str, list[dict]]:
    """对单页图片执行 OCR，返回 (page_index, text, boxes)。失败返回空。"""
    try:
        ocr = _get_ocr()
        result = ocr.ocr(_image_to_ocr_array(page_png), cls=True)
        if not result or result[0] is None:
            return page_index, "", []
        lines = []
        boxes = []
        for line in result[0]:
            if not line or not line[1]:
                continue
            lines.append(line[1][0])
            # line[0] 是四边形顶点列表 [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
            pts = line[0]
            x0 = min(p[0] for p in pts)
            y0 = min(p[1] for p in pts)
            x1 = max(p[0] for p in pts)
            y1 = max(p[1] for p in pts)
            conf = float(line[1][1]) if len(line[1]) > 1 else 1.0
            boxes.append({"bbox": [x0, y0, x1, y1], "conf": conf})
        return page_index, "\n".join(lines), boxes
    except RuntimeError:
        raise
    except Exception as e:
        logger.warning("OCR（含框）第 %d 页失败：%s", page_index, e)
        return page_index, "", []


def ocr_image(image_bytes: bytes) -> str:
    """对单张图片执行 OCR，返回识别文本。"""
    if not settings.OCR_ENABLED:
        raise RuntimeError("OCR 功能未启用（OCR_ENABLED=false）")
    if not image_bytes:
        raise ValueError("图片内容为空")

    _, text = _ocr_one_page(image_bytes, 1)
    if not text.strip():
        raise RuntimeError("图片 OCR 未识别到文本")
    return text


def ocr_pages(page_images: list[tuple[int, bytes]]) -> dict[int, str]:
    """
    并发 OCR 多页。
    page_images: [(page_index, png_bytes), ...]
    返回 {page_index: ocr_text}
    """
    if not page_images:
        return {}

    results: dict[int, str] = {}
    max_workers = settings.OCR_MAX_WORKERS

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_ocr_one_page, png, idx): idx
            for idx, png in page_images
        }
        for future in as_completed(futures):
            idx, text = future.result()
            results[idx] = text

    return results


def ocr_pages_with_boxes(
    page_images: list[tuple[int, bytes]],
) -> dict[int, OcrPageResult]:
    """并发 OCR 多页，返回含检测框坐标的结果。

    旧接口 ocr_pages() 签名完全保留，本函数为新增独立方法。
    page_images: [(page_index, png_bytes), ...]
    返回 {page_index: OcrPageResult}
    """
    if not page_images:
        return {}

    results: dict[int, OcrPageResult] = {}
    max_workers = settings.OCR_MAX_WORKERS

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_ocr_one_page_with_boxes, png, idx): idx
            for idx, png in page_images
        }
        for future in as_completed(futures):
            idx, text, boxes = future.result()
            results[idx] = OcrPageResult(page_index=idx, text=text, boxes=boxes)

    return results


def clean_ocr_text(text: str) -> str:
    """清洗 OCR 输出文本：去乱码、合并断行、修复常见问题。"""
    if not text:
        return ""

    # 去除乱码字符（保留中文、ASCII 可打印字符、常用标点、数学符号）
    # U+2200-U+22FF: 数学运算符（∫∑∏√∞∈∉≤≥≠≈∂∇）
    # U+0370-U+03FF: 希腊字母（αβγπ等）
    text = re.sub(r"[^一-鿿　-〿＀-￯ -~Ͱ-Ͽ∀-⋿\n]", "", text)

    # 修复被错误断行的中文句子（如 "第\n一章" → "第一章"）
    # 行末是汉字且下行首也是汉字，则合并
    text = re.sub(
        r"([一-鿿，。；：！？])\n(?!((?:参考|正确)?\s*答案|解析|解答)\b)([一-鿿])",
        r"\1\3",
        text,
    )

    text = re.sub(
        r"(?<!\n)(?=(?:【)?(?:参考|正确)?答案(?:】)?\s*[：:])",
        "\n",
        text,
    )
    text = re.sub(r"\n((?:参考|正确)?)\n(答案\s*[：:])", r"\n\1\2", text)

    # 去除连续空格
    text = re.sub(r" {2,}", " ", text)

    # 去除连续空行（超过 2 个换行压缩为 2 个）
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 清理行首行尾空格
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines)

    return text.strip()
