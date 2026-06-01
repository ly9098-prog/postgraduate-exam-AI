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
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_ocr_instance = None


_OCR_MAX_SIDE = 3000
_OCR_MIN_WIDTH = 1000
_OCR_DEPENDENCY_ERROR = "OCR 依赖未安装：paddleocr，请先安装 requirements-ocr.txt"


@dataclass
class OcrPageResult:
    page_index: int
    text: str
    boxes: list[dict] | None = field(default=None)


@dataclass
class OcrCandidateResult:
    result: Any
    image_size: tuple[int, int]


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


def _load_ocr_image(image_bytes: bytes):
    import io

    from PIL import Image, ImageOps

    return ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes))).convert("RGB")


def _resize_for_ocr(img):
    from PIL import Image

    width, height = img.size
    if width < _OCR_MIN_WIDTH:
        scale = min(_OCR_MIN_WIDTH / width, _OCR_MAX_SIDE / height)
        if scale > 1:
            img = img.resize((int(width * scale), int(height * scale)), Image.Resampling.LANCZOS)
    return img


def _foreground_mask(img, max_side: int = 1200):
    import numpy as np
    from PIL import ImageOps

    gray = ImageOps.autocontrast(img.convert("L"), cutoff=1)
    width, height = gray.size
    scale = min(1.0, max_side / max(width, height))
    if scale < 1:
        gray = gray.resize((max(1, int(width * scale)), max(1, int(height * scale))))

    arr = np.asarray(gray, dtype=np.float32)
    if arr.size == 0:
        return arr.astype(bool), scale
    background = float(np.percentile(arr, 92))
    threshold = max(12.0, float(arr.std()) * 0.35)
    return arr < background - threshold, scale


def _content_bbox_from_luma(img) -> tuple[int, int, int, int] | None:
    import numpy as np

    mask, scale = _foreground_mask(img)
    if mask.size == 0 or mask.mean() < 0.0005:
        return None

    height, width = mask.shape
    row_threshold = max(2, int(width * 0.002))
    col_threshold = max(2, int(height * 0.002))
    rows = np.where(mask.sum(axis=1) > row_threshold)[0]
    cols = np.where(mask.sum(axis=0) > col_threshold)[0]
    if len(rows) == 0 or len(cols) == 0:
        return None

    inv_scale = 1 / scale if scale else 1
    left = int(cols[0] * inv_scale)
    top = int(rows[0] * inv_scale)
    right = int((cols[-1] + 1) * inv_scale)
    bottom = int((rows[-1] + 1) * inv_scale)
    return left, top, right, bottom


def _crop_blank_margins(img):
    bbox = _content_bbox_from_luma(img)
    if bbox is None:
        return img

    width, height = img.size
    left, top, right, bottom = bbox
    content_width = right - left
    content_height = bottom - top
    if content_width * content_height < width * height * 0.08:
        return img

    pad_x = max(12, int(width * 0.02))
    pad_y = max(12, int(height * 0.02))
    crop_box = (
        max(0, left - pad_x),
        max(0, top - pad_y),
        min(width, right + pad_x),
        min(height, bottom + pad_y),
    )
    cropped_area = (crop_box[2] - crop_box[0]) * (crop_box[3] - crop_box[1])
    if cropped_area > width * height * 0.95:
        return img
    return img.crop(crop_box)


def _projection_score(mask) -> float:
    import numpy as np

    if mask.size == 0:
        return 0.0
    rows = mask.sum(axis=1).astype(np.float32)
    if rows.size < 2:
        return 0.0
    return float(rows.var() + np.abs(np.diff(rows)).mean())


def _estimate_skew_angle(img) -> float:
    import numpy as np
    from PIL import Image

    mask, _ = _foreground_mask(img, max_side=900)
    if mask.size == 0 or mask.mean() < 0.001:
        return 0.0

    base_img = Image.fromarray((mask * 255).astype("uint8"), mode="L")
    best_angle = 0.0
    best_score = _projection_score(mask)
    zero_score = best_score

    for angle in [x * 0.5 for x in range(-10, 11) if x != 0]:
        rotated = base_img.rotate(angle, resample=Image.Resampling.BILINEAR, expand=True, fillcolor=0)
        score = _projection_score(np.asarray(rotated, dtype=np.uint8) > 0)
        if score > best_score:
            best_angle = angle
            best_score = score

    if best_score < zero_score * 1.08 or abs(best_angle) < 0.3:
        return 0.0
    return best_angle


def _deskew_image(img):
    from PIL import Image

    angle = _estimate_skew_angle(img)
    if not angle:
        return img
    rotated = img.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="white")
    return _crop_blank_margins(rotated)


