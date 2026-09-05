"""题目标准化器 — 纯规则实现。

将 Stage 3/4 的输出标准化为统一的 Question Schema。
涵盖题干清洗、选项结构化、答案标准化、题型识别。
不做 AI 修复、不做数据库写入、不修改上游输出。
"""

import copy
import hashlib
import logging
import re
import time
from dataclasses import dataclass

from app.features.question_type_classifier import (
    QT_SINGLE_CHOICE,
    extract_options_from_text,
)
from app.features.question_type_classifier import (
    classify as _classify_type,
)
from app.features.question_type_classifier import (
    detect_options_from_text as _detect_options_from_text,
)
from app.services.pdf_text_normalizer import deduplicate_repeated_text
from app.utils.trace.stage_tracer import StageTracer

logger = logging.getLogger(__name__)

from app.features.question_type import (
    QT_FILL_BLANK,
    QT_MULTI_BLANK_CHOICE,
    QT_MULTIPLE_CHOICE,
    QT_SUBJECTIVE,
    QT_TRUE_FALSE,
)

_OPTION_LINE_RE = re.compile(r"^(?:[?？]|[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])?\s*[A-Ha-h][.、:：)）\s]")
# 增强选项检测模式：A. A) ①. (A) 等，用于从 raw_text 中二次检测选项
_OPTION_PATTERN = re.compile(r"^\s*([A-D]|[①②③④]|\(\s*[A-D]\s*\))\s*[.、\)]")
_STRUCTURAL_CODE_FENCE = re.compile(r"```")


def _has_structural_markers(text: str) -> bool:
    """检查文本是否包含结构化标记（选项行或代码围栏）。

    用于 quality gate 决策：当文本含结构化标记时，即使 contamination
    分数较高，也应保留 options / code_blocks，而非清空结构字段。
    """
    if not text:
        return False
    # 选项标记：每行以 A. B) ①. 等开头
    for line in text.split("\n"):
        stripped = line.strip()
        if _OPTION_PATTERN.match(stripped):
            return True
    # 代码围栏
    if _STRUCTURAL_CODE_FENCE.search(text):
        return True
    return False


# 单选题必须包含的标准选项集合
REQUIRED_OPTION_KEYS = frozenset({"A", "B", "C", "D"})
_OCR_CONTAMINATION_THRESHOLD = 0.30

_OPTION_LETTERS = frozenset({"A", "B", "C", "D"})

_TRUE_FALSE_MAP = {
    "T": "T", "F": "F", "TRUE": "T", "FALSE": "F",
    "正确": "T", "错误": "F", "√": "T", "×": "F", "对": "T", "错": "F",
}
_TRUE_FALSE_VALUES = frozenset(_TRUE_FALSE_MAP.keys())

# 题干中需要剥离的答案/解析标签行
_STRIP_PATTERNS = [
    re.compile(r"^(?:【答案】|答案[：:]|参考答案[：:]|正确答案[：:]|KEY\s*[：:]|Answer\s*[：:]).*$"),
    re.compile(r"^(?:【解析】|解析[：:]|解答[：:]|讲解[：:]|分析[：:]|Explanation\s*[：:]).*$"),
]

# 题干清洗规则（按顺序应用）
# 注意：^ 锚定规则只匹配全文开头，对代码块安全。
# 而非 ^ 锚定的空格/换行规则会破坏 fenced code block 内部格式，
# 在 _clean_stem 中通过 _apply_outside_code_blocks 跳过 fence 内部。
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

# ^ 锚定规则（只匹配全文开头，对代码块安全，可直接应用到全文）
_LEADING_RULES: list[tuple[re.Pattern, str]] = _CLEAN_RULES[:5]

# 可能破坏 fenced code block 内部格式的规则（须跳过 fence 内部文本）
_OUTSIDE_FENCE_RULES: list[tuple[re.Pattern, str]] = _CLEAN_RULES[5:]


def _apply_outside_code_blocks(text: str, transform_fn) -> str:
    """将 transform_fn 应用到 fenced code block 外部的文本，块内原样保留。

    支持 ``` fence，未闭合 fence 之后的内容也视为 protected。
    注：~~~ fence 当前不处理（代码库中仅使用 ``` 围栏）。
    """
    parts = re.split(r"(```[\s\S]*?```|```[\s\S]*?$)", text)
    for i, part in enumerate(parts):
        if not part.startswith("```"):
            parts[i] = transform_fn(part)
    return "".join(parts)


def _clean_stem(text: str) -> str:
    """清洗题干：去除题号前缀、题型标签、多余空白、LaTeX 标记、重复内容。

    跳过 fenced code block（```...```）内部内容，保护代码缩进和排版。
    """
    # ^ 锚定规则：只匹配全文开头，对代码块安全，直接应用到全文
    for pat, repl in _LEADING_RULES:
        text = pat.sub(repl, text)

    # 空格/换行压缩规则 + LaTeX 替换 + 题干去重：仅应用到 fence 外部，
    # 保护代码缩进和排版。dedup 会折叠相邻空白行，须跳过 fence 内部。
    def _outside_only(t: str) -> str:
        for pat, repl in _OUTSIDE_FENCE_RULES:
            t = pat.sub(repl, t)
        t = re.sub(r"\\(?:dots|ldots|dotsquare)", "...", t)
        t = re.sub(r"\\(?:cdots|cdots|cdotsquare)", "···", t)
        # deduplicate_repeated_text 内部会 strip()
        # 导致 fence 边界处的换行丢失，需恢复
        ends_with_nl = t.endswith("\n")
        t = deduplicate_repeated_text(t)
        if ends_with_nl and not t.endswith("\n"):
            t += "\n"
        return t

    text = _apply_outside_code_blocks(text, _outside_only)
    text = text.strip()
    return text


