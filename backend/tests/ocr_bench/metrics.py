"""OCR Bench 指标计算。

在 tests.ocr_eval.metrics (CER, line_recall, etc.) 基础上扩展：
- 业务指标（题号、选项、答案 Exact Match）
- 代码指标（括号平衡、代码 token EM、比较操作符保留率）
- 加权综合评分
"""

from __future__ import annotations

import difflib
import re
from typing import Any

from tests.ocr_bench.schema import (
    BusinessMetrics,
    CodeMetrics,
    FreezeBindingMetrics,
    LineLevelMetrics,
    MetricsResult,
    QualityGateMetrics,
    ReadingOrderMetrics,
    ScenarioBucket,
)
from tests.ocr_eval.metrics import (
    character_error_rate,
    line_precision as _line_precision,
    line_recall as _line_recall,
    text_drop_rate as _text_drop_rate,
)

# ---------------------------------------------------------------------------
# Weights for overall score
# ---------------------------------------------------------------------------

_TEXT_WEIGHTS = {
    "cer": 0.20,
    "line_recall": 0.10,
    "line_precision": 0.10,
    "text_drop_rate": 0.10,
}

_BUSINESS_WEIGHTS = {
    "question_number_em": 0.15,
    "option_set_em": 0.10,
    "answer_em": 0.15,
    "question_count_match": 0.05,
}

_CODE_WEIGHTS = {
    "bracket_balance_rate": 0.02,
    "code_token_em": 0.02,
    "comparison_op_preserved": 0.01,
}

# ---------------------------------------------------------------------------
# Line-level metrics
# ---------------------------------------------------------------------------


def compute_line_metrics(gt: str, ocr: str) -> LineLevelMetrics:
    """计算行级 OCR 质量指标。"""
    gt_clean = gt.replace("\r\n", "\n").strip()
    ocr_clean = ocr.replace("\r\n", "\n").strip()

    cer = character_error_rate(gt_clean, ocr_clean)

    gt_lines = [l for l in gt_clean.split("\n") if l.strip()]
    ocr_lines = [l for l in ocr_clean.split("\n") if l.strip()]

    lr_matched, lr_total = _line_recall(gt_lines, ocr_lines)
    lr = lr_matched / max(lr_total, 1)

    lp_matched, lp_total = _line_precision(gt_lines, ocr_lines)
    lp = lp_matched / max(lp_total, 1)

    drop = _text_drop_rate(gt_clean, ocr_clean)

    # WER: word-level edit distance
    wer = _word_error_rate(gt_clean, ocr_clean)

    return LineLevelMetrics(
        cer=round(cer, 4),
        wer=round(wer, 4),
        text_drop_rate=round(drop, 4),
        line_recall=round(lr, 4),
        line_precision=round(lp, 4),
    )


def _word_error_rate(gt: str, ocr: str) -> float:
    gt_words = gt.split()
    ocr_words = ocr.split()
    if not gt_words:
        return 0.0 if not ocr_words else 1.0
    if not ocr_words:
        return 1.0

    matcher = difflib.SequenceMatcher(None, gt_words, ocr_words)
    errors = 0
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "replace":
            errors += max(i2 - i1, j2 - j1)
        elif op == "delete":
            errors += i2 - i1
        elif op == "insert":
            errors += j2 - j1
    return errors / len(gt_words)


# ---------------------------------------------------------------------------
# Business metrics
# ---------------------------------------------------------------------------


_QUESTION_NUM_PATTERN = re.compile(r"(?:^|\n)\s*(\d+)[.、．）)\s]")
_OPTION_KEY_PATTERN = re.compile(r"(?:^|\n)\s*([A-D])[.、．）)\s]")
_ANSWER_PATTERN = re.compile(
    r"(?:答案|【答案】|参考答案|正确答案|KEY)\s*[：: ]?\s*([A-D]+|[TF])",
    re.IGNORECASE,
)

