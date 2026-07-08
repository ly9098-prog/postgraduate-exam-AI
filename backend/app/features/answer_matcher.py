"""答案解析关联器 — 纯规则实现。

从切分后的题目中提取和匹配答案、解析。
支持 INLINE（内联）和 SEPARATED（分离）两种模式。
不做内容清洗、不做题型判断、不调用 AI。
"""

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# OCR 答案字母纠正
_OCR_ANSWER_MAP = {"8": "B", "6": "B", "0": "D"}

# ── Explicit answer extraction (P0: Problem D from audit) ──
_EXPLICIT_ANSWER_PATTERNS: list[tuple[re.Pattern, str | None]] = [
    # 答案：A / 答案:A / 答案: A
    (re.compile(r"(?:^|\s)(?:参考|正确)?答案\s*[:：]\s*([A-Da-d][、,，]?\s*[A-Da-d]?|[A-Da-d])\s*(?:\n|$)"), None),
    # 答案：AB / 答案：A、C  (multi-choice)
    (re.compile(r"(?:^|\s)(?:参考|正确)?答案\s*[:：]\s*([A-Da-d][、,，]\s*[A-Da-d]|[A-Da-d]{2,})\s*(?:\n|$)"), None),
    # 参考答案：A
    (re.compile(r"(?:^|\s)参考答案\s*[:：]\s*([A-Da-d])\s*(?:\n|$)"), None),
    # 正确答案：A
    (re.compile(r"(?:^|\s)正确答案\s*[:：]\s*([A-Da-d])\s*(?:\n|$)"), None),
    # Answer: A / KEY: A
    (re.compile(r"(?:^|\s)(?:Answer|KEY)\s*[:：]\s*([A-Da-d])\s*(?:\n|$)", re.IGNORECASE), None),
    # 【答案】A
    (re.compile(r"(?:^|\s)【(?:参考|正确)?答案】\s*([A-Da-d])\s*(?:\n|$)"), None),
]


@dataclass
class ExplicitAnswerResult:
    """Result of explicit answer extraction from raw text."""
    answer: str | None
    source_span: tuple[int, int] | None
    pattern: str | None
    confidence: float


def extract_explicit_answer(raw_text: str) -> ExplicitAnswerResult:
    """Extract explicit answer from raw OCR text.

    Detects patterns like:
        答案：A, 答案:A, 参考答案：A, 正确答案：A, Answer: A
        答案：AB (multi-choice), 答案：A、C

    Returns:
        ExplicitAnswerResult with answer (uppercase, comma-separated for multi)
        or answer=None if no explicit answer found.
    """
    if not raw_text:
        return ExplicitAnswerResult(answer=None, source_span=None, pattern=None, confidence=0.0)

    for pat, _ in _EXPLICIT_ANSWER_PATTERNS:
        m = pat.search(raw_text)
        if m:
            raw_answer = m.group(1).strip()
            # Normalize: remove punctuation separators, uppercase
            cleaned = raw_answer.replace("、", ",").replace("，", ",").replace(" ", "")
            cleaned = cleaned.upper()
            # Validate: single letter (A-D) or multi-letter combo
            if re.match(r"^[A-D](?:[,，]?\s*[A-D])*$", cleaned):
                pattern_desc = pat.pattern[:60]
                return ExplicitAnswerResult(
                    answer=cleaned,
                    source_span=(m.start(), m.end()),
                    pattern=pattern_desc,
                    confidence=0.95,
                )
            # Single letter fallback
            if re.match(r"^[A-D]$", cleaned):
                pattern_desc = pat.pattern[:60]
                return ExplicitAnswerResult(
                    answer=cleaned,
                    source_span=(m.start(), m.end()),
                    pattern=pattern_desc,
                    confidence=0.95,
                )

    # OCR fuzzy: "答案:8" → "B"
    fuzzy_pat = re.compile(r"(?:^|\n)\s*(?:参考|正确)?答案\s*[:：]\s*([068])\s*(?:\n|$)")
    m = fuzzy_pat.search(raw_text)
    if m:
        ocr_digit = m.group(1)
        mapped = _OCR_ANSWER_MAP.get(ocr_digit)
        if mapped:
            return ExplicitAnswerResult(
                answer=mapped,
                source_span=(m.start(), m.end()),
                pattern="answer_ocr_fuzzy",
                confidence=0.7,
            )

    return ExplicitAnswerResult(answer=None, source_span=None, pattern=None, confidence=0.0)