def _break_before_number_markers(text: str) -> str:
    """在题号标记前插入换行：① ② ...、（1）（2）...、1) 2) ...

    跳过 fenced code block（```...```）内部内容，防止将代码中的
    `1)`、`（1）` 等数字标记误识别为题号并插入换行。
    """
    lines = text.split("\n")
    result: list[str] = []
    in_fence = False
    for line in lines:
        if line.strip().startswith("```"):
            result.append(line)
            in_fence = not in_fence
            continue
        if in_fence:
            result.append(line)
            continue
        # ①-⑳ 圈号标记（避免破坏 (①) 等括号内引用）
        line = re.sub(r"(?<![（(\n])([①-⑳])", r"\n\1", line)
        # （1）（2）全角括号数字：仅在前一个字符不是 ASCII 标识符时换行。
        # 例如图论/离散数学中 x（2）、v（3）属于变量/顶点标识，不能当作子项序号。
        line = re.sub(r"(?<=[^\sA-Za-z0-9_])[　 ]*([（][0-9]+[）])", r"\n\1", line)
        # 1) 2) 数字+括号：同样禁止从 ASCII 标识符内部切开。
        # 旧规则会把 "(v1,v2)10" 误处理成 "(v1,v\n2)10"，导致刷题页异常换行。
        line = re.sub(r"(?<=[^\s\dA-Za-z_,（(])[　 ]*(\d+[)）])(?=\s*[一-鿟\w])", r"\n\1", line)
        result.append(line)
    return "\n".join(result)


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

        # 选项行：仅在 upstream 确实提取到选项时才剥离
        if option_lines and _OPTION_LINE_RE.match(stripped):
            in_options = True
            continue

        if not in_options:
            stem_lines.append(line)

    stem_text = "\n".join(stem_lines)

    # P1-2: Strip inline options from stem when option_lines are embedded in
    # the same line as stem text (e.g. "则A. 可能是2 B. 不可能是1").
    # This handles the case where OCR outputs stem+options on one line and
    # the line-by-line _OPTION_LINE_RE matching above can't separate them.
    if option_lines and len(option_lines) >= 2:
        # Remove inline option text from stem. Handles cases where options
        # are on the same line as stem text (e.g. "则A.可能是2 B.不可能是1").
        _option_keys = sorted(option_lines.keys(), key=len, reverse=True)
        for _k in _option_keys:
            _val = option_lines.get(_k, "")
            if not _val:
                continue
            # Build regex for e.g. "A. 可能是2" with optional separator variations
            _opt_pat = re.compile(
                re.escape(_k) + r"\s*[.．、:：)）]\s*" + re.escape(_val) + r"\s*"
            )
            stem_text = _opt_pat.sub("", stem_text)
        stem_text = stem_text.strip()

    return _clean_stem(stem_text)


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


def filter_isolated_tokens(text: str, context: dict | None = None) -> str:
    """Remove standalone OCR noise tokens {A, B, C, D} outside option context.

    Rules:
    - Token must be exactly one of {A, B, C, D}
    - NOT in an option block (not preceded by a number marker or question signal)
    - NOT adjacent to Chinese/graphic punctuation context

    Args:
        text: The stem text to clean.
        context: Optional dict with 'has_options' or 'option_lines' signal.

    Returns:
        Cleaned text with isolated tokens removed.
    """
    if not text:
        return text

    # If text has actual option context, skip aggressive filtering
    if context:
        if context.get("has_options") or context.get("option_lines"):
            return text

    # Remove standalone A/B/C/D tokens at end of lines (isolated noise)
    lines = text.split("\n")
    cleaned: list[str] = []
    for line in lines:
        stripped = line.strip()
        # Skip lines that are just a single A/B/C/D
        if len(stripped) == 1 and stripped in {"A", "B", "C", "D"}:
            continue
        cleaned.append(line)
    text = "\n".join(cleaned)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


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


@dataclass
class OptionValidationResult:
    """Result of option set validation."""
    is_complete: bool
    is_usable: bool
    count: int
    missing_keys: list[str]
    suspicious_reasons: list[str]


def validate_option_set(options: dict[str, str]) -> OptionValidationResult:
    """Validate a parsed option set for suspicious patterns.

    Detects cases like single A option containing B/C/D labels (split failure),
    or options with embedded labels in their text.

    Returns:
        OptionValidationResult with is_usable=False if options are unreliable.
    """
    if not options:
        return OptionValidationResult(
            is_complete=False, is_usable=False, count=0,
            missing_keys=[], suspicious_reasons=["empty_options"],
        )

    count = len(options)
    missing = [k for k in ("A", "B", "C", "D") if k not in options]
    suspicious: list[str] = []

    # Single A option containing other option labels → split failure
    if count == 1 and "A" in options:
        text = options["A"]
        if re.search(r"(?<![A-Za-z0-9_])[BCD]\s*[\.\．、:：]", text):
            suspicious.append("inline_option_split_failed")

    # Suspiciously long text with embedded option labels
    for key, text in options.items():
        if len(text) > 100 and re.search(r"[A-D]\s*[\.\．、:：]", text):
            suspicious.append(f"option_{key}_may_contain_multiple_labels")
            break  # one suspicious option is enough to flag the set

    return OptionValidationResult(
        is_complete=count >= 4,
        is_usable=count >= 2 and len(suspicious) == 0,
        count=count,
        missing_keys=missing,
        suspicious_reasons=suspicious,
    )