# Roman numeral line pattern for question number extraction
_ROMAN_QN_LINE = re.compile(r"^\s*(I{1,3}|IV|VI{0,3}|[ⅰ-ⅹ]+)\s*[.、）)\s]")


def extract_question_numbers(text: str) -> list[int]:
    """从 OCR 文本中提取题号列表。

    Uses the unified ``question_numbering.parse_numbering`` for primary
    parsing (Arabic, Chinese, parenthesized), with Roman numeral fallback.
    """
    from app.features.question_numbering import NumberingType, parse_numbering

    seen: set[int] = set()
    result: list[int] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue

        # Try unified parser first
        parsed = parse_numbering(stripped)
        if parsed is not None and parsed.numbering_type in (
            NumberingType.MAIN_QUESTION,
            NumberingType.SUB_QUESTION,
        ):
            num = parsed.normalized_value
            if num not in seen:
                seen.add(num)
                result.append(num)
            continue

        # Roman numeral fallback: I. II. III. as question numbers
        m = _ROMAN_QN_LINE.match(stripped)
        if m:
            num = _roman_to_int(m.group(1))
            if num and num not in seen:
                seen.add(num)
                result.append(num)

    return result


def _roman_to_int(s: str) -> int | None:
    """Convert Roman numeral string to integer."""
    roman_map = {
        "I": 1, "V": 5, "X": 10,
        "ⅰ": 1, "ⅱ": 2, "ⅲ": 3, "ⅳ": 4, "ⅴ": 5,
        "ⅵ": 6, "ⅶ": 7, "ⅷ": 8, "ⅸ": 9, "ⅹ": 10,
        "Ⅰ": 1, "Ⅱ": 2, "Ⅲ": 3, "Ⅳ": 4, "Ⅴ": 5,
        "Ⅵ": 6, "Ⅶ": 7, "Ⅷ": 8, "Ⅸ": 9, "Ⅹ": 10,
    }
    # ASCII Roman
    ascii_map = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5,
                 "VI": 6, "VII": 7, "VIII": 8}
    if s in ascii_map:
        return ascii_map[s]
    # Unicode Roman
    if all(c in roman_map for c in s):
        return sum(roman_map[c] for c in s)
    return None


_ROMAN_QN_LINE = re.compile(r"^\s*(I{1,3}|IV|VI{0,3}|[ⅰ-ⅹ]+)\s*[.、）)\s]")


def _extract_current_qn(line: str) -> int | None:
    """Extract the current question number from a line (if it starts one)."""
    from app.features.question_numbering import NumberingType, parse_numbering

    parsed = parse_numbering(line)
    if parsed is not None and parsed.numbering_type in (
        NumberingType.MAIN_QUESTION,
        NumberingType.SUB_QUESTION,
    ):
        return parsed.normalized_value

    m = _ROMAN_QN_LINE.match(line)
    if m:
        return _roman_to_int(m.group(1))

    return None


def extract_option_keys(text: str) -> dict[int, set[str]]:
    """从 OCR 文本中提取每题选项键集合。"""
    lines = text.split("\n")
    result: dict[int, set[str]] = {}
    current_q = 0

    for line in lines:
        qn = _extract_current_qn(line)
        if qn is not None:
            current_q = qn
            if current_q not in result:
                result[current_q] = set()

        om = _OPTION_KEY_PATTERN.search(line)
        if om and current_q > 0:
            result[current_q].add(om.group(1))

    return result


def extract_answers(text: str) -> dict[str, str]:
    """从 OCR 文本中提取答案。"""
    result: dict[str, str] = {}
    for m in _ANSWER_PATTERN.finditer(text):
        ans = m.group(1).strip()
        if ans:
            result.setdefault(str(len(result) + 1), ans)
    return result