# 答案字母字符集（含 OCR 容错、判断 T/F、多选逗号）
_ANSWER_LETTERS = r"[A-Da-d068TFtf,，]"

# 答案标记模式: (regex, 答案字母组)
_ANSWER_LABEL_PATTERNS: list[tuple[re.Pattern, int]] = [
    (re.compile(r"(?:【答案】|答案[：:]\s*|参考答案[：:]\s*|正确答案[：:]\s*)\s*(" + _ANSWER_LETTERS + r"+)"), 1),
    (re.compile(r"(?:KEY|Answer|answer)\s*[：:]\s*(" + _ANSWER_LETTERS + r"+)"), 1),
]

# 解析标记模式: (regex, 解析内容组)
_EXPLANATION_LABEL_PATTERNS: list[tuple[re.Pattern, int]] = [
    (re.compile(r"(?:【解析】|解析[：:]|解答[：:]|讲解[：:]|分析[：:])\s*(.+)"), 1),
    (re.compile(r"(?:Explanation|explanation)\s*[：:]\s*(.+)"), 1),
]

# 解析标签清理（用于从混合文本中剥离标签前缀）
_EXPLANATION_CLEAN = [
    re.compile(r"^解析[：:]?\s*"),
    re.compile(r"^【解析】\s*"),
    re.compile(r"^解答[：:]?\s*"),
    re.compile(r"^【解答】\s*"),
    re.compile(r"^讲解[：:]?\s*"),
    re.compile(r"^分析[：:]?\s*"),
    re.compile(r"^(?:Explanation|explanation)\s*[：:]\s*"),
]


def _correct_answer_letter(letter: str) -> str:
    """OCR 纠错：8→B, 0→D 等，并统一大写。"""
    upper = letter.upper()
    return _OCR_ANSWER_MAP.get(upper, upper)


def _clean_explanation(text: str) -> str:
    """去除解析标签前缀。"""
    for pat in _EXPLANATION_CLEAN:
        text = pat.sub("", text)
    return text.strip()


def _extract_inline_answer(text: str) -> dict | None:
    """从题目文本中提取内联答案。"""
    for pat, group_idx in _ANSWER_LABEL_PATTERNS:
        m = pat.search(text)
        if m:
            raw = m.group(0).strip()
            answer = _correct_answer_letter(m.group(group_idx))
            return {"answer": answer, "raw": raw}
    return None


def _extract_inline_explanation(text: str) -> dict | None:
    """从题目文本中提取内联解析。"""
    for pat, group_idx in _EXPLANATION_LABEL_PATTERNS:
        m = pat.search(text)
        if m:
            raw = m.group(0).strip()
            explanation = _clean_explanation(m.group(group_idx))
            return {"explanation": explanation, "raw": raw}
    return None


def _collect_page_text(blocks: list[dict], pages: list[int]) -> str:
    """收集指定页码的文本。"""
    if not pages:
        return ""
    parts = []
    for block in blocks:
        if block.get("page") in pages:
            parts.append(block.get("normalized_text", ""))
    return "\n".join(parts)


def _extract_all_separated_answers(text: str) -> list[dict]:
    """从答案区域文本中提取所有「题号.字母」条目，按出现顺序排列。"""
    pat = re.compile(r"(?:^|\n)\s*(\d+)\s*[.、)）]\s*(" + _ANSWER_LETTERS + r")\b")
    answers = []
    seen = set()
    for m in pat.finditer(text):
        num = int(m.group(1))
        if num in seen:
            continue
        seen.add(num)
        letter = _correct_answer_letter(m.group(2))
        answers.append({
            "number": num,
            "answer": letter,
            "raw": m.group(0).strip(),
        })
    return answers


