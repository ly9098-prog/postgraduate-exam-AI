"""题目标准化器 — 纯规则实现。

将 Stage 3/4 的输出标准化为统一的 Question Schema。
涵盖题干清洗、选项结构化、答案标准化、题型识别。
不做 AI 修复、不做数据库写入、不修改上游输出。
"""

import re
import hashlib
import logging
import time

logger = logging.getLogger(__name__)

QT_SINGLE_CHOICE = "single_choice"
QT_MULTIPLE_CHOICE = "multiple_choice"
QT_TRUE_FALSE = "true_false"
QT_FILL_BLANK = "fill_blank"
QT_MULTI_BLANK_CHOICE = "multi_blank_choice"
QT_SUBJECTIVE = "subjective"
_OPTION_LINE_RE = re.compile(r"^(?:[?？]|[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])?\s*[A-Ha-h][.、:：)）\s]")

# 单选题必须包含的标准选项集合
REQUIRED_OPTION_KEYS = frozenset({"A", "B", "C", "D"})
_OCR_CONTAMINATION_THRESHOLD = 0.30

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
    """清洗题干：去除题号前缀、题型标签、多余空白、LaTeX 标记。"""
    for pat, repl in _CLEAN_RULES:
        text = pat.sub(repl, text)
    text = re.sub(r"\\(?:dots|ldots|dotsquare)", "...", text)
    text = re.sub(r"\\(?:cdots|cdots|cdotsquare)", "···", text)
    return text.strip()


def _break_before_number_markers(text: str) -> str:
    """在题号标记前插入换行：① ② ...、（1）（2）...、1) 2) ..."""
    # ①-⑳ 圈号标记（避免破坏 (①) 等括号内引用）
    text = re.sub(r"(?<![（(\n])([①-⑳])", r"\n\1", text)
    # （1）（2）全角括号数字，前面有非空白字符时换行
    text = re.sub(r"(?<=[^\s])[　 ]*([（][0-9]+[）])", r"\n\1", text)
    # 1) 2) 数字+括号，排除数学表达式(0,1)和全角括号（1）的误匹配
    text = re.sub(r"(?<=[^\s\d,（(])[　 ]*(\d+[)）])(?=\s*[一-鿟\w])", r"\n\1", text)
    return text


def _extract_stem(raw_text: str, option_lines: dict[str, str], blank_option_groups: list[dict] | None = None) -> str:
    """从原始题目文本中提取题干（去除选项行和答案/解析行）。"""
    lines = raw_text.split("\n")
    stem_lines: list[str] = []
    in_options = False
    blank_markers = {str(group.get("id") or group.get("marker") or "").strip() for group in (blank_option_groups or [])}

    for line in lines:
        stripped = line.strip()

        # 答案/解析标记 — 后续行不再属于题干
        for pat in _STRIP_PATTERNS:
            if pat.match(stripped):
                return _clean_stem("\n".join(stem_lines))

        if blank_markers:
            for marker in blank_markers:
                if marker and re.match(rf"^(?:{re.escape(marker)}|[（(]\s*{re.escape(marker)}\s*[）)])(?:\s*$|\s*(?:[?？]\s*)?[A-Ha-h][.、:：)）\s])", stripped):
                    in_options = True
                    break
            if in_options:
                continue

        # 选项行
        if _OPTION_LINE_RE.match(stripped):
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
        text = raw_options[key].strip()
        text = re.sub(r"\\(?:dots|ldots|dotsquare)", "...", text)
        text = re.sub(r"\\(?:cdots|cdots|cdotsquare)", "···", text)
        result.append({"key": key.upper(), "text": text})
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


def check_option_completeness(
    question_type: str, options: list[dict],
) -> tuple[bool, list[str]]:
    """检查选择题选项完整性。

    单选题必须包含 A/B/C/D 全部四个选项。
    多选题至少需要 2 个选项。
    """
    if question_type not in (QT_SINGLE_CHOICE, QT_MULTIPLE_CHOICE):
        return True, []
    if not options:
        return False, ["missing_all_options"]

    present_keys = {o["key"].upper() for o in options if o.get("key")}

    if question_type == QT_SINGLE_CHOICE:
        missing = REQUIRED_OPTION_KEYS - present_keys
        if missing:
            return False, [f"missing_option_{k}" for k in sorted(missing)]
    else:
        if len(present_keys) < 2:
            return False, ["options_too_few_for_multiple_choice"]

    return True, []


_check_option_completeness = check_option_completeness  # 向后兼容


def run_ocr_quality_gate(raw_text: str) -> dict:
    """在解析前运行 OCR 质量门控。

    Returns:
        {"passed": bool, "ocr_quality_flags": [...], "ocr_contamination_score": float}
    """
    if not raw_text or not raw_text.strip():
        return {"passed": True, "ocr_quality_flags": [], "ocr_contamination_score": 0.0}

    from app.features.ocr_quality_gate import detect_ocr_contamination

    contamination = detect_ocr_contamination(raw_text)
    flags = contamination["flags"]
    score = contamination["score"]
    passed = score < _OCR_CONTAMINATION_THRESHOLD

    if not passed:
        logger.warning(
            "OCR quality gate REJECTED: score=%.2f flags=%s raw_preview=%.100s",
            score, flags, raw_text,
        )

    return {
        "passed": passed,
        "ocr_quality_flags": flags,
        "ocr_contamination_score": score,
    }