def compute_business_metrics(
    gt: str,
    ocr: str,
    expected_qnumbers: list[int] | None = None,
    expected_options: dict[str, list[str]] | None = None,
    expected_answers: dict[str, str] | None = None,
) -> BusinessMetrics:
    """计算业务级指标。

    支持两种模式：
    1. 从 GT/OCR 文本自动提取并比较（当明确期望未提供时）
    2. 与明确期望比较（当 expected_* 提供时）
    """
    gt_qnums = extract_question_numbers(gt)
    ocr_qnums = extract_question_numbers(ocr)
    gt_opts = extract_option_keys(gt)
    ocr_opts = extract_option_keys(ocr)
    gt_answers = extract_answers(gt)
    ocr_answers = extract_answers(ocr)

    # Question number exact match (Jaccard)
    if expected_qnumbers:
        gt_qnum_set = set(expected_qnumbers)
    else:
        gt_qnum_set = set(gt_qnums)
    ocr_qnum_set = set(ocr_qnums)

    qn_union = gt_qnum_set | ocr_qnum_set
    qn_intersection = gt_qnum_set & ocr_qnum_set
    qn_em = len(qn_intersection) / max(len(qn_union), 1) if qn_union else 1.0

    # Option set exact match (per question)
    if expected_options:
        gt_opt_sets = {
            int(k): set(v) for k, v in expected_options.items()
        }
    else:
        gt_opt_sets = gt_opts

    opt_matches = 0
    opt_total = len(gt_opt_sets) or 1
    for qnum, exp_keys in gt_opt_sets.items():
        found_keys = ocr_opts.get(qnum, set())
        if exp_keys == found_keys:
            opt_matches += 1
    opt_em = opt_matches / opt_total

    # Answer exact match
    if expected_answers:
        answer_src = expected_answers
    else:
        answer_src = gt_answers
    ans_matches = 0
    ans_total = len(answer_src) or 1
    for qno, exp_ans in answer_src.items():
        if ocr_answers.get(qno, "") == exp_ans:
            ans_matches += 1
    ans_em = ans_matches / ans_total

    # Question count match
    count_match = len(ocr_qnum_set) == len(gt_qnum_set)
    if expected_qnumbers:
        count_match = len(ocr_qnum_set) == len(expected_qnumbers)

    return BusinessMetrics(
        question_number_em=round(qn_em, 4),
        option_set_em=round(opt_em, 4),
        answer_em=round(ans_em, 4),
        question_count_match=count_match,
    )


# ---------------------------------------------------------------------------
# Code metrics
# ---------------------------------------------------------------------------


_CODE_SYMBOL_PATTERNS: dict[str, re.Pattern] = {
    "arrow": re.compile(r"->"),
    "eq": re.compile(r"=="),
    "neq": re.compile(r"!="),
    "leq": re.compile(r"<="),
    "geq": re.compile(r">="),
    "ptr": re.compile(r"\*"),
    "ref": re.compile(r"&"),
    "inc": re.compile(r"\+\+"),
    "dec": re.compile(r"--"),
    "template": re.compile(r"<[A-Za-z_][A-Za-z0-9_]*>"),
}

_BRACKET_PAIRS: list[tuple[re.Pattern, re.Pattern, str]] = [
    (re.compile(r"\("), re.compile(r"\)"), "()"),
    (re.compile(r"\["), re.compile(r"\]"), "[]"),
    (re.compile(r"\{"), re.compile(r"\}"), "{}"),
]