def _extract_separated_answer(
    normalized_blocks: list[dict],
    answer_pages: list[int],
    question_number: int,
    question_index: int | None = None,
) -> dict | None:
    """从答案区域按题号匹配答案。"""
    answer_text = _collect_page_text(normalized_blocks, answer_pages)
    if not answer_text:
        return None

    # 方式 1：按题号精确匹配 "1.A" "1、A" "1) A"
    pat_direct = re.compile(
        rf"(?:^|\n)\s*{question_number}\s*[.、)）]\s*(" + _ANSWER_LETTERS + r")\b"
    )
    m = pat_direct.search(answer_text)
    if m:
        return {
            "answer": _correct_answer_letter(m.group(1)),
            "raw": m.group(0).strip(),
            "exact_match": True,
        }

    # 方式 2：题号 + 答案标签 "1 答案：A"
    pat_label = re.compile(
        rf"(?:^|\n)\s*{question_number}\s*[.、)）]?\s*(?:答案[：:]|【答案】)\s*(" + _ANSWER_LETTERS + r"+)"
    )
    m = pat_label.search(answer_text)
    if m:
        return {
            "answer": _correct_answer_letter(m.group(1)),
            "raw": m.group(0).strip(),
            "exact_match": True,
        }

    # 方式 3：提取全部答案，先按题号精确匹配，再按顺序 fallback
    all_answers = _extract_all_separated_answers(answer_text)
    if all_answers:
        for a in all_answers:
            if a["number"] == question_number:
                return {"answer": a["answer"], "raw": a["raw"], "exact_match": True}

        # 顺序 fallback：仅在题号合理范围内使用
        max_ans_num = max(a["number"] for a in all_answers)
        if question_index is not None and question_number <= max_ans_num + 2:
            if question_index < len(all_answers):
                a = all_answers[question_index]
                return {"answer": a["answer"], "raw": a["raw"], "exact_match": False}

    return None


def _extract_separated_explanation(
    normalized_blocks: list[dict],
    explanation_pages: list[int],
    question_number: int,
) -> dict | None:
    """从解析区域按题号提取解析。"""
    expl_text = _collect_page_text(normalized_blocks, explanation_pages)
    if not expl_text:
        return None

    # 题号 + 解析标记
    pat_label = re.compile(
        rf"(?:^|\n)\s*{question_number}\s*[.、)）]\s*"
        rf"(?:【解析】|解析[：:]|解答[：:]|讲解[：:]|分析[：:])\s*(.+)"
    )
    m = pat_label.search(expl_text)
    if m:
        raw = m.group(0).strip()
        return {
            "explanation": _clean_explanation(m.group(1)),
            "raw": raw,
            "exact_match": True,
        }

    # 题号 + 任意内容（弱匹配）
    pat_weak = re.compile(
        rf"(?:^|\n)\s*{question_number}\s*[.、)）]\s*(.+)"
    )
    m = pat_weak.search(expl_text)
    if m:
        raw = m.group(0).strip()
        return {
            "explanation": _clean_explanation(m.group(1)),
            "raw": raw,
            "exact_match": False,
        }

    return None


def _extract_explicit_answer_from_raw(raw_text: str) -> dict | None:
    """Extract explicit answer from raw OCR text via extract_explicit_answer().

    Returns dict with answer/source/confidence/pattern suitable for merging
    into matched result, or None if no explicit answer found.
    """
    result = extract_explicit_answer(raw_text)
    if result.answer:
        logger.info(
            "Explicit answer extracted: answer=%s pattern=%.60s confidence=%.2f",
            result.answer, result.pattern or "none", result.confidence,
        )
        return {
            "answer": result.answer,
            "answer_source": "explicit_text",
            "pattern": result.pattern,
            "confidence": result.confidence,
            "source_span": result.source_span,
        }
    return None


