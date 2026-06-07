"""题目标准化器 — 纯规则实现。

将 Stage 3/4 的输出标准化为统一的 Question Schema。
涵盖题干清洗、选项结构化、答案标准化、题型识别。
不做 AI 修复、不做数据库写入、不修改上游输出。
"""

import re
import hashlib

QT_SINGLE_CHOICE = "single_choice"
QT_MULTIPLE_CHOICE = "multiple_choice"
QT_TRUE_FALSE = "true_false"
QT_FILL_BLANK = "fill_blank"
QT_MULTI_BLANK_CHOICE = "multi_blank_choice"
QT_SUBJECTIVE = "subjective"

_TYPE_ALIAS_MAP = {
    "单选": QT_SINGLE_CHOICE, "单选题": QT_SINGLE_CHOICE,
    "多选": QT_MULTIPLE_CHOICE, "多选题": QT_MULTIPLE_CHOICE,
    "判断": QT_TRUE_FALSE, "判断题": QT_TRUE_FALSE,
    "填空": QT_FILL_BLANK, "填空题": QT_FILL_BLANK,
    "主观": QT_SUBJECTIVE, "主观题": QT_SUBJECTIVE,
    "简答": QT_SUBJECTIVE, "简答题": QT_SUBJECTIVE,
}

_TRUE_FALSE_VALUES = {"T", "F", "TRUE", "FALSE", "正确", "错误", "√", "×", "对", "错"}

_TRUE_FALSE_MAP = {
    "T": "T", "F": "F", "TRUE": "T", "FALSE": "F",
    "正确": "T", "错误": "F", "√": "T", "×": "F", "对": "T", "错": "F",
}

# 题干中需要剥离的答案/解析标签行
_STRIP_PATTERNS = [
    re.compile(r"^(?:【答案】|答案[：:]|参考答案[：:]|正确答案[：:]|KEY\s*[：:]|Answer\s*[：:]).*$"),
    re.compile(r"^(?:【解析】|解析[：:]|解答[：:]|讲解[：:]|分析[：:]|Explanation\s*[：:]).*$"),
]

# 题干清洗规则（按顺序应用）
_CLEAN_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^\s*\d+[.、)）]\s*"), ""),
    (re.compile(r"^\(\d+\)\s*"), ""),
    (re.compile(r"^【\d+】\s*"), ""),
    (re.compile(r"^第\s*\d+\s*题[.、:：]?\s*"), ""),
    (re.compile(r"^\s*\((?:单选题|多选题|判断题|填空题|简答题|主观题)\)\s*"), ""),
    (re.compile(r"[　\t]+"), " "),
    (re.compile(r" {2,}"), " "),
    (re.compile(r"\n{3,}"), "\n\n"),
    (re.compile(r"（\s*）"), "()"),
]


def _clean_stem(text: str) -> str:
    """清洗题干：去除题号前缀、题型标签、多余空白。"""
    for pat, repl in _CLEAN_RULES:
        text = pat.sub(repl, text)
    return text.strip()


def _extract_stem(raw_text: str, option_lines: dict[str, str]) -> str:
    """从原始题目文本中提取题干（去除选项行和答案/解析行）。"""
    lines = raw_text.split("\n")
    stem_lines: list[str] = []
    in_options = False

    for line in lines:
        stripped = line.strip()

        # 答案/解析标记 — 后续行不再属于题干
        for pat in _STRIP_PATTERNS:
            if pat.match(stripped):
                return _clean_stem("\n".join(stem_lines))

        # 选项行
        if option_lines and re.match(r"^(?:[?？]|[①②③④⑤⑥⑦⑧])?\s*[A-Ha-h][.、:：)）\s]", stripped):
            in_options = True
            continue

        if not in_options:
            stem_lines.append(line)

    return _clean_stem("\n".join(stem_lines))


def _normalize_options(raw_options: dict[str, str]) -> list[dict]:
    """标准化选项为 [{"key": "A", "text": "..."}] 格式。"""
    if not raw_options:
        return []
    result: list[dict] = []
    for key in sorted(raw_options.keys()):
        result.append({"key": key.upper(), "text": raw_options[key].strip()})
    return result


def _normalize_blank_option_groups(groups: list[dict] | None) -> list[dict]:
    if not groups:
        return []
    normalized: list[dict] = []
    for group in groups:
        marker = str(group.get("id") or group.get("marker") or "").strip()
        options = _normalize_options(group.get("options") or {})
        if marker and options:
            normalized.append({"id": marker, "options": options})
    return normalized