def compute_code_metrics(gt: str, ocr: str) -> CodeMetrics:
    """计算代码题专项指标。

    比较操作符保留、括号平衡、代码 token 精确匹配。
    """
    # Comparison operator preservation
    op_preserved: list[float] = []
    for name, pat in _CODE_SYMBOL_PATTERNS.items():
        gt_count = len(pat.findall(gt))
        ocr_count = len(pat.findall(ocr))
        if gt_count > 0:
            op_preserved.append(min(ocr_count / gt_count, 1.0))
        else:
            op_preserved.append(1.0)
    comp_op_rate = sum(op_preserved) / max(len(op_preserved), 1)

    # Bracket balance
    bracket_scores: list[float] = []
    for open_pat, close_pat, _name in _BRACKET_PAIRS:
        gt_open = len(open_pat.findall(gt))
        gt_close = len(close_pat.findall(gt))
        ocr_open = len(open_pat.findall(ocr))
        ocr_close = len(close_pat.findall(ocr))

        gt_balanced = gt_open == gt_close
        ocr_balanced = ocr_open == ocr_close

        if gt_balanced and ocr_balanced:
            bracket_scores.append(1.0)
        elif not gt_balanced and not ocr_balanced:
            bracket_scores.append(1.0)
        else:
            bracket_scores.append(0.0)

    bracket_rate = sum(bracket_scores) / max(len(bracket_scores), 1)

    # Code token exact match (identifiers, keywords, operators)
    code_tokens_gt = _extract_code_tokens(gt)
    code_tokens_ocr = _extract_code_tokens(ocr)
    if code_tokens_gt:
        gt_set = set(code_tokens_gt)
        ocr_set = set(code_tokens_ocr)
        token_intersection = gt_set & ocr_set
        token_union = gt_set | ocr_set
        token_em = len(token_intersection) / max(len(token_union), 1)
    else:
        token_em = 1.0

    return CodeMetrics(
        bracket_balance_rate=round(bracket_rate, 4),
        code_token_em=round(token_em, 4),
        comparison_op_preserved=round(comp_op_rate, 4),
        code_structure_ok=bracket_rate >= 0.8 and token_em >= 0.8,
    )


_CODE_TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|->|==|!=|<=|>=|\+\+|--|[*&<>=+\-*/%]")

def _extract_code_tokens(text: str) -> list[str]:
    return _CODE_TOKEN_PATTERN.findall(text)


def compute_reading_order_metrics(
    gt: str,
    ocr: str,
    expected_qnumbers: list[int] | None = None,
    expected_options: dict[str, list[str]] | None = None,
) -> ReadingOrderMetrics:
    """Compute reading order metrics from text.

    Uses question number and option key ordering in text to infer
    reading order quality, without requiring geometry data.

    When explicit region ordering data is not available, estimates
    order quality from sequential content patterns.
    """
    gt_qnums = extract_question_numbers(gt)
    ocr_qnums = extract_question_numbers(ocr)

    # Question number order accuracy: are question numbers in sequence?
    if len(gt_qnums) >= 2:
        gt_pairs = set()
        for i in range(len(gt_qnums) - 1):
            gt_pairs.add((gt_qnums[i], gt_qnums[i + 1]))
        ocr_pairs = set()
        for i in range(len(ocr_qnums) - 1):
            ocr_pairs.add((ocr_qnums[i], ocr_qnums[i + 1]))

        qn_preserved = len(gt_pairs & ocr_pairs)
        qn_total = len(gt_pairs)
        qn_order_acc = qn_preserved / max(qn_total, 1)
    else:
        qn_order_acc = 1.0

    # Pairwise order accuracy: compare line order
    gt_lines = [l.strip() for l in gt.split("\n") if l.strip()]
    ocr_lines = [l.strip() for l in ocr.split("\n") if l.strip()]
    pairwise_acc = _pairwise_order_accuracy(gt_lines, ocr_lines)

    # Sequence exact match: full reordering match
    seq_match = 1.0 if _sequence_exact_match(gt_lines, ocr_lines) else 0.0

    # Option order accuracy
    gt_opts = extract_option_keys(gt)
    ocr_opts = extract_option_keys(ocr)
    opt_order_acc = _option_order_accuracy(gt_opts, ocr_opts)

    # Cross-column error rate: estimate from how often OCR has
    # interleaved question content (detected by question numbers
    # being out of order)
    cross_col_err = 0.0
    if len(ocr_qnums) >= 2:
        out_of_order = sum(
            1 for i in range(len(ocr_qnums) - 1)
            if ocr_qnums[i] > ocr_qnums[i + 1]
        )
        cross_col_err = out_of_order / max(len(ocr_qnums) - 1, 1)

    # Header/footer leak: estimate from text lines that appear
    # to be page numbers or running headers in body content
    hf_leak = _estimate_header_footer_leak(gt, ocr)

    return ReadingOrderMetrics(
        pairwise_order_accuracy=round(pairwise_acc, 4),
        sequence_exact_match=round(seq_match, 4),
        question_number_order_accuracy=round(qn_order_acc, 4),
        option_order_accuracy=round(opt_order_acc, 4),
        cross_column_error_rate=round(cross_col_err, 4),
        header_footer_leak_rate=round(hf_leak, 4),
        reading_order_low_confidence_rate=0.0,
    )