def match_answers(
    raw_questions: list[dict],
    normalized_blocks: list[dict],
    structure: dict | None = None,
) -> dict:
    """关联题目与答案、解析。

    Args:
        raw_questions: stage3 输出的题目列表
        normalized_blocks: stage1 输出的标准化块
        structure: stage2 的结构分析结果

    Returns:
        {"matched": [...], "unmatched": [...]}
    """
    if structure is None:
        structure = {}

    mode = structure.get("mode", "INLINE")
    answer_pages = structure.get("answer_pages", [])
    explanation_pages = structure.get("explanation_pages", [])

    matched = []
    unmatched = []

    for idx, q in enumerate(raw_questions):
        qnum = q.get("number", 0)
        qtext = q.get("raw_question_text", "")

        answer = None
        explanation = None
        answer_source = "missing"
        explanation_source = "missing"
        raw_answer_text = ""
        raw_explanation_text = ""
        confidence = 0.0
        trace_answer_source: str | None = None

        # 0. Explicit answer extraction from raw text (P0: Problem D)
        # Run BEFORE inline/separated extraction so explicit answers are
        # always detected even when inline patterns fail.
        explicit = _extract_explicit_answer_from_raw(qtext)
        # Fallback: if question has _original_raw_text (frozen options were
        # stripped from raw_question_text), check that too.
        if not explicit and q.get("_original_raw_text"):
            explicit = _extract_explicit_answer_from_raw(q["_original_raw_text"])
        if explicit:
            answer = explicit["answer"]
            answer_source = explicit["answer_source"]
            raw_answer_text = qtext[explicit["source_span"][0]:explicit["source_span"][1]] if explicit.get("source_span") else ""
            confidence = max(confidence, explicit["confidence"])
            trace_answer_source = f"explicit_{explicit.get('pattern', 'unknown')}"

        # 1. INLINE 提取 (only if no explicit answer found yet)
        if answer is None:
            inline_a = _extract_inline_answer(qtext)
            if inline_a:
                answer = inline_a["answer"]
                answer_source = "inline"
                raw_answer_text = inline_a["raw"]
                confidence = max(confidence, 0.9)

        inline_e = _extract_inline_explanation(qtext)
        if inline_e:
            explanation = inline_e["explanation"]
            explanation_source = "inline"
            raw_explanation_text = inline_e["raw"]
            confidence = max(confidence, 0.9)

        # 2. SEPARATED 提取（仅当 mode == SEPARATED 且未从 inline 找到时）
        if mode == "SEPARATED":
            if answer is None and answer_pages:
                sep_a = _extract_separated_answer(
                    normalized_blocks, answer_pages, qnum, idx
                )
                if sep_a:
                    answer = sep_a["answer"]
                    answer_source = "separated"
                    raw_answer_text = sep_a["raw"]
                    conf_delta = 0.95 if sep_a.get("exact_match") else 0.7
                    confidence = max(confidence, conf_delta)

            if explanation is None and explanation_pages:
                sep_e = _extract_separated_explanation(
                    normalized_blocks, explanation_pages, qnum
                )
                if sep_e:
                    explanation = sep_e["explanation"]
                    explanation_source = "separated"
                    raw_explanation_text = sep_e["raw"]
                    conf_delta = 0.95 if sep_e.get("exact_match") else 0.7
                    confidence = max(confidence, conf_delta)

        # 3. 答案和解析都缺失 → 完全未匹配
        if answer is None and explanation is None:
            unmatched.append({
                "question_number": qnum,
                "reason": "answer_not_found",
            })
        elif answer is None:
            unmatched.append({
                "question_number": qnum,
                "reason": "answer_not_found",
            })

        matched.append({
            "question_number": qnum,
            "answer": answer,
            "explanation": explanation,
            "answer_source": answer_source,
            "explanation_source": explanation_source,
            "confidence": round(confidence, 2),
            "raw_answer_text": raw_answer_text,
            "raw_explanation_text": raw_explanation_text,
            "trace_answer_source": trace_answer_source,
        })

    return {"matched": matched, "unmatched": unmatched}