def has_objective_question_signals(
    raw_text: str,
    stem: str,
    answer: str | None = None,
) -> tuple[bool, list[str]]:
    """Detect objective question signals in raw text.

    Used to prevent false downgrade to subjective when objective
    signals are present but options failed to parse.

    Returns:
        (has_signals, signal_list) describing the specific signals found.
    """
    signals: list[str] = []
    text = raw_text or stem or ""

    # Option label patterns (A./B./C./D.)
    option_labels = re.findall(r"^\s*[A-Da-d]\s*[.．、:：)）]", text, re.MULTILINE)
    if len(option_labels) >= 2:
        signals.append(f"option_labels:{len(option_labels)}")

    # Explicit answer markers
    if re.search(r"(?:参考|正确)?答案\s*[：:]|【答案】", text):
        signals.append("explicit_answer_marker")

    # Answer is a choice letter(s)
    if answer and re.match(r"^[A-D](?:[,\s]*[A-D])*$", answer.strip().upper()):
        signals.append("explicit_choice_answer")

    # Choice-related keywords
    kw_matches = re.findall(r"下列|选项|单选|多选|选择|哪些|正确的是|错误的是|下列说法", text)
    if kw_matches:
        signals.append(f"choice_keywords:{len(kw_matches)}")

    return bool(signals), signals


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

    qnum = raw_question.get("number", "?")
    logger.info(
        "[TRACE] stage=raw_input qnum=%s raw_text_len=%d has_option_lines=%s "
        "has_blank_groups=%s upstream_has_options=%s raw_text_preview=%.120s",
        qnum, len(raw_text), bool(option_lines),
        bool(raw_question.get("blank_option_groups")),
        raw_question.get("has_options", False),
        raw_text.replace("\n", "\\n")[:120],
    )

    # === Structure freeze: detect frozen questions ===
    is_frozen = bool(raw_question.get("is_frozen", False))
    if is_frozen:
        logger.info("[FREEZE] normalize_question(q%s): frozen options=%s",
                     qnum, sorted(option_lines.keys()) if option_lines else "none")

    # NOTE: Layer 0 — Input Clean only. Option order is preserved as-is from
    # the upstream (freeze stage or splitter). No reordering, no padding,
    # no structural changes to options. normalize_option_order is NOT called
    # here — it would violate the read-only constraint.
    # Frozen options preserve their detected order; non-frozen options keep
    # the insertion order from the splitter.

    # === Goal 5: Cache lookup — 防止同一输入重复解析 ===
    # 缓存键涵盖所有影响输出的输入字段，防止不同 option_lines 命中相同缓存。
    _cache_inputs = {
        "raw_text": raw_text,
        "option_lines": str(sorted((option_lines or {}).items())),
        "is_frozen": raw_question.get("is_frozen", False),
        "blank_option_groups": str(raw_question.get("blank_option_groups", [])),
        "matched": str(matched or {}),
        "source_info": str(source_info or {}),
        "has_options": raw_question.get("has_options", False),
    }
    _cache_key_raw = "|".join(f"{k}={v}" for k, v in _cache_inputs.items())
    _pre_cache_key = hashlib.sha256(_cache_key_raw.encode()).hexdigest() if raw_text else ""
    if _pre_cache_key:
        _cached = parse_cache_get(_cache_key_raw, _pre_cache_key)
        if _cached is not None:
            # 缓存命中时也必须从 raw_question 重新附加定位/bbox 字段
            _bbox_fields = {
                "page_start": raw_question.get("page_start"),
                "page_end": raw_question.get("page_end"),
                "source_question_no": raw_question.get("source_question_no"),
                "source_question_label": raw_question.get("source_question_label"),
                "question_bbox": raw_question.get("question_bbox"),
                "question_bbox_coordinate_space": raw_question.get("question_bbox_coordinate_space"),
                "question_bbox_page_width": raw_question.get("question_bbox_page_width"),
                "question_bbox_page_height": raw_question.get("question_bbox_page_height"),
                "question_bbox_confidence": raw_question.get("question_bbox_confidence"),
                "question_bbox_strategy": raw_question.get("question_bbox_strategy"),
                "question_bbox_diagnostics": raw_question.get("question_bbox_diagnostics"),
            }
            for _k, _v in _bbox_fields.items():
                if _v is not None:
                    _cached_v = _cached.get(_k)
                    if _cached_v is not None and _cached_v != _v:
                        logger.debug(
                            "normalize cache: bbox field %s differs (cached=%s raw=%s), overwriting",
                            _k, _cached_v, _v,
                        )
                    _cached[_k] = _v
            return _cached

    blank_option_groups = _normalize_blank_option_groups(raw_question.get("blank_option_groups"))
    page = raw_question.get("page_start", source_info.get("page", 1))

    # === Execution Trace: initialize per-question tracer ===
    tracer = StageTracer(raw_text)

    # === OCR Quality Gate: 在解析前检测污染 ===
    quality_gate = tracer.run("ocr_quality_gate", "rule", "raw_ocr", None, _run_ocr_quality_gate, raw_text)
    has_structural_markers = _has_structural_markers(raw_text)
    logger.info(
        "[OPTIONS-DETECT] quality_gate_passed=%s score=%.2f has_structural_markers=%s",
        quality_gate["passed"], quality_gate["ocr_contamination_score"], has_structural_markers,
    )
    # 结构完整性优先：当文本含选项/代码围栏时，即使检测到污染也降低阻断等级
    ocr_critical_corruption = (
        not quality_gate["passed"]
        and quality_gate["ocr_contamination_score"] >= 0.50
        and not has_structural_markers  # 有结构标记时不视为致命污染
    )

    # Pre-classifier text detection probe
    _text_detect_before = _detect_options_from_text(raw_text)
    logger.info(
        "[TRACE] stage=text_detection qnum=%s detect_result=%s "
        "quality_gate_passed=%s quality_score=%.2f has_structural_markers=%s",
        qnum, _text_detect_before,
        quality_gate["passed"], quality_gate["ocr_contamination_score"],
        has_structural_markers,
    )

    stem = _extract_stem(raw_text, option_lines, blank_option_groups)
    tracer.add_note("stem_extraction", f"stem length={len(stem)}", "raw_ocr", "ocr_quality_gate")
    # Scan stem for corruption patterns
    for c in tracer.scan_text_corruptions(stem, "stem"):
        tracer.mark_corruption("stem_extraction", c["type"], c["detail"])

    # === Filter isolated single-letter noise tokens from stem ===
    stem = tracer.run("noise_filtering", "rule", "stem", "stem_extraction",
                      lambda s: filter_isolated_tokens(s, {"has_options": raw_question.get("has_options"), "option_lines": option_lines}),
                      stem)

    # ──────────────────────────────────────────────────────────────────────────
    # Layer 1: Question Type Classification — strict has_options gatekeeper
    # ──────────────────────────────────────────────────────────────────────────
    # This is the SINGLE authoritative decision point. If has_options is False,
    # no downstream stage may create or modify options.

    classification = _classify_type(
        raw_text, option_lines,
        splitter_has_options=raw_question.get("has_options", False),
        is_frozen=is_frozen,
    )
    _has_options_classified = classification["has_options"]
    _classify_reason = classification["has_options_reason"]
    _classify_question_type = classification.get("question_type")
    logger.info(
        "[TRACE] stage=classifier_result qnum=%s has_options=%s reason=%s "
        "detect_before=%s type_override=%s confidence=%.1f",
        qnum, _has_options_classified, _classify_reason,
        _text_detect_before,
        _classify_question_type or "none",
        classification.get("confidence", 0),
    )

    # ──────────────────────────────────────────────────────────────────────────
    # Layer 3: Option Engine — only runs when has_options=True
    # ──────────────────────────────────────────────────────────────────────────
    # Standardizes options_raw into [{key: "A", text: "..."}].
    # No AI generation, no padding, no guessing. Options order from upstream
    # (freeze stage or splitter) is preserved as-is.
    _options_branch = (
        "blank_groups" if blank_option_groups and _has_options_classified else
        "option_lines" if option_lines and _has_options_classified else
        "fallback_extract" if _has_options_classified else
        "no_options_classified"
    )
    logger.info(
        "[TRACE] stage=options_branch qnum=%s branch=%s "
        "has_options_classified=%s blank_groups=%s option_lines=%s",
        qnum, _options_branch, _has_options_classified,
        bool(blank_option_groups), bool(option_lines),
    )
    if _has_options_classified:
        if blank_option_groups:
            # Grouped options (multi_blank_choice) are stored in blank_option_groups,
            # not top-level options. Skip fallback extraction to avoid re-extracting
            # ABCD patterns from grouped option lines.
            options = []
        elif option_lines:
            options = tracer.run("options_extraction", "rule", "raw_ocr", "stem_extraction",
                                 _normalize_options, option_lines)
        else:
            # STEP 4 FALLBACK: classifier says has_options=True but option_lines is empty.
            # Try to extract options directly from raw_text as last resort.
            fallback_opts = extract_options_from_text(raw_text)
            if fallback_opts:
                logger.info(
                    "[OPTIONS-FALLBACK] q%s: extracted %d options from raw_text "
                    "(option_lines was empty, classifier said has_options=True)",
                    raw_question.get("number", "?"), len(fallback_opts),
                )
                options = _normalize_options(fallback_opts)
                tracer.mark_options_recovery("options_extraction", "fallback_from_raw_text", len(options), 0.8)
            else:
                options = []
    else:
        options = []
    logger.info(
        "[TRACE] stage=final_options qnum=%s options_count=%d options_keys=%s "
        "branch=%s question_type=%s fallback_used=%s",
        qnum, len(options), [o["key"] for o in options] if options else "none",
        _options_branch,
        blank_option_groups and "multi_blank_choice" or "pending",
        bool(option_lines) is False and bool(options) is True,
    )
    # Track options source for observability
    # Layer 1/3: options come from the classifier gate (has_options) and
    # the option engine (normalization). No re-detection/recovery is performed.
    if blank_option_groups:
        tracer.mark_options_recovery("options_extraction", "blank_groups", len(options), 1.0)
    elif _has_options_classified and options:
        tracer.mark_options_recovery("options_extraction", "classifier_gate", len(options), 1.0)

    # ── Stem re-strip guard ────────────────────────────────────────────
    # When the splitter didn't extract option_lines (e.g. VL_REBUILD path)
    # but normalize_schema independently detected options, go back and
    # strip the option text from the stem. Without this, options like
    # "A.找到头结点" remain embedded in the stem text.
    if not option_lines and options and len(options) >= 2:
        fake_option_lines = {o["key"]: o["text"] for o in options}
        clean_stem = _extract_stem(raw_text, fake_option_lines, blank_option_groups)
        if clean_stem and len(clean_stem) < len(stem):
            logger.info(
                "[OPTIONS-STRIP] q%s: re-stripped stem (option_lines was empty, "
                "fallback found %d options), removed %d chars",
                qnum, len(options), len(stem) - len(clean_stem),
            )
            stem = clean_stem

    answer_raw = matched.get("answer")
    explanation_raw = matched.get("explanation", "")
    section_type = raw_question.get("section_type")
    question_type = QT_MULTI_BLANK_CHOICE if blank_option_groups else _detect_question_type(stem, options, answer_raw, section_type=section_type)
    # Layer 1 classifier override: when detect_options_from_text finds options,
    # force question_type to single_choice (even if _detect_question_type returned subjective)
    if _classify_question_type and question_type == QT_SUBJECTIVE:
        question_type = _classify_question_type
        logger.info(
            "[CLASSIFY] q%s: question_type override: subjective→%s (detect_options_from_text=True)",
            raw_question.get("number", "?"), _classify_question_type,
        )
    # P0: Objective signals guard — prevent false downgrade to subjective
    # when raw text contains option labels, explicit answers, or choice keywords.
    _has_obj_signals, _obj_signal_list = has_objective_question_signals(
        raw_text or "", stem or "", answer_raw,
    )
    if _has_obj_signals and question_type == QT_SUBJECTIVE:
        question_type = QT_SINGLE_CHOICE
        logger.info(
            "[OBJECTIVE-SIGNALS] q%s: subjective→single_choice override "
            "(signals=%s)",
            raw_question.get("number", "?"), _obj_signal_list,
        )
    tracer.add_note("question_type_detection", f"type={question_type}", "intermediate", "options_extraction")
    # 多空选择题除外：在题号标记（①、（1）、1) 等）前插入换行
    if question_type != QT_MULTI_BLANK_CHOICE:
        stem = _break_before_number_markers(stem)
    answer = _normalize_answer(answer_raw, question_type)
    analysis = (explanation_raw or "").strip()
    confidence_score = _compute_confidence(stem, options, answer, question_type)
    stem_hash = _compute_stem_hash(stem)

    # === Consistency cross-check: raw_text vs parsed ===
    consistency = _run_consistency_cross_check(raw_text, question_type, options)
    tracer.add_note("consistency_check", f"consistent={consistency.get('consistent')}", "intermediate", "question_type_detection")

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

    # P0: Option set validation — detect suspicious patterns (e.g. single A
    # containing BCD labels) even when option completeness passes.
    _opt_validation = validate_option_set(option_lines)
    if _opt_validation.suspicious_reasons:
        for reason in _opt_validation.suspicious_reasons:
            warnings.append(f"suspicious_options:{reason}")
            failure_reasons.append(reason)

    # P0: Objective signals risk — when objective signals exist but options
    # are incomplete, propagate the risk flag so it shows in quality_blockers.
    if _has_obj_signals and question_type in (QT_SINGLE_CHOICE, QT_MULTIPLE_CHOICE):
        if not options or len(options) < 2:
            warnings.append("objective_signals_but_options_incomplete")
            failure_reasons.append("objective_signals_but_options_incomplete")

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
        logger.info(
            "[OPTIONS-DETECT] rejected_by_gate=%s has_structural_markers=%s",
            quality_gate["passed"], has_structural_markers,
        )
        if ocr_critical_corruption:
            errors.append("ocr_critical_corruption")
            failure_reasons.append("ocr_corruption_detected")
            # 污染严重且无结构标记时强制降置信度
            confidence_score = min(confidence_score, 0.30)
            if options:
                if is_frozen:
                    logger.info("[FREEZE] quality_gate: frozen options preserved despite corruption")
                else:
                    options = []
                    logger.info("[OPTIONS-DETECT] quality_gate: options cleared (no structural markers)")
        elif has_structural_markers:
            # 有结构标记时降级为 warning，不阻断
            logger.info("[OPTIONS-DETECT] quality_gate downgraded: has structural markers, preserving options")

    # --- 一致性校验阻断 (Goal 3) ---
    if not consistency["consistent"]:
        severity = consistency["severity"]
        missing_opts = ",".join(sorted(consistency["missing_in_parsed"]))
        if severity == "critical":
            errors.append(f"parse_loss: raw_has_{missing_opts}_parsed_missing")
            failure_reasons.append(f"parse_option_loss: {missing_opts}")
        else:
            warnings.append(f"parse_extra_options: parsed has extra {missing_opts}")

    # --- 代码块完整性检测 (BUGS Task 1: stem 中的代码块) ---
    from app.features.code_integrity import (
        contains_code,
        detect_code_block_integrity,
        detect_code_regression,
    )
    code_risk_flags: list[str] = []
    stem_has_code = tracer.run("code_detection", "rule", "stem", "noise_filtering",
                               contains_code, stem)
    if stem_has_code:
        code_result = detect_code_block_integrity(stem)
        tracer.add_note("code_integrity_check", f"flags={code_result.get('flags')} score={code_result.get('score')}",
                        "stem", "code_detection")
        if code_result["flags"]:
            for flag in code_result["flags"]:
                code_risk_flags.append(flag)
                warnings.append(f"code_integrity:{flag}")
                tracer.mark_corruption("code_integrity_check", flag, f"Code integrity issue: {flag}")
            # 代码完整性损坏：拉低置信度、禁止通过
            confidence_score = min(confidence_score, 0.35)
            failure_reasons.extend(code_result["flags"])
            code_risk_flags.append("code_block_incomplete")
        # --- 代码结构退化检测: raw_text vs stem (BUGS Task 4) ---
        regression = detect_code_regression(raw_text, stem)
        tracer.add_note("code_regression_check", f"has_regression={regression.get('has_regression')} flags={regression.get('flags')}",
                        "intermediate", "code_integrity_check")
        if regression["has_regression"]:
            for flag in regression["flags"]:
                if flag not in code_risk_flags:
                    code_risk_flags.append(flag)
                warnings.append(f"code_integrity:{flag}")
                tracer.mark_corruption("code_regression_check", flag, f"Code regression: {flag}")
            confidence_score = min(confidence_score, 0.30)
            failure_reasons.extend(regression["flags"])

    if confidence_score < 0.5:
        warnings.append("low_confidence")

    # === 防假成功: is_valid 复合判定 (Goal 4) ===
    # is_valid = stem_valid AND options_complete AND no_critical_ocr_corruption AND no_code_integrity_issues
    stem_valid = "missing_stem" not in errors
    options_complete = not any(e.startswith("missing_option_") for e in errors)
    no_critical_corruption = "ocr_critical_corruption" not in errors
    no_parse_loss = not any(e.startswith("parse_loss") for e in errors)
    no_code_integrity_issues = not code_risk_flags

    is_valid = (
        stem_valid
        and options_complete
        and no_critical_corruption
        and no_parse_loss
        and no_code_integrity_issues
        and len([e for e in errors if e not in ("missing_answer", "missing_answer_for_objective_question")]) == 0
    )

    # === Quality status derivation (P0: Problem E) ===
    # quality_status tracks the overall health of the question across the pipeline.
    # It is MONOTONIC: once set to a problematic state, downstream stages cannot
    # silently upgrade it without evidence of repair.
    quality_blockers: list[str] = []
    # Fatal blockers - these prevent high-confidence pass-through
    if "code_garbled_text" in code_risk_flags:
        quality_blockers.append("ocr_garbled_code")
    _answer_missing = not answer and question_type in (QT_SINGLE_CHOICE, QT_MULTIPLE_CHOICE, QT_TRUE_FALSE)
    if _answer_missing:
        quality_blockers.append("missing_answer_for_objective_question")
    if confidence_score < 0.5:
        quality_blockers.append("low_confidence")
    if not stem_valid:
        quality_blockers.append("empty_stem")
    if not options_complete:
        quality_blockers.append("incomplete_options")
    if "objective_signals_but_options_incomplete" in failure_reasons:
        quality_blockers.append("objective_signals_but_options_incomplete")
    if code_risk_flags:
        quality_blockers.append("code_integrity_issue")

    if quality_blockers:
        quality_status = "needs_manual_review"
    else:
        quality_status = "passed"
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
            or any(f.startswith("code_") for f in failure_reasons)
        )
    )

    result = {
        "schema_version": "v1",
        "subject_id": source_info.get("subject_id"),
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
        "is_frozen": is_frozen,
        # Layer 1: Question Type Classification — strict has_options gate
        "options_classified": _has_options_classified,
        "options_classify_reason": _classify_reason,
        # Goal 6: 失败追踪字段
        "validation_status": validation_status,
        "failure_reason": failure_reasons,
        "retry_recommended": retry_recommended,
        # Goal 2: OCR 质量标记
        "ocr_quality_flags": quality_gate["ocr_quality_flags"],
        # 代码完整性风险标记
        "risk_flags": (code_risk_flags[:] +
                       [r for r in failure_reasons if r.startswith("objective_signals_") or r.startswith("suspicious_")] +
                       [w[len("suspicious_options:"):] for w in warnings if w.startswith("suspicious_options:")]),
        # P0: Quality status (monotonic - can't be upgraded without evidence)
        "quality_status": quality_status,
        "quality_blockers": quality_blockers,
    }
    if blank_option_groups:
        result["blank_option_groups"] = blank_option_groups

    # === PaddleOCR-VL 视觉回退：代码完整性损坏时尝试重新识别 ===
    if not raw_question.get("_vision_fallback_attempted"):
        page_image = raw_question.get("page_image")
        if page_image and code_risk_flags:
            from app.features.vision_fallback import needs_vision_fallback

            if needs_vision_fallback(code_risk_flags):
                from app.features.vision_fallback import _build_vl_config, _call_vl_sync

                vl_config = _build_vl_config(raw_question.get("vl_config"))
                vl_text = _call_vl_sync(page_image, vl_config)
                if vl_text:
                    vl_raw = dict(raw_question)
                    vl_raw["raw_question_text"] = vl_text
                    vl_raw["_vision_fallback_attempted"] = True
                    vl_result = normalize_question(vl_raw, matched, source_info)

                    from app.features.vision_fallback import _compare_code_results

                    verdict = _compare_code_results(result, vl_result)
                    if verdict == "better":
                        vl_result["vision_fallback_attempted"] = True
                        vl_result["vision_fallback_used"] = True
                        vl_result["vision_fallback_status"] = "success"
                        vl_result["vision_fallback_engine"] = "paddleocr_vl"
                        vl_result["vision_fallback_reason"] = list(code_risk_flags)
                        vl_result["pre_fallback_code_flags"] = list(code_risk_flags)
                        post_flags = vl_result.get("risk_flags") or []
                        vl_result["post_fallback_code_flags"] = list(post_flags)
                        result = vl_result
                        logger.info(
                            "Vision fallback improved: flags %s → %s",
                            code_risk_flags, post_flags,
                        )
                    else:
                        result["vision_fallback_attempted"] = True
                        result["vision_fallback_used"] = False
                        result["vision_fallback_status"] = "not_better"
                        result["vision_fallback_engine"] = "paddleocr_vl"
                        result["vision_fallback_reason"] = list(code_risk_flags)
                        result["pre_fallback_code_flags"] = list(code_risk_flags)
                        from app.features.code_integrity import (
                            detect_code_block_integrity as _detect_code,
                        )
                        result["post_fallback_code_flags"] = list(
                            _detect_code(vl_text).get("flags", [])
                        )
                else:
                    result["vision_fallback_attempted"] = True
                    result["vision_fallback_used"] = False
                    result["vision_fallback_status"] = "failed"
                    result["vision_fallback_engine"] = "paddleocr_vl"
                    result["vision_fallback_reason"] = list(code_risk_flags)
                    result["pre_fallback_code_flags"] = list(code_risk_flags)
                    result["post_fallback_code_flags"] = list(code_risk_flags)
        elif code_risk_flags:
            result["vision_fallback_attempted"] = True
            result["vision_fallback_used"] = False
            result["vision_fallback_status"] = "unavailable"
            result["vision_fallback_reason"] = list(code_risk_flags)
            result["pre_fallback_code_flags"] = list(code_risk_flags)
            result["post_fallback_code_flags"] = list(code_risk_flags)

    # === Execution Trace: record vision fallback note ===
    tracer.add_note("vision_fallback",
                    f"attempted={result.get('vision_fallback_attempted')} status={result.get('vision_fallback_status')}",
                    "fallback", "code_integrity_check")

    # === 决策可观测性: decision_trace 初始化 ===
    result["decision_trace"] = _build_decision_trace(
        quality_gate, code_risk_flags, stem_has_code, is_valid, failure_reasons,
    )

    # === Execution Trace: attach per-question trace ===
    result["trace"] = tracer.to_list()

    # ── 透传定位/bbox 字段（从 raw_question 复制到 result）──
    _POSITIONING_FIELDS = [
        "page_start", "page_end",
        "source_question_no", "source_question_label",
        "question_bbox", "question_bbox_coordinate_space",
        "question_bbox_page_width", "question_bbox_page_height",
        "question_bbox_confidence", "question_bbox_strategy",
        "question_bbox_diagnostics",
    ]
    for _field in _POSITIONING_FIELDS:
        _val = raw_question.get(_field)
        if _val is not None:
            result[_field] = _val

    # === 最终 Schema 强制统一 ===
    result = tracer.run("output_normalization", "pipeline", "final", "vision_fallback",
                        normalize_output, result)

    # === Goal 5: 写入缓存 ===
    if _pre_cache_key:
        parse_cache_put(_cache_key_raw, _pre_cache_key, result)

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

    matched_by_num: dict[int | str, dict] = {}
    for m in matched_pairs:
        num = m["question_number"]
        if not isinstance(num, int):
            try:
                num = int(num)
            except (ValueError, TypeError):
                pass
        matched_by_num[num] = m

    questions: list[dict] = []
    errors: list[dict] = []
    warnings: list[dict] = []

    for raw_q in raw_questions:
        qnum = raw_q.get("number", 0)
        if not isinstance(qnum, int):
            try:
                qnum = int(qnum)
            except (ValueError, TypeError):
                pass
        matched = matched_by_num.get(qnum)

        try:
            result = normalize_question(raw_q, matched, source_info)
            # P1-2: 透传 splitter / 上游写入的 risk_flags，让下游 stage
            # （ai_repair / submit_to_review）和前端审核页能看到完整风险信号。
            # 值域见 prompts/tasks/ocr_book_pdf_non_question_filter_plan.md §11.3。
            upstream_flags = raw_q.get("risk_flags") or []
            existing_flags = result.get("risk_flags") or []
            merged_flags = list(dict.fromkeys(upstream_flags + existing_flags))
            if merged_flags:
                result["risk_flags"] = merged_flags
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
    result = entry.get("result")
    if result is None:
        return None
    # deepcopy prevents callers from mutating the cached result
    return copy.deepcopy(result)  # type: ignore[return-value]


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


