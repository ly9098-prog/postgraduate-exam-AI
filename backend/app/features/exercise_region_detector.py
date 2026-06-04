"""习题区域检测器 — 轻量级页面扫描，定位习题页范围。

在正式 OCR 之前执行，使用低 DPI 快速 OCR 获取页面文本，
通过关键词匹配+题目特征评分定位习题区域，仅对习题区域执行后续全量 OCR。

Phases:
1. Exercise Start Detection (keyword fuzzy match)
2. Exercise Page Validation (question density scoring)
3. Exercise Region Expansion (forward scan)
4. Exercise End Detection (end keywords / empty pages)
5. Multiple Exercise Regions (iterate all chapters)
6. AI-assisted judgment (placeholder, deferred)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ExerciseRegion:
    start_page: int
    end_page: int
    confidence: float
    matched_keyword: str


# ---------------------------------------------------------------------------
# Phase 1: Exercise Start Detection — keywords + fuzzy matching
# ---------------------------------------------------------------------------

EXERCISE_START_KEYWORDS = [
    "本节习题精选",
    "习题精选",
    "本节习题",
    "本章习题",
    "课后习题",
    "同步训练",
    "综合练习",
    "练习题",
    "自测题",
    "思考题",
    "习题",
]

EXERCISE_END_KEYWORDS = [
    "参考答案",
    "答案与解析",
    "答案和解析",
    "答案解析",
    "习题解析",
    "本章小结",
    "知识总结",
    "知识梳理",
    "答案",
]

_TRAD_TO_SIMP = str.maketrans(
    "習題練選綜測總結節課後訓區點講義體書章答案解析參考標準資料",
    "习题练选综测总结节课后训区点讲义体书章答案解析参考标准资料",
)

_PUNCTUATION_RE = re.compile(r"[：:；;，,。.！!？?【】\[\]()（）「」『』“”‘’《》〈〉\s]")


def _normalize_for_matching(text: str) -> str:
    text = text.translate(_TRAD_TO_SIMP)
    text = _PUNCTUATION_RE.sub("", text)
    return text


def _levenshtein(s: str, t: str) -> int:
    if len(s) < len(t):
        return _levenshtein(t, s)
    if not t:
        return len(s)
    prev = list(range(len(t) + 1))
    for i, sc in enumerate(s):
        curr = [i + 1]
        for j, tc in enumerate(t):
            cost = 0 if sc == tc else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[-1]


def _match_exercise_keyword(
    text: str, keywords: list[str], max_distance: int = 2
) -> tuple[str, float] | None:
    normalized = _normalize_for_matching(text)
    if not normalized:
        return None

    for kw in keywords:
        norm_kw = _normalize_for_matching(kw)
        if norm_kw in normalized:
            return kw, 1.0

    for line in text.split("\n"):
        norm_line = _normalize_for_matching(line.strip())
        if not norm_line or len(norm_line) > 30:
            continue
        for kw in keywords:
            norm_kw = _normalize_for_matching(kw)
            if len(norm_kw) <= 2:
                if norm_line == norm_kw:
                    return kw, 1.0
                continue
            dist = _levenshtein(norm_line[:len(norm_kw) + max_distance], norm_kw)
            if dist == 0:
                return kw, 1.0
            elif dist <= 1:
                return kw, 0.8
            elif dist <= max_distance:
                return kw, 0.6

    return None


# ---------------------------------------------------------------------------
# Phase 2: Exercise Page Validation — question density scoring
# ---------------------------------------------------------------------------

_QUESTION_NUMBER_RE = re.compile(r"^\s*\d+\s*[.．、)）]", re.MULTILINE)
_OPTION_RE = re.compile(r"(?:^|\s)[A-Da-d]\s*[.．、:：)）]", re.MULTILINE)
_FILL_BLANK_RE = re.compile(r"_{2,}|（\s*）|\(\s*\)")
_SCORE_MARKER_RE = re.compile(r"[（(]\s*\d+\s*分\s*[)）]")
_CIRCLED_NUMBER_RE = re.compile(r"[①②③④⑤⑥⑦⑧⑨⑩]")
_KNOWLEDGE_NEGATIVE_RE = re.compile(r"定义|定理|概念|原理|性质|公式|证明[：:]|引理|推论")
_EXAMPLE_NEGATIVE_RE = re.compile(r"^例\s*\d+|例题|解法|证明如下|解\s*[:：]")


def _compute_exercise_page_score(text: str) -> float:
    if not text.strip():
        return 0.0

    score = 0.0

    q_numbers = len(_QUESTION_NUMBER_RE.findall(text))
    if q_numbers >= 3:
        score += 0.35
    elif q_numbers >= 2:
        score += 0.3
    elif q_numbers >= 1:
        score += 0.15

    options = len(_OPTION_RE.findall(text))
    if options >= 4:
        score += 0.35
    elif options >= 3:
        score += 0.3
    elif options >= 1:
        score += 0.1

    fill_blanks = len(_FILL_BLANK_RE.findall(text))
    if fill_blanks >= 2:
        score += 0.1

    score_markers = len(_SCORE_MARKER_RE.findall(text))
    if score_markers >= 1:
        score += 0.1

    circled = len(_CIRCLED_NUMBER_RE.findall(text))
    if circled >= 2:
        score += 0.1

    knowledge = len(_KNOWLEDGE_NEGATIVE_RE.findall(text))
    if knowledge >= 3:
        score -= 0.25
    elif knowledge >= 2:
        score -= 0.2

    examples = len(_EXAMPLE_NEGATIVE_RE.findall(text))
    if examples >= 2:
        score -= 0.15

    return max(0.0, min(1.0, score))


def _has_question_pattern(text: str) -> bool:
    return bool(_QUESTION_NUMBER_RE.search(text))


# ---------------------------------------------------------------------------
# Phase 4: Exercise End Detection
# ---------------------------------------------------------------------------

def _match_end_keyword(text: str) -> str | None:
    normalized = _normalize_for_matching(text)
    for kw in EXERCISE_END_KEYWORDS:
        norm_kw = _normalize_for_matching(kw)
        if norm_kw in normalized:
            return kw
    return None


# ---------------------------------------------------------------------------
# Phase 6: AI-assisted judgment (placeholder)
# ---------------------------------------------------------------------------

async def _ai_classify_page(text: str) -> str | None:
    return None


# ---------------------------------------------------------------------------
# Core detection algorithm (Phases 1-5 combined)
# ---------------------------------------------------------------------------

_SEEKING_START = "seeking_start"
_VALIDATING = "validating"
_EXPANDING = "expanding"


def detect_exercise_regions(
    page_texts: dict[int, str],
    config: dict | None = None,
) -> list[ExerciseRegion]:
    """Detect exercise regions from pre-scanned page texts.

    Args:
        page_texts: {page_number: ocr_text} from lightweight scan
        config: optional overrides for max_empty_pages, min_confidence

    Returns:
        Ordered list of ExerciseRegion, or empty list if none found.
    """
    cfg = config or {}
    max_empty = cfg.get("max_empty_pages", 3)
    min_confidence = cfg.get("min_confidence", 0.5)

    if not page_texts:
        return []

    pages = sorted(page_texts.keys())
    regions: list[ExerciseRegion] = []

    state = _SEEKING_START
    current_start: int = 0
    current_keyword: str = ""
    current_confidence: float = 0.0
    empty_streak: int = 0
    last_valid_page: int = 0

    for page in pages:
        text = page_texts[page]

        if state == _SEEKING_START:
            match = _match_exercise_keyword(text, EXERCISE_START_KEYWORDS)
            if match:
                keyword, confidence = match
                if confidence >= min_confidence:
                    current_start = page
                    current_keyword = keyword
                    current_confidence = confidence
                    state = _VALIDATING

        elif state == _VALIDATING:
            score = _compute_exercise_page_score(text)
            start_text = page_texts.get(current_start, "")
            start_score = _compute_exercise_page_score(start_text)

            combined_score = max(score, start_score)
            if combined_score >= 0.2 or _has_question_pattern(text) or _has_question_pattern(start_text):
                state = _EXPANDING
                empty_streak = 0
                last_valid_page = page
            else:
                state = _SEEKING_START

        elif state == _EXPANDING:
            end_kw = _match_end_keyword(text)
            if end_kw:
                regions.append(ExerciseRegion(
                    start_page=current_start,
                    end_page=page,
                    confidence=current_confidence,
                    matched_keyword=current_keyword,
                ))
                state = _SEEKING_START
                empty_streak = 0
                continue

            score = _compute_exercise_page_score(text)
            has_q = _has_question_pattern(text)

            if score >= 0.25 or has_q:
                empty_streak = 0
                last_valid_page = page
            else:
                empty_streak += 1
                if empty_streak >= max_empty:
                    regions.append(ExerciseRegion(
                        start_page=current_start,
                        end_page=last_valid_page,
                        confidence=current_confidence,
                        matched_keyword=current_keyword,
                    ))
                    state = _SEEKING_START
                    empty_streak = 0

    if state == _EXPANDING:
        end_page = last_valid_page if last_valid_page > current_start else pages[-1]
        regions.append(ExerciseRegion(
            start_page=current_start,
            end_page=end_page,
            confidence=current_confidence,
            matched_keyword=current_keyword,
        ))

    if state == _VALIDATING:
        start_text = page_texts.get(current_start, "")
        if _has_question_pattern(start_text) or _compute_exercise_page_score(start_text) >= 0.25:
            regions.append(ExerciseRegion(
                start_page=current_start,
                end_page=current_start,
                confidence=current_confidence * 0.7,
                matched_keyword=current_keyword,
            ))

    return regions


# ---------------------------------------------------------------------------
# Lightweight OCR scan
# ---------------------------------------------------------------------------

def _lightweight_page_ocr(content: bytes, dpi: int = 72) -> dict[int, str]:
    """Render PDF pages at low DPI and run PaddleOCR for quick text extraction.

    Minimal preprocessing: no rotation detection, no deskew.
    """
    import gc

    import fitz

    from app.services.ocr_service import _get_ocr, _image_to_array, _ocr_lock, _resize_for_ocr

    doc = fitz.open(stream=content, filetype="pdf")
    total_pages = len(doc)
    ocr = _get_ocr()
    page_texts: dict[int, str] = {}

    try:
        for i in range(total_pages):
            pix = doc[i].get_pixmap(dpi=dpi)
            png_bytes = pix.tobytes("png")
            del pix

            try:
                from PIL import Image, ImageOps
                import io
                img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
                img = ImageOps.autocontrast(img.convert("L"), cutoff=1).convert("RGB")
                img = _resize_for_ocr(img)

                import numpy as np
                arr = np.array(img)
                del img

                with _ocr_lock:
                    result = ocr.ocr(arr, cls=False)
                del arr

                if result and result[0]:
                    lines = []
                    for line in result[0]:
                        if line and len(line) >= 2 and line[1]:
                            text = str(line[1][0] or "")
                            if text.strip():
                                lines.append(text)
                    page_texts[i + 1] = "\n".join(lines)
                else:
                    page_texts[i + 1] = ""
            except Exception as e:
                logger.debug("Lightweight OCR page %d failed: %s", i + 1, e)
                page_texts[i + 1] = ""

            if (i + 1) % 20 == 0:
                gc.collect()
    finally:
        doc.close()

    return page_texts


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_exercise_regions_from_pdf(
    content: bytes,
    config: dict | None = None,
) -> list[ExerciseRegion]:
    """End-to-end: lightweight OCR scan → detect exercise regions.

    Args:
        content: raw PDF bytes
        config: {dpi, max_empty_pages, min_confidence}

    Returns:
        List of ExerciseRegion, or empty list if detection fails/finds nothing.
    """
    cfg = config or {}
    dpi = cfg.get("dpi", 72)

    try:
        page_texts = _lightweight_page_ocr(content, dpi=dpi)
    except Exception as e:
        logger.warning("Exercise region detection failed during OCR scan: %s", e)
        return []

    if not page_texts:
        return []

    regions = detect_exercise_regions(page_texts, config=cfg)

    if regions:
        logger.info(
            "Exercise region detection found %d region(s): %s",
            len(regions),
            [(r.start_page, r.end_page) for r in regions],
        )
    else:
        logger.info("Exercise region detection found no regions, will fall back to full OCR")

    return regions