def _pairwise_order_accuracy(reference: list[str], hypothesis: list[str]) -> float:
    """Compute pairwise order accuracy: fraction of pairwise orderings
    preserved in hypothesis relative to reference.

    Measures how many pairs of items appear in the same relative order.
    """
    if len(reference) < 2:
        return 1.0

    ref_indices = {item: i for i, item in enumerate(reference) if item in hypothesis}
    # Map hypothesis to reference indices
    hyp_indices = []
    for item in hypothesis:
        if item in ref_indices:
            hyp_indices.append(ref_indices[item])

    preserved = 0
    total = 0
    for i in range(len(hyp_indices)):
        for j in range(i + 1, len(hyp_indices)):
            total += 1
            if hyp_indices[i] < hyp_indices[j]:
                preserved += 1

    return preserved / max(total, 1)


def _sequence_exact_match(reference: list[str], hypothesis: list[str]) -> bool:
    """Full sequence match: hypothesis must contain all reference
    items in the correct order (may have extra items)."""
    # Filter hypothesis to only items in reference, preserving order
    filtered = [item for item in hypothesis if item in reference]
    return filtered == reference


def _option_order_accuracy(
    gt_opts: dict[int, set[str]],
    ocr_opts: dict[int, set[str]],
) -> float:
    """Compare option key ordering between GT and OCR."""
    scores: list[float] = []
    for qnum in gt_opts:
        if qnum not in ocr_opts:
            continue
        gt_list = sorted(gt_opts[qnum])
        ocr_list = sorted(ocr_opts[qnum])
        # Compute pairwise order preservation
        preserved = 0
        total = 0
        for i in range(len(ocr_list)):
            for j in range(i + 1, len(ocr_list)):
                total += 1
                gi = gt_list.index(ocr_list[i]) if ocr_list[i] in gt_list else -1
                gj = gt_list.index(ocr_list[j]) if ocr_list[j] in gt_list else -1
                if gi >= 0 and gj >= 0 and gi < gj:
                    preserved += 1
        scores.append(preserved / max(total, 1) if total > 0 else 1.0)

    return sum(scores) / max(len(scores), 1) if scores else 1.0


_PAGE_NUM_PATTERN = re.compile(r"^\s*[-–—]?\s*\d+\s*[-–—]?\s*$")
_HEADER_PATTERN = re.compile(r"^(第[\d一二三四五六七八九十]+[页章节]|[\d]+\s*/\s*\d+)")


def _estimate_header_footer_leak(gt: str, ocr: str) -> float:
    """Estimate header/footer leak rate from OCR text.

    Counts lines in OCR that look like page numbers or headers
    relative to total lines.
    """
    ocr_lines = [l.strip() for l in ocr.split("\n") if l.strip()]
    if not ocr_lines:
        return 0.0

    suspicious = 0
    for line in ocr_lines:
        if _PAGE_NUM_PATTERN.match(line):
            suspicious += 1
        elif _HEADER_PATTERN.match(line):
            suspicious += 1
        elif len(line) <= 3 and line.isdigit():
            suspicious += 1

    return suspicious / len(ocr_lines)


# ---------------------------------------------------------------------------
# Overall score
# ---------------------------------------------------------------------------


