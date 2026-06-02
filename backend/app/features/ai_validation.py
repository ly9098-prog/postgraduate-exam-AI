"""AI 标准化结果校验 — 检测 AI 修复产出的常见异常。

在 ai_repair 之后对修复结果做二次校验：
- 重复题干拼接（AI 把 stem 重复了一遍或多遍）
- 字段污染（答案/解析内容混入 stem，或 stem 内容混入 answer）
- JSON 结构异常（字段类型错误、选项格式异常）
- 异常长度（修复后 stem 异常膨胀或缩短）

校验结果不阻塞管线，以 warnings 和 flags 形式附加到题目上。
"""

import re


def _detect_duplicate_stem(stem: str, raw_text: str = "") -> str | None:
    """检测 stem 是否被重复拼接。"""
    if not stem or len(stem) < 20:
        return None

    # Method 1: Check if stem is approximately doubled
    half = len(stem) // 2
    first_half = stem[:half]
    second_half = stem[half:half + len(first_half)]

    # Use ratio comparison for halves
    import difflib
    ratio = difflib.SequenceMatcher(None, first_half, second_half).ratio()
    if ratio >= 0.85:
        return "stem_duplicated"

    # Method 2: Check for repeated long substrings (>= 15 chars)
    check_len = min(40, len(stem) // 2)
    for length in range(check_len, 14, -1):
        for start in range(0, len(stem) - length * 2 + 1, 5):
            fragment = stem[start:start + length]
            rest = stem[start + length:]
            if fragment in rest:
                return "stem_repeated_fragment"

    return None


def _detect_field_pollution(stem: str, answer: str, analysis: str) -> list[str]:
    """检测字段间内容污染。"""
    issues = []

    # 答案标签混入 stem
    answer_labels = re.compile(
        r"(?:【答案】|答案[：:]|参考答案[：:]|正确答案[：:])\s*[A-D]",
    )
    if answer_labels.search(stem):
        issues.append("answer_label_in_stem")

    # 解析标签混入 stem
    analysis_labels = re.compile(
        r"(?:【解析】|解析[：:]|解答[：:]|详解[：:])",
    )
    if analysis_labels.search(stem):
        issues.append("analysis_label_in_stem")

    # stem 内容大量出现在 answer 中（反向污染）
    if answer and stem and len(answer) > 30:
        stem_clean = re.sub(r"\s+", "", stem)
        answer_clean = re.sub(r"\s+", "", answer)
        if len(stem_clean) >= 15 and stem_clean[:15] in answer_clean:
            issues.append("stem_content_in_answer")

    return issues


def _detect_structure_anomalies(question: dict) -> list[str]:
    """检测 JSON 结构异常。"""
    issues = []

    # stem 类型错误
    stem = question.get("stem")
    if stem is not None and not isinstance(stem, str):
        issues.append("stem_not_string")

    # options 格式异常
    options = question.get("options")
    if options is not None:
        if isinstance(options, list):
            for opt in options:
                if not isinstance(opt, dict):
                    issues.append("option_item_not_dict")
                    break
                if "key" not in opt or "text" not in opt:
                    issues.append("option_missing_key_or_text")
                    break
        elif not isinstance(options, dict):
            issues.append("options_invalid_type")

    # answer 类型错误
    answer = question.get("answer")
    if answer is not None and not isinstance(answer, str):
        issues.append("answer_not_string")

    # confidence 范围
    confidence = question.get("confidence_score")
    if confidence is not None:
        if not isinstance(confidence, (int, float)):
            issues.append("confidence_not_numeric")
        elif confidence < 0 or confidence > 1:
            issues.append("confidence_out_of_range")

    return issues


def _detect_length_anomaly(
    stem: str, raw_text: str, max_ratio: float = 2.0, min_ratio: float = 0.2,
) -> str | None:
    """检测修复后 stem 长度相对原文的异常膨胀或缩短。"""
    if not raw_text or not stem:
        return None
    raw_len = len(raw_text)
    stem_len = len(stem)
    if raw_len == 0:
        return None
    ratio = stem_len / raw_len
    if ratio > max_ratio:
        return "stem_too_long"
    if ratio < min_ratio:
        return "stem_too_short"
    return None


def validate_ai_result(question: dict) -> dict:
    """对单道 AI 修复后的题目做校验。

    Args:
        question: 修复后的标准题目 dict

    Returns:
        {
            "is_valid": bool,
            "issues": [...],
            "severity": "none" | "warning" | "error",
        }
    """
    issues: list[str] = []

    stem = question.get("stem", "")
    answer = question.get("answer", "")
    analysis = question.get("analysis", "")
    raw_text = question.get("raw_text", "")

    # 1. Duplicate stem
    dup = _detect_duplicate_stem(stem, raw_text)
    if dup:
        issues.append(dup)

    # 2. Field pollution
    pollution = _detect_field_pollution(stem, answer, analysis)
    issues.extend(pollution)

    # 3. Structure anomalies
    struct = _detect_structure_anomalies(question)
    issues.extend(struct)

    # 4. Length anomaly
    length = _detect_length_anomaly(stem, raw_text)
    if length:
        issues.append(length)

    # Determine severity
    error_issues = {
        "stem_not_string", "options_invalid_type", "answer_not_string",
        "confidence_not_numeric", "stem_duplicated",
    }
    has_error = any(i in error_issues for i in issues)

    if has_error:
        severity = "error"
    elif issues:
        severity = "warning"
    else:
        severity = "none"

    return {
        "is_valid": not has_error,
        "issues": issues,
        "severity": severity,
    }


def validate_ai_results(questions: list[dict]) -> dict:
    """批量校验 AI 修复结果。

    Args:
        questions: 修复后的题目列表

    Returns:
        {
            "questions": [...],  # 附加 ai_validation 字段
            "stats": {
                "total": int,
                "valid": int,
                "warnings": int,
                "errors": int,
            },
        }
    """
    result_questions = []
    valid_count = 0
    warning_count = 0
    error_count = 0

    for question in questions:
        validation = validate_ai_result(question)
        new_q = dict(question)
        new_q["ai_validation"] = validation

        if validation["severity"] == "none":
            valid_count += 1
        elif validation["severity"] == "warning":
            warning_count += 1
        else:
            error_count += 1

        result_questions.append(new_q)

    return {
        "questions": result_questions,
        "stats": {
            "total": len(questions),
            "valid": valid_count,
            "warnings": warning_count,
            "errors": error_count,
        },
    }
