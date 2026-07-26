"""OCR 回归失败案例自动分类器 — 纯规则引擎。

每种分类器返回 list[tuple[str, float, str]]，即 (失败类型, 置信度, 证据)。
编排函数 classify_failures 汇总所有分类结果，按置信度降序排列。
"""

import difflib
import re

# ---------------------------------------------------------------------------
# 失败类型常量
# ---------------------------------------------------------------------------

FT_QUESTION_NUMBER_LOSS = "题号丢失"
FT_OPTION_MISALIGNMENT = "选项错位"
FT_FORMULA_DAMAGE = "公式损坏"
FT_TWO_COLUMN_SERIAL = "两栏串行"
FT_WATERMARK_POLLUTION = "水印污染"
FT_PAGE_BREAK_ARTIFACT = "分页断裂"
FT_TABLE_LOSS = "表格丢失"

# ---------------------------------------------------------------------------
# 从 text_normalizer 导入的规则（单一真实来源）
# ---------------------------------------------------------------------------

_WATERMARK_RE: re.Pattern | None = None


def _get_watermark_re() -> re.Pattern:
    global _WATERMARK_RE
    if _WATERMARK_RE is None:
        try:
            from app.features.text_normalizer import _RE_WATERMARK

            _WATERMARK_RE = _RE_WATERMARK
        except ImportError:
            _WATERMARK_RE = re.compile(r"$^")  # 永不匹配
    return _WATERMARK_RE


# ---------------------------------------------------------------------------
# 公式检测（与 metrics.py 保持一致的简化版）
# ---------------------------------------------------------------------------

