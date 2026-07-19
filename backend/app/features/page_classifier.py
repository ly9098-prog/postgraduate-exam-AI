"""页面分类器 — 纯规则实现。

对文档的每一页进行类型分类，决定哪些页面进入题目抽取流程。
不做逐题切分、不做答案匹配、不调用 AI。
"""

import re
from collections import defaultdict

# Page labels
QUESTION_PAGE = "QUESTION_PAGE"
ANSWER_PAGE = "ANSWER_PAGE"
ANALYSIS_PAGE = "ANALYSIS_PAGE"
KNOWLEDGE_PAGE = "KNOWLEDGE_PAGE"
CATALOG_PAGE = "CATALOG_PAGE"
BLANK_PAGE = "BLANK_PAGE"

# ---------------------------------------------------------------------------
# Signal patterns
# ---------------------------------------------------------------------------

_QUESTION_NUMBER_PATTERNS = [
    re.compile(r"^\s*\d+\s*[.．、)）]"),
    re.compile(r"^\s*\(\d+\)"),
    re.compile(r"^\s*【\d+】"),
    re.compile(r"^第\s*\d+\s*题"),
    re.compile(r"^第\s*[一二三四五六七八九十]+\s*题"),
]

_OPTION_PATTERN = re.compile(
    r"(?:^|\s)[A-Da-d]\s*[.．、:：)）]", re.MULTILINE
)

_FILL_BLANK_PATTERN = re.compile(r"_{2,}|（\s*）|\(\s*\)")

_ANSWER_KEYWORDS = [
    "答案", "参考答案", "正确答案", "标准答案",
    "Answer", "ANSWER", "KEY",
]

_NUMBERED_ANSWER_PATTERN = re.compile(
    r"^\s*\d+\s*[.、)）]\s*[A-Da-d068TFtf]\b", re.MULTILINE
)

_ANALYSIS_KEYWORDS = [
    "解析", "解答", "讲解", "详解",
    "【解析】", "【解答】", "【分析】",
]

_CATALOG_PATTERNS = [
    re.compile(r"目\s*录"),
    re.compile(r"第\s*[一二三四五六七八九十\d]+\s*章.*\d+$", re.MULTILINE),
    re.compile(r"^\s*\d+\.\d+\s+.+\.{3,}\s*\d+", re.MULTILINE),
]

_KNOWLEDGE_NEGATIVE_SIGNALS = re.compile(
    r"定义|定理|概念|原理|性质|公式|证明[：:]|引理|推论|注意|说明[：:]"
)

_BLANK_THRESHOLD = 20


# ---------------------------------------------------------------------------
# Core classification
# ---------------------------------------------------------------------------


def _count_question_numbers(text: str) -> int:
    count = 0
    for line in text.split("\n"):
        stripped = line.strip()
        for pat in _QUESTION_NUMBER_PATTERNS:
            if pat.match(stripped):
                count += 1
                break
    return count


def _count_option_markers(text: str) -> int:
    return len(_OPTION_PATTERN.findall(text))


def _count_fill_blanks(text: str) -> int:
    return len(_FILL_BLANK_PATTERN.findall(text))


def _count_answer_keywords(text: str) -> int:
    count = 0
    for kw in _ANSWER_KEYWORDS:
        count += text.count(kw)
    return count


def _count_numbered_answers(text: str) -> int:
    return len(_NUMBERED_ANSWER_PATTERN.findall(text))


def _count_analysis_keywords(text: str) -> int:
    count = 0
    for kw in _ANALYSIS_KEYWORDS:
        count += text.count(kw)
    return count


def _has_catalog_pattern(text: str) -> bool:
    for pat in _CATALOG_PATTERNS:
        if pat.search(text):
            return True
    return False


def _count_knowledge_signals(text: str) -> int:
    return len(_KNOWLEDGE_NEGATIVE_SIGNALS.findall(text))


