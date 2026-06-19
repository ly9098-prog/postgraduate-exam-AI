"""OCR 回归评测扩展指标 — 纯标准库实现。

在 tests.ocr_eval.metrics 的 4 个基础函数之上增加了：
- 字符准确率 / 编辑距离
- 题号识别准确率
- 选项结构准确率
- 公式保真率
- OCR 综合质量分
"""

import difflib
import re

from tests.ocr_eval.metrics import (
    character_error_rate,
    line_precision,
    line_recall,
    text_drop_rate,
)

# ---------------------------------------------------------------------------
# 权重常量（可调）
# ---------------------------------------------------------------------------

_WEIGHTS = {
    "character_accuracy": 0.30,
    "line_recall": 0.15,
    "line_precision": 0.15,
    "question_number_accuracy": 0.20,
    "option_structure_accuracy": 0.10,
    "formula_fidelity": 0.10,
}

# ---------------------------------------------------------------------------
# 基础扩展指标
# ---------------------------------------------------------------------------


def character_accuracy(reference: str, hypothesis: str) -> float:
    """字符准确率 = 1 - CER。"""
    return 1.0 - character_error_rate(reference, hypothesis)


def edit_distance(reference: str, hypothesis: str) -> int:
    """编辑距离：基于 SequenceMatcher 操作计数的 Levenshtein 近似值。"""
    ref = reference.replace("\n", " ").strip()
    hyp = hypothesis.replace("\n", " ").strip()
    if not ref:
        return len(hyp)
    if not hyp:
        return len(ref)

    matcher = difflib.SequenceMatcher(None, ref, hyp)
    edits = 0
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "replace":
            edits += max(i2 - i1, j2 - j1)
        elif op == "delete":
            edits += i2 - i1
        elif op == "insert":
            edits += j2 - j1
    return edits


# ---------------------------------------------------------------------------
# 结构化指标
# ---------------------------------------------------------------------------


def question_number_accuracy(
    expected_numbers: set[int], found_numbers: set[int]
) -> float:
    """题号识别准确率：Jaccard 相似度。"""
    if not expected_numbers and not found_numbers:
        return 1.0
    union = expected_numbers | found_numbers
    if not union:
        return 0.0
    intersection = expected_numbers & found_numbers
    return len(intersection) / len(union)


def option_structure_accuracy(
    expected_options: dict[int, set[str]],
    found_options: dict[int, set[str]],
) -> float:
    """选项结构准确率：每题选项键集合的匹配率。"""
    if not expected_options:
        return 1.0
    correct = 0
    for qnum, exp_keys in expected_options.items():
        found_keys = found_options.get(qnum, set())
        if exp_keys == found_keys:
            correct += 1
    return correct / len(expected_options)


# ---------------------------------------------------------------------------
# 公式保真率
# ---------------------------------------------------------------------------

_FORMULA_PATTERN = re.compile(
    r"\\[a-zA-Z]+|∫|∑|∏|√|∂|∇|∞|→|⇒|⇔|≤|≥|≠|±|×|÷"
    r"|\[\[.*?\]\]|lim|sin|cos|tan|log|det|dx|dy"
    r"|\^[0-9]|_[0-9]|[α-ω]",
    re.IGNORECASE,
)


def _extract_formula_chars(text: str) -> str:
    """提取文本中属于公式区域的字符。"""
    return "".join(_FORMULA_PATTERN.findall(text))


def formula_fidelity(reference: str, hypothesis: str) -> float:
    """公式保真率：公式字符区域的 CER 取反。"""
    ref_formula = _extract_formula_chars(reference)
    hyp_formula = _extract_formula_chars(hypothesis)
    if not ref_formula:
        return 1.0 if not hyp_formula else 0.0
    return 1.0 - character_error_rate(ref_formula, hyp_formula)


# ---------------------------------------------------------------------------
# OCR 综合质量分
# ---------------------------------------------------------------------------


def ocr_quality_score(
    reference: str,
    hypothesis: str,
    expected_numbers: set[int],
    found_numbers: set[int],
    expected_opt_keys: dict[int, set[str]],
    found_opt_keys: dict[int, set[str]],
    ref_lines: list[str],
    hyp_lines: list[str],
) -> dict:
    """加权综合 OCR 质量分（0-100）。"""
    char_acc = character_accuracy(reference, hypothesis)

    recall_matched, recall_total = line_recall(ref_lines, hyp_lines)
    prec_matched, prec_total = line_precision(ref_lines, hyp_lines)
    line_rec = recall_matched / max(recall_total, 1)
    line_prec_val = prec_matched / max(prec_total, 1)

    qnum_acc = question_number_accuracy(expected_numbers, found_numbers)
    opt_acc = option_structure_accuracy(expected_opt_keys, found_opt_keys)
    formula_fid = formula_fidelity(reference, hypothesis)

    score = (
        _WEIGHTS["character_accuracy"] * char_acc
        + _WEIGHTS["line_recall"] * line_rec
        + _WEIGHTS["line_precision"] * line_prec_val
        + _WEIGHTS["question_number_accuracy"] * qnum_acc
        + _WEIGHTS["option_structure_accuracy"] * opt_acc
        + _WEIGHTS["formula_fidelity"] * formula_fid
    ) * 100

    return {
        "score": round(score, 1),
        "character_accuracy": round(char_acc, 4),
        "character_error_rate": round(1.0 - char_acc, 4),
        "line_recall": round(line_rec, 4),
        "line_precision": round(line_prec_val, 4),
        "question_number_accuracy": round(qnum_acc, 4),
        "option_structure_accuracy": round(opt_acc, 4),
        "formula_fidelity": round(formula_fid, 4),
        "edit_distance": edit_distance(reference, hypothesis),
        "text_drop_rate": round(text_drop_rate(reference, hypothesis), 4),
    }
