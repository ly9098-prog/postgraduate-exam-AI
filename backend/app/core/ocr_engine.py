"""OcrEngine — 纯同步单页 OCR 引擎。

类设计，只在 worker 子进程中创建。API 主进程不初始化 PaddleOCR/CUDA。

输入: bytes + WorkerRequest
输出: WorkerResult（含 line-level text、polygon/bbox、confidence、transforms）

不含任何线程、进程或 async 逻辑。
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import re
import threading
from typing import Any

logger = logging.getLogger(__name__)

# ── 低置信度行过滤阈值 ─────────────────────────────────────────────────────
_LOW_CONF_THRESHOLD: float = float(
    os.environ.get("OCR_LOW_CONF_THRESHOLD", "0.55")
)

_OCR_MAX_SIDE = 3000


class OcrEngine:
    """纯同步 OCR 引擎。只在子进程中创建。

    Usage::

        engine = OcrEngine(config)
        result = engine.recognize(request)
    """

    def __init__(self, config: Any) -> None:
        """Initialize PaddleOCR instance (this runs IN the child process).

        Args:
            config: ``OcrRuntimeConfig`` frozen dataclass.
        """
        self._config = config
        self._lock = threading.Lock()  # serializes PaddleOCR C++ inference
        self._ocr = self._init_paddleocr()
        self._fingerprint = self._compute_fingerprint()
        logger.info(
            "OcrEngine initialized: use_gpu=%s lang=%s fingerprint=%s",
            config.use_gpu, config.language, self._fingerprint,
        )

    # ── Public API ──────────────────────────────────────────────────────────

    def recognize(
        self,
        image_bytes: bytes,
        page_index: int = 0,
        *,
        skip_rotation: bool = False,
        mode: str = "boxes",
    ) -> dict:
        """Run OCR on a single page.

        Pure sync — no threads, no async.

        Args:
            image_bytes: PNG/JPEG image bytes.
            page_index: Page number for logging.
            skip_rotation: Skip 90/180/270 rotation candidates.
            mode: "text" → text only, "boxes" → text+boxes+lines, "raw" → no preprocessing.

        Returns:
            Dict suitable for ``WorkerResult.result`` with keys:
            text, lines, boxes, confidence, transforms, coordinate_space,
            engine_fingerprint, page_index.
        """
        try:
            if mode == "raw":
                return self._recognize_raw(image_bytes, page_index)
            return self._recognize_with_boxes(image_bytes, page_index, skip_rotation)
        except Exception as exc:
            logger.warning("OcrEngine page %d failed: %s", page_index, exc)
            return {
                "page_index": page_index,
                "text": "",
                "lines": [],
                "boxes": [],
                "confidence": 0.0,
                "transforms": None,
                "coordinate_space": "image",
                "engine_fingerprint": self._fingerprint,
                "failed": True,
                "error": str(exc),
            }

    # ── Properties ─────────────────────────────────────────────────────────

    @property
    def fingerprint(self) -> str:
        return self._fingerprint

    @property
    def config(self) -> Any:
        return self._config

    # ── PaddleOCR init ──────────────────────────────────────────────────────

    def _init_paddleocr(self) -> Any:
        """Create and health-check a PaddleOCR instance."""
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise RuntimeError(
                "OCR 依赖未安装：paddleocr，请先安装 requirements-ocr.txt"
            ) from exc

        cfg = self._config
        ocr = PaddleOCR(
            use_angle_cls=True,
            lang=cfg.language,
            use_gpu=cfg.use_gpu,
            show_log=False,
            det_db_thresh=cfg.det_db_thresh,
            det_db_box_thresh=cfg.det_db_box_thresh,
            det_db_unclip_ratio=cfg.det_db_unclip_ratio,
            drop_score=cfg.drop_score,
            use_mkldnn=False,
            cpu_threads=1,
        )
        # Health check
        import numpy as np
        _ = ocr.ocr(np.zeros((100, 100, 3), dtype=np.uint8), cls=True)
        logger.info("PaddleOCR health check passed")
        return ocr

    def _compute_fingerprint(self) -> str:
        """Compute engine fingerprint from config for provenance tracking."""
        cfg = self._config
        raw = (
            f"lang={cfg.language}|gpu={cfg.use_gpu}|"
            f"det_thresh={cfg.det_db_thresh}|box_thresh={cfg.det_db_box_thresh}|"
            f"unclip={cfg.det_db_unclip_ratio}|drop={cfg.drop_score}|"
            f"min_w={cfg.min_image_width}|rotation={cfg.enable_rotation}"
        )
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    # ── Raw mode (no preprocessing) ─────────────────────────────────────────

    def _recognize_raw(self, image_bytes: bytes, page_index: int) -> dict:
        """OCR without preprocessing pipeline (for fast re-check)."""
        import numpy as np
        from PIL import Image

        pil_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img_array = np.array(pil_img)
        raw_results = self._ocr.ocr(img_array, cls=True)

        text_parts: list[str] = []
        all_lines: list[dict] = []
        all_boxes: list[dict] = []
        conf_sum = 0.0
        for line_group in raw_results or []:
            if line_group is None:
                continue
            for line_info in line_group:
                if not line_info or len(line_info) < 2 or not line_info[1]:
                    continue
                text = str(line_info[1][0] or "")
                conf = float(line_info[1][1]) if len(line_info[1]) > 1 else 1.0
                pts = line_info[0]
                x0 = min(p[0] for p in pts)
                y0 = min(p[1] for p in pts)
                x1 = max(p[0] for p in pts)
                y1 = max(p[1] for p in pts)
                text_parts.append(text)
                conf_sum += conf
                all_lines.append({
                    "text": text,
                    "polygon": [c for p in pts for c in p],
                    "bbox": [x0, y0, x1, y1],
                    "confidence": conf,
                })
                all_boxes.append({"bbox": [x0, y0, x1, y1], "conf": conf})

        joined = "\n".join(text_parts)
        return {
            "page_index": page_index,
            "text": joined,
            "lines": all_lines,
            "boxes": all_boxes,
            "confidence": conf_sum / max(len(all_lines), 1) if all_lines else 0.0,
            "transforms": None,
            "coordinate_space": "image",
            "engine_fingerprint": self._fingerprint,
            "failed": False,
            "error": None,
        }

    # ── Full pipeline mode ──────────────────────────────────────────────────

    def _recognize_with_boxes(
        self, image_bytes: bytes, page_index: int, skip_rotation: bool,
    ) -> dict:
        """Full OCR pipeline: preprocess → infer → postprocess."""
        from app.core.transform_tracker import TransformTracker

        tracker = TransformTracker()
        img = self._prepare_image(image_bytes, tracker)
        raw_result = self._infer(img)
        if not skip_rotation and self._config.enable_rotation:
            raw_result = self._try_rotation(img, raw_result)

        lines = self._extract_lines(raw_result)
        img_w, img_h = img.size

        ordered = self._order_lines(lines, img_w, img_h)

        text_lines: list[str] = []
        boxes: list[dict] = []
        ocr_lines: list[dict] = []
        conf_sum = 0.0

        for line in ordered:
            text = line["text"].strip()
            if not text:
                continue
            conf = line.get("conf", 1.0)
            is_low_conf = conf < _LOW_CONF_THRESHOLD and not any(
                "一" <= c <= "鿿" for c in text
            )
            box_entry: dict[str, Any] = {"bbox": line["bbox"], "conf": conf}
            if is_low_conf:
                box_entry["low_conf"] = True
            boxes.append(box_entry)

            if is_low_conf:
                has_content = bool(re.search(
                    r"[A-Za-z0-9一-鿿{}()\[\]<>+\-*/%=&|^~!@#$,.;:\\\"'`_]",
                    text,
                ))
                if len(text) <= 2 and not has_content:
                    continue

            text_lines.append(text)
            conf_sum += conf
            ocr_lines.append({
                "text": text,
                "polygon": line.get("polygon", []),
                "bbox": line["bbox"],
                "confidence": conf,
            })

        result_text = "\n".join(text_lines)
        avg_conf = conf_sum / max(len(text_lines), 1) if text_lines else 0.0

        transforms = tracker.to_ir_transforms() if tracker else None

        return {
            "page_index": page_index,
            "text": result_text,
            "lines": ocr_lines,
            "boxes": boxes,
            "confidence": avg_conf,
            "transforms": transforms,
            "coordinate_space": "image",
            "engine_fingerprint": self._fingerprint,
            "failed": False,
            "error": None,
        }

    # ── Inference ───────────────────────────────────────────────────────────

    def _infer(self, img) -> Any:
        """Run PaddleOCR inference with serialization lock."""
        import numpy as np
        with self._lock:
            return self._ocr.ocr(np.array(img), cls=True)

    def _try_rotation(self, img, initial_result) -> Any:
        """Try 90/180/270 degree rotations if initial result is poor."""

        if self._score_result(initial_result) >= 8:
            return initial_result

        best_result = initial_result
        best_score = self._score_result(initial_result)
        initial_score = best_score

        for degrees in (90, 180, 270):
            candidate_img = self._rotate_image(img, degrees)
            candidate = self._infer(candidate_img)
            candidate_score = self._score_result(candidate)
            if candidate_score > best_score:
                best_result = candidate
                best_score = candidate_score

        if best_score >= max(3.0, initial_score * 1.5):
            return best_result
        return initial_result

    # ── Preprocessing ──────────────────────────────────────────────────────

    def _prepare_image(self, image_bytes: bytes, tracker=None):
        """Full preprocessing pipeline: load → crop → deskew → resize → enhance."""
        from PIL import Image

        img = self._load_image(image_bytes)
        orig_w, orig_h = img.size
        if tracker is not None:
            tracker.orig_width = orig_w
            tracker.orig_height = orig_h

        # Crop
        before = img.size
        img = self._crop_margins(img)
        if tracker is not None and img.size != before:
            pad_x = max(12, int(before[0] * 0.02))
            pad_y = max(12, int(before[1] * 0.02))
            crop_left = (before[0] - img.size[0]) // 2
            crop_top = (before[1] - img.size[1]) // 2
            tracker.record_crop(left=max(0, crop_left - pad_x), top=max(0, crop_top - pad_y))

        # Deskew
        angle = self._estimate_skew(img)
        if angle and tracker is not None:
            cx, cy = img.size[0] / 2, img.size[1] / 2
            tracker.record_rotate(angle, cx=cx, cy=cy)
        if angle:
            img = img.rotate(angle, resample=Image.Resampling.BICUBIC,
                             expand=True, fillcolor="white")
            img = self._crop_margins(img)

        # Resize
        before = img.size
        img = self._resize(img)
        if tracker is not None and img.size != before:
            sx = img.size[0] / before[0]
            sy = img.size[1] / before[1]
            tracker.record_resize(scale_x=sx, scale_y=sy)

        # Quality enhancement
        quality = self._estimate_quality(img)
        strategy = self._choose_strategy(quality)
        if tracker is not None:
            tracker.record_metadata("quality_metrics", quality)
            tracker.record_metadata("enhancement_strategy", sorted(strategy))
        img = self._apply_strategy(img, strategy)

        return img

    def _load_image(self, image_bytes: bytes):
        from PIL import Image, ImageOps
        return ImageOps.exif_transpose(
            Image.open(io.BytesIO(image_bytes))
        ).convert("RGB")

    def _resize(self, img):
        from PIL import Image

        min_width = self._config.min_image_width
        width, height = img.size
        if width < min_width:
            scale = min_width / width
            max_scale = _OCR_MAX_SIDE / max(width, height)
            scale = min(scale, max_scale)
            if scale > 1:
                img = img.resize(
                    (int(width * scale), int(height * scale)),
                    Image.Resampling.LANCZOS,
                )
        width, height = img.size
        if max(width, height) > _OCR_MAX_SIDE:
            scale = _OCR_MAX_SIDE / max(width, height)
            img = img.resize(
                (int(width * scale), int(height * scale)),
                Image.Resampling.LANCZOS,
            )
        return img

    def _crop_margins(self, img):
        bbox = self._content_bbox(img)
        if bbox is None:
            return img
        width, height = img.size
        left, top, right, bottom = bbox
        if (right - left) * (bottom - top) < width * height * 0.08:
            return img
        pad_x = max(12, int(width * 0.02))
        pad_y = max(12, int(height * 0.02))
        crop_box = (
            max(0, left - pad_x),
            max(0, top - pad_y),
            min(width, right + pad_x),
            min(height, bottom + pad_y),
        )
        if (crop_box[2] - crop_box[0]) * (crop_box[3] - crop_box[1]) > width * height * 0.95:
            return img
        return img.crop(crop_box)

    def _content_bbox(self, img):
        import numpy as np

        mask_data = self._foreground_mask(img)
        if mask_data is None:
            return None
        mask, scale = mask_data
        if mask.size == 0 or mask.mean() < 0.0005:
            return None
        height, width = mask.shape
        row_th = max(2, int(width * 0.002))
        col_th = max(2, int(height * 0.002))
        rows = np.where(mask.sum(axis=1) > row_th)[0]
        cols = np.where(mask.sum(axis=0) > col_th)[0]
        if len(rows) == 0 or len(cols) == 0:
            return None
        inv_scale = 1 / scale if scale else 1
        return (
            int(cols[0] * inv_scale),
            int(rows[0] * inv_scale),
            int((cols[-1] + 1) * inv_scale),
            int((rows[-1] + 1) * inv_scale),
        )

    def _foreground_mask(self, img):
        import numpy as np
        from PIL import ImageOps

        gray = ImageOps.autocontrast(img.convert("L"), cutoff=1)
        width, height = gray.size
        max_side = 1200
        scale = min(1.0, max_side / max(width, height))
        if scale < 1:
            gray = gray.resize((max(1, int(width * scale)), max(1, int(height * scale))))
        arr = np.asarray(gray, dtype=np.float32)
        if arr.size == 0:
            return arr.astype(bool), scale
        background = float(np.percentile(arr, 92))
        threshold = max(12.0, float(arr.std()) * 0.35)
        return arr < background - threshold, scale

    def _estimate_skew(self, img) -> float:
        import numpy as np
        from PIL import Image

        mask_data = self._foreground_mask(img)
        if mask_data is None:
            return 0.0
        mask, _ = mask_data
        if mask.size == 0 or mask.mean() < 0.001:
            return 0.0

        base_img = Image.fromarray((mask * 255).astype("uint8"), mode="L")
        best_angle = 0.0
        best_score = self._projection_score(mask)
        zero_score = best_score

        for angle in [x * 0.5 for x in range(-10, 11) if x != 0]:
            rotated = base_img.rotate(angle, resample=Image.Resampling.BILINEAR,
                                      expand=True, fillcolor=0)
            score = self._projection_score(np.asarray(rotated, dtype=np.uint8) > 0)
            if score > best_score:
                best_angle = angle
                best_score = score

        if best_score < zero_score * 1.08 or abs(best_angle) < 0.3:
            return 0.0
        return best_angle

    def _projection_score(self, mask) -> float:
        import numpy as np

        if mask.size == 0:
            return 0.0
        rows = mask.sum(axis=1).astype(np.float32)
        if rows.size < 2:
            return 0.0
        return float(rows.var() + np.abs(np.diff(rows)).mean())

    def _rotate_image(self, img, degrees: int):
        from PIL import Image
        return img.rotate(degrees, resample=Image.Resampling.BICUBIC,
                          expand=True, fillcolor="white")

    def _estimate_quality(self, img) -> dict[str, float]:
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

    def _choose_strategy(self, quality: dict[str, float]) -> set[str]:
        strategy = {"autocontrast"}
        if quality["noise"] > 6 and quality["contrast"] > 15:
            strategy.add("denoise")
        if quality["sharpness"] < 14 and quality["noise"] < 8:
            strategy.add("sharpen")
        return strategy

    def _apply_strategy(self, img, strategy: set[str]):
        from PIL import ImageFilter, ImageOps

        if "denoise" in strategy:
            img = img.filter(ImageFilter.MedianFilter(size=3))
        if "sharpen" in strategy:
            img = img.filter(ImageFilter.UnsharpMask(radius=1, percent=120, threshold=3))
        if "autocontrast" in strategy:
            img = ImageOps.autocontrast(img.convert("L"), cutoff=1).convert("RGB")
        return img

    # ── Postprocessing ─────────────────────────────────────────────────────

    def _extract_lines(self, result: Any) -> list[dict]:
        extracted: list[dict] = []
        for line in self._normalize(result):
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
                "polygon": [c for p in pts for c in p],
                "cx": (x0 + x1) / 2,
                "cy": (y0 + y1) / 2,
                "width": x1 - x0,
                "height": y1 - y0,
            })
        return extracted

    def _normalize(self, result: Any) -> list:
        if not result or result[0] is None:
            return []
        return result[0]

    def _score_result(self, result: Any) -> float:
        lines = self._normalize(result)
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

    def _order_lines(self, lines: list[dict], img_w: int, img_h: int) -> list[dict]:
        if len(lines) < 2:
            return lines
        split = self._detect_column_split(lines, img_w)
        if split is None:
            return sorted(lines, key=lambda line: (line["cy"], line["cx"]))
        full_w = [line for line in lines if line["width"] >= img_w * 0.65]
        col_lines = [line for line in lines if line not in full_w]
        left = sorted(
            [line for line in col_lines if line["cx"] < split],
            key=lambda line: (line["cy"], line["cx"]),
        )
        right = sorted(
            [line for line in col_lines if line["cx"] >= split],
            key=lambda line: (line["cy"], line["cx"]),
        )
        top_cutoff = min((line["cy"] for line in col_lines), default=0)
        bottom_cutoff = max((line["cy"] for line in col_lines), default=img_h)
        before = sorted(
            [line for line in full_w if line["cy"] <= top_cutoff],
            key=lambda line: (line["cy"], line["cx"]),
        )
        after = sorted(
            [line for line in full_w if line["cy"] > bottom_cutoff],
            key=lambda line: (line["cy"], line["cx"]),
        )
        middle = sorted(
            [line for line in full_w if top_cutoff < line["cy"] <= bottom_cutoff],
            key=lambda line: (line["cy"], line["cx"]),
        )
        return before + left + right + middle + after

    def _detect_column_split(self, lines: list[dict], img_w: int) -> float | None:
        candidates = [line for line in lines if line["width"] < img_w * 0.65]
        if len(candidates) < 6:
            return None
        split = img_w / 2
        left = [line for line in candidates if line["cx"] < split]
        right = [line for line in candidates if line["cx"] >= split]
        if len(left) < 3 or len(right) < 3:
            return None
        left_y = (min(line["cy"] for line in left), max(line["cy"] for line in left))
        right_y = (min(line["cy"] for line in right), max(line["cy"] for line in right))
        if min(left_y[1], right_y[1]) - max(left_y[0], right_y[0]) <= 0:
            return None
        left_max = max(line["bbox"][2] for line in left)
        right_min = min(line["bbox"][0] for line in right)
        gap = right_min - left_max
        for ratio in (0.04, 0.02, 0.01):
            if gap >= max(img_w * ratio, 12):
                return (left_max + right_min) / 2
        return None


# ── Child-process engine factory ─────────────────────────────────────────────
# These functions create an OcrEngine in a CHILD PROCESS (process pool worker).
# They MUST NOT be called from the main API process.


def create_engine_for_child(config=None) -> OcrEngine:
    """Create an OcrEngine in a child process.

    WARNING: Only call this in a forked/spawned child process.
    Calling it from the main API process will initialize PaddleOCR
    and CUDA context in the main process, which is NOT allowed.
    """
    from app.core.ocr_runtime_config import get_runtime_config
    return OcrEngine(config or get_runtime_config())
