"""OCR service：基于 PaddleOCR 的扫描版 PDF 识别。

设计原则：
- OCR 实例单例化，使用双重检查锁避免并发初始化
- PaddleOCR 初始化以及推理调用串行化（threading.Lock）
- CPU 推理禁用 MKLDNN、单线程（防止 C++ 多线程冲突导致 SIGSEGV）
- 启动自检：初始化后立即执行健康检查，失败则标记引擎不可用
- 失败降级：OCR 引擎初始化失败时返回清晰错误，不静默崩溃
"""
import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

# 低置信度行过滤阈值（0.0–1.0），不含 CJK 字符且置信度低于此值的行视为水印/噪声
# 可通过环境变量 OCR_LOW_CONF_THRESHOLD 覆盖
_OCR_LOW_CONF_THRESHOLD: float = float(
    os.environ.get("OCR_LOW_CONF_THRESHOLD", "0.55")
)

from app.core.config import settings
from app.core.ocr_profile import get_ocr_profile

logger = logging.getLogger(__name__)

try:
    from app.core.log_context import log_event
except ImportError:  # pragma: no cover
    def log_event(_lg, _ev, **_kw):  # type: ignore[misc]
        pass

# ── 全局状态 ──────────────────────────────────────────────────────────────
_ocr_instance = None
_ocr_init_lock = threading.Lock()       # 保护 PaddleOCR 初始化（只初始化一次）
_ocr_inference_lock = threading.Lock()  # 串行化推理调用（单线程 paddle inference）
_ocr_init_error: str | None = None      # 初始化失败时记录错误消息，后续不再重试
_ocr_initialized: bool = False

_OCR_MAX_SIDE = 3000
_OCR_DEPENDENCY_ERROR = "OCR 依赖未安装：paddleocr，请先安装 requirements-ocr.txt"

# P2-6: OCR 缓存统计
_ocr_cache_hits = 0
_ocr_cache_misses = 0


@dataclass
class OcrPageResult:
    page_index: int
    text: str
    boxes: list[dict] | None = field(default=None)
    failed: bool = False
    error: str | None = None


@dataclass
class OcrCandidateResult:
    result: Any
    image_size: tuple[int, int]


def _get_ocr():
    """懒加载 PaddleOCR 单例，使用双重检查锁避免并发初始化。

    初始化失败时会记录到 _ocr_init_error，后续所有调用直接抛出，
    不再重试，避免重复 SIGSEGV。
    """
    global _ocr_instance, _ocr_init_error, _ocr_initialized

    if _ocr_init_error:
        raise RuntimeError(f"OCR 引擎初始化失败: {_ocr_init_error}")

    if _ocr_initialized:
        return _ocr_instance

    with _ocr_init_lock:
        if _ocr_initialized:
            return _ocr_instance

        try:
            from paddleocr import PaddleOCR  # 延迟导入，不影响未开启 OCR 的启动速度
        except ImportError as exc:
            _ocr_init_error = _OCR_DEPENDENCY_ERROR
            raise RuntimeError(_OCR_DEPENDENCY_ERROR) from exc

        profile = get_ocr_profile()
        try:
            _ocr_instance = PaddleOCR(
                use_angle_cls=True,
                lang=settings.OCR_LANGUAGE,
                use_gpu=profile.use_gpu,
                show_log=False,
                det_db_thresh=settings.OCR_DET_DB_THRESH,
                det_db_box_thresh=settings.OCR_DET_DB_BOX_THRESH,
                det_db_unclip_ratio=settings.OCR_DET_DB_UNCLIP_RATIO,
                drop_score=settings.OCR_DROP_SCORE,
                # 稳定性：关闭 MKLDNN + 单 CPU 线程，防止 C++ 多线程冲突
                use_mkldnn=False,
                cpu_threads=1,
            )
        except Exception as exc:
            _ocr_init_error = str(exc)
            logger.critical("PaddleOCR 初始化失败: %s", _ocr_init_error)
            raise RuntimeError(f"OCR 引擎初始化失败: {_ocr_init_error}") from exc

        # 启动自检：用一张纯白图片测试推理是否能正常完成
        _run_ocr_health_check(_ocr_instance)

        _ocr_initialized = True
        logger.info("PaddleOCR 初始化完成（use_gpu=%s, lang=%s, mkldnn=off, cpu_threads=1）",
                     profile.use_gpu, settings.OCR_LANGUAGE)
        log_event(
            logger, "ocr.engine.init", "info",
            use_gpu=profile.use_gpu, lang=settings.OCR_LANGUAGE,
        )

    return _ocr_instance


_HEALTH_CHECK_IMAGE: bytes | None = None


def _get_health_check_image() -> bytes:
    """生成一张 100×100 的纯白 PNG 用于 OCR 健康检查。

    缓存 PNG 字节以避免重复编码。
    """
    global _HEALTH_CHECK_IMAGE
    if _HEALTH_CHECK_IMAGE is not None:
        return _HEALTH_CHECK_IMAGE
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (100, 100), "white").save(buf, format="PNG")
    _HEALTH_CHECK_IMAGE = buf.getvalue()
    return _HEALTH_CHECK_IMAGE