def _normalize_answer(answer: str | None, question_type: str) -> str:
    """标准化答案格式。"""
    if answer is None:
        return ""

    answer = answer.strip()

    if question_type == QT_TRUE_FALSE:
        return _TRUE_FALSE_MAP.get(answer, _TRUE_FALSE_MAP.get(answer.upper(), answer))

    if question_type == QT_MULTIPLE_CHOICE:
        cleaned = answer.upper().replace(" ", "").replace("，", ",")
        if "," not in cleaned and len(cleaned) > 1 and all(c in "ABCDEFGH" for c in cleaned):
            cleaned = ",".join(cleaned)
        return cleaned

    if question_type == QT_SINGLE_CHOICE:
        return answer.upper()

    return answer


_SECTION_TYPE_MAP = {
    "question_type_single": QT_SINGLE_CHOICE,
    "question_type_multiple": QT_MULTIPLE_CHOICE,
    "question_type_truefalse": QT_TRUE_FALSE,
    "question_type_subjective": QT_SUBJECTIVE,
}


def _detect_question_type(
    stem: str,
    options: list[dict] | None,
    answer: str | None,
    section_type: str | None = None,
) -> str:
    """自动识别题型（规则优先）。"""
    if options is None:
        options = []

    ans_clean = (answer or "").strip()

    # Section marker 提供强信号（仅在结构不矛盾时生效）
    if section_type:
        mapped = _SECTION_TYPE_MAP.get(section_type)
        if mapped:
            if mapped in (QT_SINGLE_CHOICE, QT_MULTIPLE_CHOICE) and options:
                return mapped
            if mapped == QT_TRUE_FALSE and len(options) <= 2:
                return mapped
            if mapped == QT_SUBJECTIVE and not options:
                return mapped

    # 判断题：无或仅 2 个选项 + 答案为判断格式
    if ans_clean.upper() in _TRUE_FALSE_VALUES or ans_clean in _TRUE_FALSE_VALUES:
        if not options or len(options) <= 2:
            return QT_TRUE_FALSE

    # 填空题：题干含填空标记
    if "填空" in stem or "___" in stem or "____" in stem:
        return QT_FILL_BLANK
    if re.search(r"（\s*）", stem) and not options:
        return QT_FILL_BLANK

    # 选择题
    if options and len(options) >= 2:
        if ans_clean:
            c = ans_clean.upper().replace(" ", "").replace("，", ",")
            if "," in c or (len(c) >= 2 and all(ch in "ABCDEFGH" for ch in c)):
                return QT_MULTIPLE_CHOICE
        return QT_SINGLE_CHOICE

    return QT_SUBJECTIVE


def _compute_stem_hash(stem: str) -> str:
    """计算题干去重 hash（去空白 + SHA256 前 8 位）。"""
    normalized = re.sub(r"\s+", "", stem).lower()
    return hashlib.sha256(normalized.encode()).hexdigest()[:8]


def _compute_confidence(
    stem: str,
    options: list[dict],
    answer: str,
    question_type: str,
) -> float:
    """计算结构化置信度（0.0 ~ 1.0）。

    权重：题干 0.3 + 选项 0.25 + 答案 0.25 + 一致性 0.2
    """
    score = 0.0

    # 题干完整性 (0.3)
    if stem and len(stem) >= 3:
        score += 0.3
    elif stem:
        score += 0.1

    # 选项完整性 (0.25)
    if question_type in (QT_SINGLE_CHOICE, QT_MULTIPLE_CHOICE, QT_TRUE_FALSE):
        if options and len(options) >= 2:
            score += 0.25
        elif options:
            score += 0.1
    else:
        score += 0.25

    # 答案有效性 (0.25)
    if answer and len(answer) >= 1:
        score += 0.25

    # 选项-答案一致性 (0.2)
    if question_type == QT_SINGLE_CHOICE and options and answer:
        valid_keys = {o["key"] for o in options}
        if answer.upper() in valid_keys:
            score += 0.2
    elif question_type == QT_MULTIPLE_CHOICE and options and answer:
        valid_keys = {o["key"] for o in options}
        parts = [p for p in answer.upper().replace(" ", "").replace("，", ",").split(",") if p]
        if parts and all(p in valid_keys for p in parts):
            score += 0.2
    elif question_type == QT_TRUE_FALSE:
        if answer.upper() in ("T", "F"):
            score += 0.2
    else:
        score += 0.15  # 填空/主观题宽松通过

    return round(min(1.0, score), 2)