def normalize_output(question: dict) -> dict:
    """Enforce the unified output schema.

    REQUIRED SCHEMA fields (all guaranteed to be present):

    - ``stem`` (str): cleaned question stem
    - ``code_blocks`` (list[str]): extracted code blocks
    - ``options`` (list[dict]): options as ``[{"key": "A", "text": "..."}, ...]``
    - ``answer`` (str): normalized answer
    - ``analysis`` (str): explanation text

    Extra keys from upstream are preserved, and missing required keys
    are filled with defaults.

    Args:
        question: The normalized question dict (may be partial).

    Returns:
        Dict with guaranteed schema fields.
    """
    stem = question.get("stem", "") or ""
    code_blocks: list[str] = []
    code_match = re.findall(r"```(\w*)\n(.*?)```", stem, re.DOTALL)
    for lang, code in code_match:
        code_blocks.append(code.strip())

    # Ensure options are in list[dict] format.
    # Layer 0/3: preserve original order, NO re-sorting A→D, NO padding.
    raw_options = question.get("options", [])
    question.get("question_type", "")
    is_frozen = bool(question.get("is_frozen", False))

    if is_frozen:
        # Frozen options: preserve exactly as-is, no padding, no mutation.
        # Option key order from the freeze stage is authoritative.
        if isinstance(raw_options, list):
            options_list = list(raw_options)
        elif isinstance(raw_options, dict):
            unexpected_keys = set(raw_options) - _OPTION_LETTERS
            if unexpected_keys:
                logger.warning(
                    "[FROZEN] non-ABCD option keys dropped: %s",
                    sorted(unexpected_keys),
                )
            options_list = [{"key": k, "text": raw_options[k]}
                            for k in raw_options if k in _OPTION_LETTERS]
        else:
            options_list = []
    elif isinstance(raw_options, list):
        # Preserve insertion order, no sorting, no padding
        options_list = [{"key": o["key"], "text": o["text"]}
                        for o in raw_options
                        if isinstance(o, dict) and o.get("key")]
        # Always normalize keys to uppercase
        for opt in options_list:
            opt["key"] = opt["key"].upper()
    elif isinstance(raw_options, dict):
        # Preserve dict insertion order, no sorting
        options_list = [{"key": k.upper(), "text": raw_options[k]}
                        for k in raw_options if k.upper() in _OPTION_LETTERS]
    else:
        options_list = []

    blank_groups = question.get("blank_option_groups", [])

    result: dict = {}
    result["stem"] = stem
    result["code_blocks"] = code_blocks
    result["options"] = options_list
    result["answer"] = question.get("answer", question.get("parsed_answer", "")) or ""
    result["analysis"] = question.get("analysis", "") or ""

    # Preserve other useful keys
    preserve_keys = [
        "subject", "subject_id", "question_type", "raw_text", "knowledge_points",
        "difficulty", "source", "is_valid", "errors", "warnings",
        "stem_hash", "confidence_score", "validation_status",
        "failure_reason", "retry_recommended", "ocr_quality_flags",
        "risk_flags", "decision_trace", "trace", "blank_option_groups",
        "is_frozen",
        "options_classified", "options_classify_reason",
        "vision_fallback_attempted", "vision_fallback_used",
        "vision_fallback_status", "vision_fallback_engine",
        "vision_fallback_reason",
        "pre_fallback_code_flags", "post_fallback_code_flags",
        "schema_version",
        "quality_status", "quality_blockers",
        # ── Positioning & bbox fields ──
        "page_start", "page_end",
        "source_question_no", "source_question_label",
        "question_bbox", "question_bbox_coordinate_space",
        "question_bbox_page_width", "question_bbox_page_height",
        "question_bbox_confidence", "question_bbox_strategy",
        "question_bbox_diagnostics",
    ]
    for key in preserve_keys:
        if key in question:
            val = question[key]
            if val is not None:
                result[key] = val

    if blank_groups:
        result["blank_option_groups"] = blank_groups

    # Ensure schema_version
    result.setdefault("schema_version", "v1")

    return result