def _run_ocr_health_check(ocr_instance) -> None:
    """用一张空白图片测试 PaddleOCR 推理，验证引擎初始化正常。

    如果推理抛出任何异常（含 SIGSEGV），则标记 _ocr_init_error 并
    阻止后续所有 OCR 调用。
    """
    global _ocr_init_error
    try:
        import numpy as np
        _ = ocr_instance.ocr(np.zeros((100, 100, 3), dtype=np.uint8), cls=True)
        logger.info("PaddleOCR 健康检查通过")
    except Exception as exc:
        _ocr_init_error = f"健康检查失败: {exc}"
        logger.critical("PaddleOCR 健康检查失败: %s", _ocr_init_error)
        raise RuntimeError(f"OCR 引擎初始化失败: {_ocr_init_error}") from exc


def _load_ocr_image(image_bytes: bytes):
    import io

    from PIL import Image, ImageOps

    return ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes))).convert("RGB")


def _resize_for_ocr(img):
    from PIL import Image

    min_width = get_ocr_profile().min_image_width
    width, height = img.size
    # Upscale small images to minimum width for better text detection
    if width < min_width:
        scale = min_width / width
        # Also respect max side constraint
        max_scale = _OCR_MAX_SIDE / max(width, height)
        scale = min(scale, max_scale)
        if scale > 1:
            img = img.resize((int(width * scale), int(height * scale)), Image.Resampling.LANCZOS)
    # Downscale if either dimension exceeds max
    width, height = img.size
    if max(width, height) > _OCR_MAX_SIDE:
        scale = _OCR_MAX_SIDE / max(width, height)
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
    """执行 OCR 推理，使用全局串行锁确保 C++ 推理不并发。"""
    with _ocr_inference_lock:
        return ocr.ocr(_image_to_array(img), cls=True)


def _ocr_with_rotation_candidates(ocr, image_bytes: bytes) -> OcrCandidateResult:
    try:
        img = _prepare_ocr_image(image_bytes)
        result = _ocr_prepared_image(ocr, img)
        if not get_ocr_profile().enable_rotation:
            return OcrCandidateResult(result=result, image_size=img.size)
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
    except RuntimeError as exc:
        logger.warning("OCR 预处理失败，回退到原始图片：%s", exc)
        fallback_img = _load_ocr_image(image_bytes)
        fallback_result = _ocr_prepared_image(ocr, fallback_img)
        return OcrCandidateResult(result=fallback_result, image_size=fallback_img.size)


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
    """Detect two-column layout from OCR line positions.

    Progressive threshold fallback: starts with strict 4% gap, relaxes to 2%/1%
    when the strict threshold rejects a layout that otherwise looks columnar.
    Absolute minimum gap of 12px prevents false positives on narrow images.
    """
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

    # Progressive thresholds: 4% → 2% → 1% of image width, minimum 12px
    for ratio in (0.04, 0.02, 0.01):
        if gap >= max(image_width * ratio, 12):
            return (left_max + right_min) / 2
    return None


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
        # 初始化失败（_get_ocr 抛出）直接透传，不静默吞掉
        raise
    except Exception as e:
        logger.warning("OCR 第 %d 页失败：%s", page_index, e)
        return page_index, ""