_FORMULA_SIGNALS = re.compile(
    r"\\[a-zA-Z]+|∫|∑|∏|√|∂|∇|∞|→|≤|≥|≠|±|×|÷|\[\[|\]\]|lim|sin|cos|log|det",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# 分类函数
# ---------------------------------------------------------------------------


def classify_question_number_loss(
    expected_numbers: set[int], found_numbers: set[int]
) -> list[tuple[str, float, str]]:
    """题号丢失：预期题号中有哪些未识别到。"""
    missing = expected_numbers - found_numbers
    if missing:
        conf = len(missing) / max(len(expected_numbers), 1)
        return [
            (
                FT_QUESTION_NUMBER_LOSS,
                round(conf, 3),
                f"缺失题号: {sorted(missing)}",
            )
        ]
    return []


def classify_option_misalignment(
    expected_opts: dict[int, dict[str, str]],
    found_opts: dict[int, dict[str, str]],
) -> list[tuple[str, float, str]]:
    """选项错位：选项键不匹配 或 选项文本严重偏移。"""
    misaligned: list[int] = []
    for qnum, exp_opts in expected_opts.items():
        found = found_opts.get(qnum, {})
        exp_keys = set(exp_opts.keys())
        found_keys = set(found.keys())
        if not exp_keys:
            continue
        # 键完全缺失
        if not found_keys:
            misaligned.append(qnum)
            continue
        # 键集合不一致
        if exp_keys != found_keys:
            misaligned.append(qnum)
            continue
        # 键一致但文本差异大
        for key in exp_keys:
            if key in found:
                ratio = difflib.SequenceMatcher(
                    None, exp_opts[key], found[key]
                ).ratio()
                if ratio < 0.7:
                    misaligned.append(qnum)
                    break

    if misaligned:
        conf = len(misaligned) / max(len(expected_opts), 1)
        return [
            (
                FT_OPTION_MISALIGNMENT,
                round(conf, 3),
                f"选项错位题目: {sorted(misaligned)}",
            )
        ]
    return []


def classify_formula_damage(
    reference: str, hypothesis: str, threshold: float = 0.8
) -> list[tuple[str, float, str]]:
    """公式损坏：公式字符保真率低于阈值。"""
    from tests.ocr_regression.metrics import _extract_formula_chars

    ref_formula = _extract_formula_chars(reference)
    hyp_formula = _extract_formula_chars(hypothesis)

    if not ref_formula and not hyp_formula:
        return []

    ref_set = set(ref_formula)
    hyp_set = set(hyp_formula)
    if not ref_set:
        return []

    lost = ref_set - hyp_set
    if not lost:
        return []

    # 检查是否有公式信号丢失
    ref_signals = set(_FORMULA_SIGNALS.findall(reference))
    hyp_signals = set(_FORMULA_SIGNALS.findall(hypothesis))
    lost_signals = ref_signals - hyp_signals

    fidelity = len(ref_set & hyp_set) / max(len(ref_set), 1)
    if fidelity < threshold:
        evidence_parts = []
        if lost_signals:
            evidence_parts.append(f"公式信号丢失: {sorted(lost_signals)[:5]}")
        evidence_parts.append(
            f"公式保真率: {fidelity:.2f} (阈值: {threshold})"
        )
        return [
            (
                FT_FORMULA_DAMAGE,
                round(1.0 - fidelity, 3),
                "; ".join(evidence_parts),
            )
        ]
    return []


def classify_two_column_serial(
    questions: list[dict],
) -> list[tuple[str, float, str]]:
    """两栏串行：检查 risk_flags 中的双栏合并信号。"""
    affected: list[int] = []
    for q in questions:
        flags = q.get("risk_flags") or []
        if any("two_column" in f for f in flags):
            affected.append(q.get("number", 0))
        # 选项键交错也是双栏特征
        opt_keys = list(q.get("option_lines", {}).keys())
        if len(opt_keys) >= 3:
            # 检查是否有 A, C, B, D 这样的交错顺序
            expected_order = ["A", "B", "C", "D", "E", "F", "G"]
            indices = [
                expected_order.index(k) if k in expected_order else 999
                for k in opt_keys
            ]
            if indices != sorted(indices):
                affected.append(q.get("number", 0))

    if affected:
        affected = list(set(affected))
        conf = 0.8 if affected else 0.0
        return [
            (
                FT_TWO_COLUMN_SERIAL,
                round(conf, 3),
                f"两栏串行题目: {sorted(affected)}",
            )
        ]
    return []


def classify_watermark_pollution(
    questions: list[dict],
) -> list[tuple[str, float, str]]:
    """水印污染：题目文本中仍残留水印/页眉/页脚标记。"""
    wm_re = _get_watermark_re()
    contaminated: list[int] = []
    for q in questions:
        text = q.get("raw_question_text", "")
        if wm_re.search(text):
            contaminated.append(q.get("number", 0))

    if contaminated:
        conf = len(contaminated) / max(len(questions), 1)
        return [
            (
                FT_WATERMARK_POLLUTION,
                round(conf, 3),
                f"含水印题目: {sorted(contaminated)}",
            )
        ]
    return []


def classify_page_break_artifact(
    questions: list[dict],
    structure: dict | None = None,
) -> list[tuple[str, float, str]]:
    """分页断裂：选项不完整 且 page_start != page_end。"""
    affected: list[int] = []
    for q in questions:
        if not q.get("has_options"):
            continue
        opts = q.get("option_lines", {})
        page_start = q.get("page_start", 1)
        page_end = q.get("page_end", 1)
        if len(opts) < 3 and page_start != page_end:
            affected.append(q.get("number", 0))

    if affected:
        conf = len(affected) / max(
            sum(1 for q in questions if q.get("has_options")), 1
        )
        return [
            (
                FT_PAGE_BREAK_ARTIFACT,
                round(conf, 3),
                f"跨页断裂题目: {sorted(affected)}",
            )
        ]
    return []


def classify_table_loss(
    expected_text: str, actual_text: str, min_block_size: int = 30
) -> list[tuple[str, float, str]]:
    """表格丢失：预期中有表格结构但实际输出中大块丢失。"""
    ref = expected_text.replace("\n", " ").strip()
    hyp = actual_text.replace("\n", " ").strip()

    matcher = difflib.SequenceMatcher(None, ref, hyp)
    lost_blocks: list[str] = []
    total_deleted = 0
    for op, i1, i2, _j1, _j2 in matcher.get_opcodes():
        if op == "delete":
            block = ref[i1:i2]
            total_deleted += len(block)
            if len(block) >= min_block_size:
                lost_blocks.append(block)

    if not lost_blocks:
        return []

    # 检测表格特征：对齐的数字列、多个空格分隔的值
    table_like = 0
    for block in lost_blocks:
        lines = block.strip().split()
        if len(lines) >= 3:
            # 多列数字 = 表格特征
            num_count = sum(1 for w in lines if re.match(r"^-?\d+\.?\d*$", w))
            if num_count >= 2:
                table_like += 1

    if table_like > 0:
        conf = min(0.9, total_deleted / max(len(ref), 1) * 3)
        return [
            (
                FT_TABLE_LOSS,
                round(conf, 3),
                f"疑似表格丢失: {table_like} 块, 共 {total_deleted} 字符",
            )
        ]
    return []


# ---------------------------------------------------------------------------
# 编排函数
# ---------------------------------------------------------------------------


def classify_failures(
    expected_text: str,
    actual_text: str,
    expected_numbers: set[int],
    found_numbers: set[int],
    expected_options: dict[int, dict[str, str]],
    found_options: dict[int, dict[str, str]],
    questions: list[dict],
    structure: dict | None = None,
) -> list[dict]:
    """运行所有分类器，返回按置信度降序排列的失败列表。"""
    results: list[tuple[str, float, str]] = []
    results.extend(classify_question_number_loss(expected_numbers, found_numbers))
    results.extend(
        classify_option_misalignment(expected_options, found_options)
    )
    results.extend(classify_formula_damage(expected_text, actual_text))
    results.extend(classify_two_column_serial(questions))
    results.extend(classify_watermark_pollution(questions))
    results.extend(classify_page_break_artifact(questions, structure))
    results.extend(classify_table_loss(expected_text, actual_text))
    results.sort(key=lambda x: x[1], reverse=True)
    return [
        {"type": t, "confidence": round(c, 3), "evidence": e}
        for t, c, e in results
    ]