def normalize_question(
    raw_question: dict,
    matched: dict | None = None,
    source_info: dict | None = None,
) -> dict:
    """标准化单道题目。

    Args:
        raw_question: stage3 输出的单道题目
        matched: stage4 输出的单道匹配结果
        source_info: 来源信息 {"file", "type", "page", "subject"}

    Returns:
        标准 Question Schema dict
    """
    if matched is None:
        matched = {}
    if source_info is None:
        source_info = {}

    raw_text = raw_question.get("raw_question_text", "")
    option_lines = raw_question.get("option_lines", {})
    blank_option_groups = _normalize_blank_option_groups(raw_question.get("blank_option_groups"))
    page = raw_question.get("page_start", source_info.get("page", 1))

    stem = _extract_stem(raw_text, option_lines)
    options = [] if blank_option_groups else _normalize_options(option_lines)
    answer_raw = matched.get("answer")
    explanation_raw = matched.get("explanation", "")
    section_type = raw_question.get("section_type")
    question_type = QT_MULTI_BLANK_CHOICE if blank_option_groups else _detect_question_type(stem, options, answer_raw, section_type=section_type)
    answer = _normalize_answer(answer_raw, question_type)
    analysis = (explanation_raw or "").strip()
    confidence_score = _compute_confidence(stem, options, answer, question_type)
    stem_hash = _compute_stem_hash(stem)

    errors: list[str] = []
    warnings: list[str] = []

    if not stem:
        errors.append("missing_stem")
    if question_type in (QT_SINGLE_CHOICE, QT_MULTIPLE_CHOICE) and not options:
        errors.append("missing_options")
    if question_type == QT_MULTI_BLANK_CHOICE and not blank_option_groups:
        errors.append("missing_blank_option_groups")
    if question_type in (QT_SINGLE_CHOICE, QT_MULTIPLE_CHOICE, QT_TRUE_FALSE) and not answer:
        errors.append("missing_answer")
    if confidence_score < 0.5:
        warnings.append("low_confidence")

    result = {
        "schema_version": "v1",
        "subject": source_info.get("subject", ""),
        "question_type": question_type,
        "stem": stem,
        "options": options,
        "answer": answer,
        "analysis": analysis,
        "raw_text": raw_text,
        "knowledge_points": [],
        "difficulty": 3,
        "source": {
            "file": source_info.get("file", ""),
            "page": page,
            "type": source_info.get("type", "pdf"),
        },
        "is_valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "stem_hash": stem_hash,
        "confidence_score": confidence_score,
    }
    if blank_option_groups:
        result["blank_option_groups"] = blank_option_groups
    return result


def normalize_questions(
    raw_questions: list[dict],
    matched_pairs: list[dict],
    source_info: dict | None = None,
) -> dict:
    """批量标准化题目。

    Args:
        raw_questions: stage3 输出的全部题目
        matched_pairs: stage4 输出的匹配结果 (result["matched"])
        source_info: 来源信息

    Returns:
        {"questions": [...], "errors": [...], "warnings": [...]}
    """
    if source_info is None:
        source_info = {}

    matched_by_num: dict[int, dict] = {}
    for m in matched_pairs:
        matched_by_num[m["question_number"]] = m

    questions: list[dict] = []
    errors: list[dict] = []
    warnings: list[dict] = []

    for raw_q in raw_questions:
        qnum = raw_q.get("number", 0)
        matched = matched_by_num.get(qnum)

        try:
            result = normalize_question(raw_q, matched, source_info)
            # P1-2: 透传 splitter / 上游写入的 risk_flags，让下游 stage
            # （ai_repair / submit_to_review）和前端审核页能看到完整风险信号。
            # 值域见 prompts/tasks/ocr_book_pdf_non_question_filter_plan.md §11.3。
            upstream_flags = raw_q.get("risk_flags") or []
            if upstream_flags:
                result["risk_flags"] = list(dict.fromkeys(upstream_flags))
            questions.append(result)

            if result["errors"]:
                errors.append({"question_number": qnum, "errors": result["errors"]})
            if result["warnings"]:
                warnings.append({"question_number": qnum, "warnings": result["warnings"]})
        except Exception as e:
            errors.append({
                "question_number": qnum,
                "errors": [f"normalization_failed: {e}"],
            })

    return {"questions": questions, "errors": errors, "warnings": warnings}


def dedup_batch(questions: list[dict]) -> dict:
    """批内去重：基于 stem_hash 标记重复题目。

    不删除重复项，仅标记 is_batch_duplicate=True 和 duplicate_of_index。
    用于在 AI repair 前跳过重复题，节省 token。
    """
    seen: dict[str, int] = {}
    for i, q in enumerate(questions):
        h = q.get("stem_hash", "")
        if not h:
            continue
        if h in seen:
            q["is_batch_duplicate"] = True
            q["duplicate_of_index"] = seen[h]
        else:
            seen[h] = i

    duplicate_indices = [i for i, q in enumerate(questions) if q.get("is_batch_duplicate")]
    return {
        "questions": questions,
        "unique_count": len(questions) - len(duplicate_indices),
        "duplicate_count": len(duplicate_indices),
        "duplicate_indices": duplicate_indices,
    }