def _ocr_one_page_with_boxes(
    page_png: bytes, page_index: int, skip_rotation: bool = False,
) -> OcrPageResult:
    """对单页图片执行 OCR，返回含文本、检测框与失败状态的结果。

    P2-6: 优先查询 OCR 缓存，命中时跳过 PaddleOCR 调用。
    """
    # P2-6: 检查缓存
    from app.services.ocr_cache_service import get_cached, set_cached

    cached = get_cached(page_png)
    if cached is not None:
        global _ocr_cache_hits
        _ocr_cache_hits += 1
        logger.debug("OCR cache HIT page=%d: %d chars, %d boxes",
                      page_index, len(cached.text), len(cached.boxes))
        return OcrPageResult(
            page_index=page_index,
            text=cached.text,
            boxes=cached.boxes or [],
        )

    global _ocr_cache_misses
    _ocr_cache_misses += 1

    try:
        ocr = _get_ocr()
        if skip_rotation:
            img = _prepare_ocr_image(page_png)
            result = _ocr_prepared_image(ocr, img)
            candidate = OcrCandidateResult(result=result, image_size=img.size)
        else:
            candidate = _ocr_with_rotation_candidates(ocr, page_png)
        ordered = _order_ocr_lines_reading_order(
            _extract_ocr_lines(candidate.result),
            candidate.image_size[0],
            candidate.image_size[1],
        )
        if not ordered:
            return OcrPageResult(page_index=page_index, text="", boxes=[])
        # 低置信度行过滤：置信度 < 0.55 且不含 CJK 字符的行视为疑似水印/噪声
        # CJK 文本即便是较低置信度也保留（中文字符结构复杂，OCR 评分偏低是正常的）
        lines: list[str] = []
        boxes: list[dict] = []
        conf_sum = 0.0
        for line in ordered:
            text = line["text"].strip()
            if not text:
                continue
            conf = line.get("conf", 1.0)
            if conf < _OCR_LOW_CONF_THRESHOLD and not any("一" <= c <= "鿿" for c in text):
                logger.debug("OCR low-conf line filtered: conf=%.2f text=%.60s", conf, text)
                continue
            lines.append(text)
            boxes.append({"bbox": line["bbox"], "conf": conf})
            conf_sum += conf

        # P2-6: 写入 OCR 缓存
        result_text = "\n".join(lines)
        avg_conf = conf_sum / max(len(lines), 1) if lines else 0.0
        set_cached(page_png, result_text, boxes, avg_conf)

        return OcrPageResult(page_index=page_index, text=result_text, boxes=boxes)
    except Exception as e:
        logger.warning("OCR（含框）第 %d 页失败：%s", page_index, e)
        return OcrPageResult(page_index=page_index, text="", boxes=[], failed=True, error=str(e))


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

    # 提前检查 OCR 可用性，避免线程池提交后全部失败
    if not ocr_is_available():
        _get_ocr()  # 触发初始化，失败会抛 RuntimeError（含 _ocr_init_error）

    results: dict[int, str] = {}
    max_workers = get_ocr_profile().max_workers

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_ocr_one_page, png, idx): idx
            for idx, png in page_images
        }
        for future in as_completed(futures):
            page_idx = futures[future]
            try:
                idx, text = future.result()
                results[idx] = text
            except Exception as e:
                logger.warning("OCR 第 %d 页异常，跳过：%s", page_idx, e)
                results[page_idx] = ""

    return results


def ocr_pages_with_boxes(
    page_images: list[tuple[int, bytes]],
    skip_rotation: bool = False,
) -> dict[int, OcrPageResult]:
    """并发 OCR 多页，返回含检测框坐标的结果。

    旧接口 ocr_pages() 签名完全保留，本函数为新增独立方法。
    page_images: [(page_index, png_bytes), ...]
    返回 {page_index: OcrPageResult}
    """
    if not page_images:
        return {}

    # 提前检查 OCR 可用性，避免线程池提交后全部失败
    if not ocr_is_available():
        _get_ocr()  # 触发初始化，失败会抛 RuntimeError（含 _ocr_init_error）

    results: dict[int, OcrPageResult] = {}
    max_workers = get_ocr_profile().max_workers

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_ocr_one_page_with_boxes, png, idx, skip_rotation): idx
            for idx, png in page_images
        }
        for future in as_completed(futures):
            page_idx = futures[future]
            try:
                result = future.result()
                results[result.page_index] = result
            except Exception as e:
                logger.warning("OCR 第 %d 页异常，跳过：%s", page_idx, e)
                results[page_idx] = OcrPageResult(
                    page_index=page_idx,
                    text="",
                    boxes=[],
                    failed=True,
                    error=str(e),
                )

    return results


def clean_ocr_text(text: str, *, trace_id: str = "") -> str:
    """清洗 OCR 输出文本 — 委托给 text_normalizer.normalize_ocr_text()。

    保留此函数作为向后兼容入口。所有调用点共享同一套清洗规则。
    """
    from app.features.text_normalizer import normalize_ocr_text
    return normalize_ocr_text(text, trace_id=trace_id)


def ocr_is_available() -> bool:
    """返回 OCR 引擎是否已成功初始化且可用。

    调用方（pipeline_orchestrator、batch_image_import_service）
    在启动 OCR 前应检查此标记，不可用时直接降级而非调用 _get_ocr()。
    """
    return _ocr_initialized and _ocr_init_error is None


def get_ocr_init_error() -> str | None:
    """返回初始化错误消息（如有），用于前端/日志显示。"""
    return _ocr_init_error


def reset_ocr_engine() -> None:
    """重置 OCR 引擎状态（仅供管理员 API 或恢复脚本使用）。

    调用后下一次 _get_ocr() 会重新初始化 PaddleOCR。
    """
    global _ocr_instance, _ocr_initialized, _ocr_init_error
    with _ocr_init_lock:
        _ocr_instance = None
        _ocr_initialized = False
        _ocr_init_error = None
    logger.info("OCR 引擎已重置，下次调用将重新初始化")


def get_ocr_cache_stats() -> dict:
    """返回 OCR 缓存命中/未命中统计。"""
    return {
        "hits": _ocr_cache_hits,
        "misses": _ocr_cache_misses,
        "hit_rate": round(
            _ocr_cache_hits / (_ocr_cache_hits + _ocr_cache_misses), 4
        ) if (_ocr_cache_hits + _ocr_cache_misses) > 0 else 0.0,
    }