def _build_decision_trace(
    quality_gate: dict,
    code_risk_flags: list[str],
    stem_has_code: bool,
    is_valid: bool,
    failure_reasons: list[str],
) -> list[dict]:
    """构建 normalize 阶段的 decision_trace 初始条目。"""
    trace: list[dict] = []

    # OCR 质量门禁
    if quality_gate.get("passed", True):
        trace.append({
            "stage": "ocr_quality_gate",
            "result": "pass",
            "reason": f"score={quality_gate.get('ocr_contamination_score', 0):.2f}",
        })
    else:
        trace.append({
            "stage": "ocr_quality_gate",
            "result": "blocked",
            "reason": (
                f"score={quality_gate.get('ocr_contamination_score', 0):.2f} "
                f"flags={quality_gate.get('ocr_quality_flags', [])}"
            ),
        })

    # 代码完整性门禁
    if code_risk_flags:
        trace.append({
            "stage": "code_gate",
            "result": "blocked",
            "reason": ";".join(code_risk_flags),
        })
    elif stem_has_code:
        trace.append({
            "stage": "code_gate",
            "result": "pass",
            "reason": "code_integrity_ok",
        })

    # 最终验证
    trace.append({
        "stage": "validation",
        "result": "pass" if is_valid else "failed",
        "reason": ";".join(failure_reasons) if failure_reasons else (
            "all_checks_passed" if is_valid else "validation_failed"
        ),
    })

    return trace