def compute_overall_score(
    line: LineLevelMetrics,
    business: BusinessMetrics,
    code: CodeMetrics,
    scenario: ScenarioBucket,
) -> float:
    """加权综合评分 (0-100)。"""
    # Line score: invert CER and drop rate
    line_score = (
        _TEXT_WEIGHTS["cer"] * max(0, 1 - line.cer)
        + _TEXT_WEIGHTS["line_recall"] * line.line_recall
        + _TEXT_WEIGHTS["line_precision"] * line.line_precision
        + _TEXT_WEIGHTS["text_drop_rate"] * max(0, 1 - line.text_drop_rate)
    )

    # Business score
    biz_score = (
        _BUSINESS_WEIGHTS["question_number_em"] * business.question_number_em
        + _BUSINESS_WEIGHTS["option_set_em"] * business.option_set_em
        + _BUSINESS_WEIGHTS["answer_em"] * business.answer_em
        + _BUSINESS_WEIGHTS["question_count_match"] * (1.0 if business.question_count_match else 0.0)
    )

    # Code score (only significant for code scenarios)
    is_code = scenario in (ScenarioBucket.CODE_C, ScenarioBucket.CODE_CPP)
    if is_code:
        code_w = sum(_CODE_WEIGHTS.values())
        code_score = (
            _CODE_WEIGHTS["bracket_balance_rate"] * code.bracket_balance_rate
            + _CODE_WEIGHTS["code_token_em"] * code.code_token_em
            + _CODE_WEIGHTS["comparison_op_preserved"] * code.comparison_op_preserved
        )
    else:
        code_w = 0.0
        code_score = 0.0

    total_w = (
        sum(_TEXT_WEIGHTS.values())
        + sum(_BUSINESS_WEIGHTS.values())
        + code_w
    )
    raw = (line_score + biz_score + code_score) / max(total_w, 1)
    return round(raw * 100, 1)


# ---------------------------------------------------------------------------
# Full evaluation
# ---------------------------------------------------------------------------

_SCORE_PASS = 80.0


def evaluate(
    case_id: str,
    scenario: ScenarioBucket,
    gt: str,
    ocr: str,
    *,
    expected_qnumbers: list[int] | None = None,
    expected_options: dict[str, list[str]] | None = None,
    expected_answers: dict[str, str] | None = None,
    duration_ms: float = 0.0,
) -> MetricsResult:
    """对单个 case 运行完整评估。"""
    line = compute_line_metrics(gt, ocr)
    business = compute_business_metrics(gt, ocr, expected_qnumbers, expected_options, expected_answers)
    code = compute_code_metrics(gt, ocr)
    reading_order = compute_reading_order_metrics(gt, ocr, expected_qnumbers, expected_options)

    score = compute_overall_score(line, business, code, scenario)

    return MetricsResult(
        case_id=case_id,
        scenario=scenario,
        line=line,
        business=business,
        code=code,
        reading_order=reading_order,
        overall_score=score,
        passed=score >= _SCORE_PASS,
        duration_ms=duration_ms,
        details={
            "gt_len": len(gt),
            "ocr_len": len(ocr),
        },
    )


def scenario_pass_rate(results: list[MetricsResult]) -> dict[str, dict[str, Any]]:
    """按场景计算通过率。"""
    buckets: dict[str, list[MetricsResult]] = {}
    for r in results:
        buckets.setdefault(r.scenario.value, []).append(r)

    report: dict[str, dict[str, Any]] = {}
    for bucket, cases in sorted(buckets.items()):
        n = len(cases)
        passed = sum(1 for c in cases if c.passed)
        avg_score = sum(c.overall_score for c in cases) / max(n, 1)
        avg_cer = sum(c.line.cer for c in cases) / max(n, 1)
        avg_ans_em = sum(c.business.answer_em for c in cases) / max(n, 1)
        report[bucket] = {
            "count": n,
            "passed": passed,
            "pass_rate": round(passed / max(n, 1), 4),
            "avg_score": round(avg_score, 1),
            "avg_cer": round(avg_cer, 4),
            "avg_answer_em": round(avg_ans_em, 4),
            "cases": [c.case_id for c in cases],
        }

    return report