def _estimate_image_quality(img) -> dict[str, float]:
    import numpy as np
    from PIL import ImageFilter

    gray = img.convert("L")
    arr = np.asarray(gray, dtype=np.float32)
    if arr.size == 0:
        return {"brightness": 255.0, "contrast": 0.0, "noise": 0.0, "sharpness": 0.0}

    median = np.asarray(gray.filter(ImageFilter.MedianFilter(size=3)), dtype=np.float32)
    gy = np.abs(arr[1:, :] - arr[:-1, :]).mean() if arr.shape[0] > 1 else 0.0
    gx = np.abs(arr[:, 1:] - arr[:, :-1]).mean() if arr.shape[1] > 1 else 0.0
    return {
        "brightness": float(arr.mean()),
        "contrast": float(arr.std()),
        "noise": float(np.abs(arr - median).mean()),
        "sharpness": float(gx + gy),
    }


def _choose_preprocessing_strategy(quality: dict[str, float]) -> set[str]:
    strategy = {"autocontrast"}
    if quality["noise"] > 6 and quality["contrast"] > 15:
        strategy.add("denoise")
    if quality["sharpness"] < 14 and quality["noise"] < 8:
        strategy.add("sharpen")
    return strategy


def _apply_quality_strategy(img, strategy: set[str]):
    from PIL import ImageFilter, ImageOps

    if "denoise" in strategy:
        img = img.filter(ImageFilter.MedianFilter(size=3))
    if "sharpen" in strategy:
        img = img.filter(ImageFilter.UnsharpMask(radius=1, percent=120, threshold=3))
    if "autocontrast" in strategy:
        img = ImageOps.autocontrast(img.convert("L"), cutoff=1).convert("RGB")
    return img


def _prepare_ocr_image(image_bytes: bytes):
    img = _load_ocr_image(image_bytes)
    img = _crop_blank_margins(img)
    img = _deskew_image(img)
    img = _resize_for_ocr(img)
    quality = _estimate_image_quality(img)
    strategy = _choose_preprocessing_strategy(quality)
    return _apply_quality_strategy(img, strategy)


def _image_to_array(img):
    import numpy as np

    return np.array(img)


def _normalize_ocr_result(result: Any) -> list:
    if not result or result[0] is None:
        return []
    return result[0]


def _score_ocr_result(result: Any) -> float:
    lines = _normalize_ocr_result(result)
    if not lines:
        return 0.0

    texts: list[str] = []
    confidences: list[float] = []
    for line in lines:
        if not line or len(line) < 2 or not line[1]:
            continue
        text = str(line[1][0] or "")
        conf = float(line[1][1]) if len(line[1]) > 1 else 1.0
        if text.strip():
            texts.append(text)
            confidences.append(conf)

    if not texts:
        return 0.0

    joined = "".join(texts)
    meaningful = len(re.findall(r"[A-Za-z0-9一-鿿∀-⋿]", joined))
    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
    garbage_ratio = 1 - (meaningful / max(1, len(joined)))
    return (len(texts) * 2.0 + meaningful * 0.15) * avg_conf * max(0.2, 1 - garbage_ratio)


def _ocr_score_is_good(result: Any) -> bool:
    lines = _normalize_ocr_result(result)
    chars = sum(len(str(line[1][0] or "")) for line in lines if line and line[1])
    return len(lines) >= 3 and chars >= 30 and _score_ocr_result(result) >= 8


def _rotate_image_for_ocr(img, degrees: int):
    from PIL import Image

    return img.rotate(degrees, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="white")


def _ocr_prepared_image(ocr, img) -> Any:
    return ocr.ocr(_image_to_array(img), cls=True)


def _ocr_with_rotation_candidates(ocr, image_bytes: bytes) -> OcrCandidateResult:
    img = _prepare_ocr_image(image_bytes)
    result = _ocr_prepared_image(ocr, img)
    if _ocr_score_is_good(result):
        return OcrCandidateResult(result=result, image_size=img.size)

    best_result = result
    best_score = _score_ocr_result(result)
    best_size = img.size
    initial_score = best_score
    for degrees in (90, 180, 270):
        candidate_img = _rotate_image_for_ocr(img, degrees)
        candidate = _ocr_prepared_image(ocr, candidate_img)
        candidate_score = _score_ocr_result(candidate)
        if candidate_score > best_score:
            best_result = candidate
            best_score = candidate_score
            best_size = candidate_img.size

    if best_score >= max(3.0, initial_score * 1.5):
        return OcrCandidateResult(result=best_result, image_size=best_size)
    return OcrCandidateResult(result=result, image_size=img.size)