def _classify_single_page(page_text: str, section_hints: dict | None = None) -> dict:
    """Classify a single page's text, returning label + confidence + signals."""
    text_len = len(page_text.strip())

    if text_len < _BLANK_THRESHOLD:
        return {
            "label": BLANK_PAGE,
            "confidence": 0.95,
            "signals": {"text_length": text_len},
        }

    q_numbers = _count_question_numbers(page_text)
    options = _count_option_markers(page_text)
    fill_blanks = _count_fill_blanks(page_text)
    answer_kw = _count_answer_keywords(page_text)
    numbered_answers = _count_numbered_answers(page_text)
    analysis_kw = _count_analysis_keywords(page_text)
    is_catalog = _has_catalog_pattern(page_text)
    knowledge_signals = _count_knowledge_signals(page_text)

    signals = {
        "question_numbers": q_numbers,
        "option_markers": options,
        "fill_blanks": fill_blanks,
        "answer_keywords": answer_kw,
        "numbered_answers": numbered_answers,
        "analysis_keywords": analysis_kw,
        "is_catalog": is_catalog,
        "knowledge_signals": knowledge_signals,
        "text_length": text_len,
    }

    # Apply section hints from structure_analyzer markers
    hint_boost = section_hints or {}

    # Scoring
    scores: dict[str, float] = {
        QUESTION_PAGE: 0.0,
        ANSWER_PAGE: 0.0,
        ANALYSIS_PAGE: 0.0,
        KNOWLEDGE_PAGE: 0.0,
        CATALOG_PAGE: 0.0,
    }

    # Question signals
    if q_numbers >= 2:
        scores[QUESTION_PAGE] += 0.4
    elif q_numbers == 1:
        scores[QUESTION_PAGE] += 0.15
    if options >= 3:
        scores[QUESTION_PAGE] += 0.3
    elif options >= 1:
        scores[QUESTION_PAGE] += 0.1
    if fill_blanks >= 2:
        scores[QUESTION_PAGE] += 0.2

    # Answer signals
    if answer_kw >= 1:
        scores[ANSWER_PAGE] += 0.35
    if numbered_answers >= 3:
        scores[ANSWER_PAGE] += 0.4
    elif numbered_answers >= 1:
        scores[ANSWER_PAGE] += 0.15

    # Analysis signals
    if analysis_kw >= 3:
        scores[ANALYSIS_PAGE] += 0.5
    elif analysis_kw >= 1:
        scores[ANALYSIS_PAGE] += 0.2

    # Catalog signals
    if is_catalog:
        scores[CATALOG_PAGE] += 0.7

    # Knowledge signals (prose without question/answer patterns)
    total_question_answer_signal = q_numbers + options + answer_kw + numbered_answers + analysis_kw
    if total_question_answer_signal == 0 and text_len > 50:
        scores[KNOWLEDGE_PAGE] += 0.4
        if knowledge_signals >= 2:
            scores[KNOWLEDGE_PAGE] += 0.2

    # Section hint boosts
    if hint_boost.get("exercise_start"):
        scores[QUESTION_PAGE] += 0.2
    if hint_boost.get("answer_start"):
        scores[ANSWER_PAGE] += 0.3
    if hint_boost.get("summary"):
        scores[KNOWLEDGE_PAGE] += 0.2

    # Find winner
    best_label = max(scores, key=lambda k: scores[k])
    best_score = scores[best_label]

    # If no strong signal, default to KNOWLEDGE_PAGE for long text
    if best_score < 0.15:
        if text_len > 50:
            best_label = KNOWLEDGE_PAGE
            best_score = 0.3
        else:
            best_label = BLANK_PAGE
            best_score = 0.5

    # Convert score to confidence (0.0-1.0)
    confidence = min(1.0, best_score + 0.3)

    return {
        "label": best_label,
        "confidence": round(confidence, 2),
        "signals": signals,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_pages(
    normalized_blocks: list[dict],
    section_markers: list[dict] | None = None,
) -> list[dict]:
    """Classify each page in the document.

    Args:
        normalized_blocks: blocks with normalized_text, page fields
        section_markers: optional markers from structure_analyzer

    Returns:
        List of {page, label, confidence, signals} per page.
    """
    # Group blocks by page
    page_texts: dict[int, list[str]] = defaultdict(list)
    for block in normalized_blocks:
        page = block.get("page", 1)
        text = block.get("normalized_text", "")
        page_texts[page].append(text)

    # Build section hints per page from markers
    page_hints: dict[int, dict] = defaultdict(dict)
    if section_markers:
        for marker in section_markers:
            page = marker.get("page", 0)
            marker_type = marker.get("marker_type", "")
            page_hints[page][marker_type] = True

    # Propagate hints forward: pages after exercise_start inherit it until answer_start
    if section_markers:
        all_pages = sorted(page_texts.keys())
        active_hint: str | None = None
        for page in all_pages:
            if "exercise_start" in page_hints[page]:
                active_hint = "exercise_start"
            elif "answer_start" in page_hints[page]:
                active_hint = "answer_start"
            elif "summary" in page_hints[page]:
                active_hint = "summary"

            if active_hint and active_hint not in page_hints[page]:
                page_hints[page][active_hint] = True

    # Classify each page
    results: list[dict] = []
    for page in sorted(page_texts.keys()):
        combined_text = "\n".join(page_texts[page])
        hints = page_hints.get(page)
        classification = _classify_single_page(combined_text, hints)
        results.append({
            "page": page,
            "label": classification["label"],
            "confidence": classification["confidence"],
            "signals": classification["signals"],
        })

    return results


def filter_blocks_by_classification(
    normalized_blocks: list[dict],
    page_classifications: list[dict],
    allowed_labels: set[str] | None = None,
) -> list[dict]:
    """Filter normalized_blocks to only include pages with allowed labels.

    Args:
        normalized_blocks: full block list
        page_classifications: output of classify_pages()
        allowed_labels: set of labels to keep (default: QUESTION_PAGE, ANSWER_PAGE, ANALYSIS_PAGE)

    Returns:
        Filtered block list.
    """
    if allowed_labels is None:
        allowed_labels = {QUESTION_PAGE, ANSWER_PAGE, ANALYSIS_PAGE}

    allowed_pages: set[int] = set()
    for pc in page_classifications:
        if pc["label"] in allowed_labels:
            allowed_pages.add(pc["page"])

    return [b for b in normalized_blocks if b.get("page", 1) in allowed_pages]


def classify_pages_from_ir(
    doc: "DocumentIR",
    section_markers: list[dict] | None = None,
) -> list[dict]:
    """DocumentIR entry point for classify_pages."""
    from app.core.document_ir import document_ir_to_blocks
    blocks = document_ir_to_blocks(doc)
    return classify_pages(blocks, section_markers=section_markers)