_run_ocr_quality_gate = run_ocr_quality_gate  # 向后兼容


def _run_consistency_cross_check(raw_text: str, question_type: str, parsed_options: list[dict]) -> dict:
    """校验 raw_text 选项与 parsed_options 的一致性。

    Returns:
        {"consistent": bool, "missing_in_parsed": set, "severity": str}
    """
    if question_type not in (QT_SINGLE_CHOICE, QT_MULTIPLE_CHOICE):
        return {"consistent": True, "missing_in_parsed": set(), "severity": "ok"}
    if not raw_text or not parsed_options:
        return {"consistent": True, "missing_in_parsed": set(), "severity": "ok"}

    from app.features.ocr_quality_gate import cross_check_consistency

    parsed_dict = {o["key"]: o["text"] for o in parsed_options if o.get("key")}
    result = cross_check_consistency(raw_text, parsed_dict)

    if not result["is_consistent"]:
        logger.warning(
            "Consistency cross-check FAILED: raw=%s parsed=%s missing=%s",
            result["raw_options"], result["parsed_options"], result["missing_in_parsed"],
        )

    return {
        "consistent": result["is_consistent"],
        "missing_in_parsed": result["missing_in_parsed"],
        "severity": result["severity"],
    }


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
        标准 Question Schema dict（含 validation_status / failure_reason 字段）
    """
    if matched is None:
        matched = {}
    if source_info is None:
        source_info = {}

    raw_text = raw_question.get("raw_question_text", "")
    option_lines = raw_question.get("option_lines", {})

    # === Goal 5: Cache lookup — 防止同一输入重复解析 ===
    # 使用 raw_text hash 做预缓存键（stem 尚未提取）
    _pre_cache_key = hashlib.sha256(raw_text.encode()).hexdigest() if raw_text else ""
    if _pre_cache_key:
        _cached = parse_cache_get(raw_text, _pre_cache_key)
        if _cached is not None:
            return _cached

    blank_option_groups = _normalize_blank_option_groups(raw_question.get("blank_option_groups"))
    page = raw_question.get("page_start", source_info.get("page", 1))

    # === OCR Quality Gate: 在解析前检测污染 ===
    quality_gate = _run_ocr_quality_gate(raw_text)
    ocr_critical_corruption = (
        not quality_gate["passed"]
        and quality_gate["ocr_contamination_score"] >= 0.50
    )

    stem = _extract_stem(raw_text, option_lines, blank_option_groups)
    options = [] if blank_option_groups else _normalize_options(option_lines)
    answer_raw = matched.get("answer")
    explanation_raw = matched.get("explanation", "")
    section_type = raw_question.get("section_type")
    question_type = QT_MULTI_BLANK_CHOICE if blank_option_groups else _detect_question_type(stem, options, answer_raw, section_type=section_type)
    # 多空选择题除外：在题号标记（①、（1）、1) 等）前插入换行
    if question_type != QT_MULTI_BLANK_CHOICE:
        stem = _break_before_number_markers(stem)
    answer = _normalize_answer(answer_raw, question_type)
    analysis = (explanation_raw or "").strip()
    confidence_score = _compute_confidence(stem, options, answer, question_type)
    stem_hash = _compute_stem_hash(stem)

    # === Consistency cross-check: raw_text vs parsed ===
    consistency = _run_consistency_cross_check(raw_text, question_type, options)

    errors: list[str] = []
    warnings: list[str] = []
    failure_reasons: list[str] = []

    # --- 基础校验 ---
    if not stem:
        errors.append("missing_stem")
        failure_reasons.append("stem_empty")

    # --- 选项完整性强校验 (Goal 1) ---
    if question_type in (QT_SINGLE_CHOICE, QT_MULTIPLE_CHOICE):
        if not options:
            errors.append("missing_options")
            failure_reasons.append("options_empty")
        else:
            opts_complete, opt_errors = _check_option_completeness(question_type, options)
            if not opts_complete:
                for e in opt_errors:
                    errors.append(e)
                failure_reasons.extend(opt_errors)

    if question_type == QT_MULTI_BLANK_CHOICE and not blank_option_groups:
        errors.append("missing_blank_option_groups")
        failure_reasons.append("missing_blank_option_groups")

    if question_type in (QT_SINGLE_CHOICE, QT_MULTIPLE_CHOICE, QT_TRUE_FALSE) and not answer:
        errors.append("missing_answer")
        failure_reasons.append("missing_answer_for_objective_question")

    # --- OCR 污染阻断 (Goal 2) ---
    if not quality_gate["passed"]:
        warnings.append("ocr_contamination_detected")
        for flag in quality_gate["ocr_quality_flags"]:
            warnings.append(f"ocr_quality:{flag}")
        if ocr_critical_corruption:
            errors.append("ocr_critical_corruption")
            failure_reasons.append("ocr_corruption_detected")
            # 污染严重时强制降置信度
            confidence_score = min(confidence_score, 0.30)

    # --- 一致性校验阻断 (Goal 3) ---
    if not consistency["consistent"]:
        severity = consistency["severity"]
        missing_opts = ",".join(sorted(consistency["missing_in_parsed"]))
        if severity == "critical":
            errors.append(f"parse_loss: raw_has_{missing_opts}_parsed_missing")
            failure_reasons.append(f"parse_option_loss: {missing_opts}")
        else:
            warnings.append(f"parse_extra_options: parsed has extra {missing_opts}")

    if confidence_score < 0.5:
        warnings.append("low_confidence")

    # === 防假成功: is_valid 复合判定 (Goal 4) ===
    # is_valid = stem_valid AND options_complete AND no_critical_ocr_corruption
    stem_valid = "missing_stem" not in errors
    options_complete = not any(e.startswith("missing_option_") for e in errors)
    no_critical_corruption = "ocr_critical_corruption" not in errors
    no_parse_loss = not any(e.startswith("parse_loss") for e in errors)

    is_valid = (
        stem_valid
        and options_complete
        and no_critical_corruption
        and no_parse_loss
        and len([e for e in errors if e not in ("missing_answer", "missing_answer_for_objective_question")]) == 0
    )
    # missing_answer 本身不阻断 is_valid（答案可能在后续匹配），但与其他错误组合时阻断

    if not is_valid and not failure_reasons:
        failure_reasons.append("validation_failed")

    # === 失败追踪 (Goal 6) ===
    validation_status = "passed" if is_valid else "failed"
    retry_recommended = (
        not is_valid
        and (
            "missing_option_" in " ".join(errors)
            or "ocr_corruption_detected" in failure_reasons
            or "parse_option_loss" in " ".join(failure_reasons)
        )
    )

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
        "is_valid": is_valid,
        "errors": errors,
        "warnings": warnings,
        "stem_hash": stem_hash,
        "confidence_score": confidence_score,
        # Goal 6: 失败追踪字段
        "validation_status": validation_status,
        "failure_reason": failure_reasons,
        "retry_recommended": retry_recommended,
        # Goal 2: OCR 质量标记
        "ocr_quality_flags": quality_gate["ocr_quality_flags"],
    }
    if blank_option_groups:
        result["blank_option_groups"] = blank_option_groups

    # === Goal 5: 写入缓存 ===
    if _pre_cache_key:
        parse_cache_put(raw_text, _pre_cache_key, result)

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


# ---------------------------------------------------------------------------
# Goal 5: Parse cache — 防止同一输入多次解析产生不同版本
# 版本化失效：修改 PARSER_CACHE_VERSION 即可使所有旧缓存自动失效。
# ---------------------------------------------------------------------------

_MAX_CACHE_SIZE = 500
_MAX_CACHE_AGE = 86400  # 24小时自动过期

# 缓存版本 — 修改此值会使所有旧缓存失效，触发重新解析。
# 更新时机：解析规则、选项校验逻辑、题型识别规则等发生变化时。
PARSER_CACHE_VERSION = "2026.06.18"

_parse_cache: dict[str, dict] = {}


def _make_cache_key(raw_text: str, raw_hash: str) -> str:
    """生成缓存键：raw_hash + raw_text 的联合 hash。"""
    payload = f"{raw_hash}|{raw_text}"
    return hashlib.sha256(payload.encode()).hexdigest()


def parse_cache_get(raw_text: str, raw_hash: str) -> dict | None:
    """查询缓存。

    版本匹配（cache_version == PARSER_CACHE_VERSION）才命中。
    版本不匹配或无 version 字段 → 自动失效，返回 None。
    """
    key = _make_cache_key(raw_text, raw_hash)
    entry = _parse_cache.get(key)
    if entry is None:
        return None
    if entry.get("cache_version") != PARSER_CACHE_VERSION:
        return None
    # 被动 TTL 过期：超 24h 的条目自动失效
    if time.time() - (entry.get("cached_at") or 0) > _MAX_CACHE_AGE:
        return None
    return entry.get("result")  # type: ignore[return-value]


def parse_cache_put(raw_text: str, raw_hash: str, result: dict) -> None:
    """写入缓存（携带版本号）。超过容量时按 FIFO 淘汰最旧条目。"""
    global _parse_cache
    key = _make_cache_key(raw_text, raw_hash)
    if key in _parse_cache:
        return
    if len(_parse_cache) >= _MAX_CACHE_SIZE:
        oldest = next(iter(_parse_cache))
        del _parse_cache[oldest]
    _parse_cache[key] = {
        "result": result,
        "cache_version": PARSER_CACHE_VERSION,
        "cached_at": time.time(),
    }


def parse_cache_clear() -> None:
    """清空缓存（用于测试或强制重新解析）。"""
    global _parse_cache
    _parse_cache.clear()