def _extract_ocr_lines(result: Any) -> list[dict]:
    extracted: list[dict] = []
    for line in _normalize_ocr_result(result):
        if not line or len(line) < 2 or not line[1]:
            continue
        pts = line[0]
        x0 = min(p[0] for p in pts)
        y0 = min(p[1] for p in pts)
        x1 = max(p[0] for p in pts)
        y1 = max(p[1] for p in pts)
        text = str(line[1][0] or "")
        conf = float(line[1][1]) if len(line[1]) > 1 else 1.0
        extracted.append({
            "text": text,
            "conf": conf,
            "bbox": [x0, y0, x1, y1],
            "cx": (x0 + x1) / 2,
            "cy": (y0 + y1) / 2,
            "width": x1 - x0,
            "height": y1 - y0,
        })
    return extracted


def _detect_column_split(lines: list[dict], image_width: int) -> float | None:
    candidates = [line for line in lines if line["width"] < image_width * 0.65]
    if len(candidates) < 6:
        return None

    split = image_width / 2
    left = [line for line in candidates if line["cx"] < split]
    right = [line for line in candidates if line["cx"] >= split]
    if len(left) < 3 or len(right) < 3:
        return None

    left_y = (min(line["cy"] for line in left), max(line["cy"] for line in left))
    right_y = (min(line["cy"] for line in right), max(line["cy"] for line in right))
    overlap = min(left_y[1], right_y[1]) - max(left_y[0], right_y[0])
    if overlap <= 0:
        return None

    left_max = max(line["bbox"][2] for line in left)
    right_min = min(line["bbox"][0] for line in right)
    gap = right_min - left_max
    if gap < image_width * 0.04:
        return None
    return (left_max + right_min) / 2


def _order_ocr_lines_reading_order(
    lines: list[dict], image_width: int, image_height: int
) -> list[dict]:
    if len(lines) < 2:
        return lines

    split = _detect_column_split(lines, image_width)
    if split is None:
        return sorted(lines, key=lambda line: (line["cy"], line["cx"]))

    full_width = [line for line in lines if line["width"] >= image_width * 0.65]
    column_lines = [line for line in lines if line not in full_width]
    left = sorted([line for line in column_lines if line["cx"] < split], key=lambda line: (line["cy"], line["cx"]))
    right = sorted([line for line in column_lines if line["cx"] >= split], key=lambda line: (line["cy"], line["cx"]))

    top_cutoff = min((line["cy"] for line in column_lines), default=0)
    bottom_cutoff = max((line["cy"] for line in column_lines), default=image_height)
    before = sorted([line for line in full_width if line["cy"] <= top_cutoff], key=lambda line: (line["cy"], line["cx"]))
    after = sorted([line for line in full_width if line["cy"] > bottom_cutoff], key=lambda line: (line["cy"], line["cx"]))
    middle = sorted(
        [line for line in full_width if top_cutoff < line["cy"] <= bottom_cutoff],
        key=lambda line: (line["cy"], line["cx"]),
    )
    return before + left + right + middle + after


def _image_to_ocr_array(image_bytes: bytes):
    return _image_to_array(_prepare_ocr_image(image_bytes))


def _ocr_one_page(page_png: bytes, page_index: int) -> tuple[int, str]:
    """对单页图片执行 OCR，返回 (page_index, text)。失败返回空字符串。"""
    try:
        ocr = _get_ocr()
        candidate = _ocr_with_rotation_candidates(ocr, page_png)
        lines = _order_ocr_lines_reading_order(
            _extract_ocr_lines(candidate.result),
            candidate.image_size[0],
            candidate.image_size[1],
        )
        if not lines:
            logger.info("OCR 第 %d 页未检测到文本行", page_index)
            return page_index, ""
        text_lines = [line["text"] for line in lines if line["text"].strip()]
        logger.info("OCR 第 %d 页识别到 %d 行文本", page_index, len(text_lines))
        return page_index, "\n".join(text_lines)
    except RuntimeError:
        raise
    except Exception as e:
        logger.warning("OCR 第 %d 页失败：%s", page_index, e)
        return page_index, ""


def _ocr_one_page_with_boxes(page_png: bytes, page_index: int) -> tuple[int, str, list[dict]]:
    """对单页图片执行 OCR，返回 (page_index, text, boxes)。失败返回空。"""
    try:
        ocr = _get_ocr()
        candidate = _ocr_with_rotation_candidates(ocr, page_png)
        ordered = _order_ocr_lines_reading_order(
            _extract_ocr_lines(candidate.result),
            candidate.image_size[0],
            candidate.image_size[1],
        )
        if not ordered:
            return page_index, "", []
        lines = [line["text"] for line in ordered if line["text"].strip()]
        boxes = [{"bbox": line["bbox"], "conf": line["conf"]} for line in ordered]
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
