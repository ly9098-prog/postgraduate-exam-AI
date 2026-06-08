"""文本题目解析器 — 纯规则实现。

从用户粘贴的文本中识别并结构化题目数据。
支持：标签格式、分隔线格式、批量题目、缺失标签容错。

解析结果经 process_question_pipeline() 统一标准化、去重、校验。
"""

from __future__ import annotations

import re
import logging
from typing import Any

from app.features.question_pipeline import process_question_pipeline, normalizer, _guess_subject

logger = logging.getLogger(__name__)

# ============================================================
# 分隔线模式
# ============================================================

# 批量题分隔：3+ 个 = 或 3+ 个 *
_BATCH_SEPARATOR_RE = re.compile(r"\n\s*(?:={3,}|\*{3,}|\-{3,})\s*\n")

# 题内分隔（自测版上下分栏）：3+ 个 -
_SECTION_SEPARATOR_RE = re.compile(r"\n\s*\-{3,}\s*\n")

# ============================================================
# 标签模式（兼容中英文、全角半角括号）
# ============================================================

# 标签的 bracket 部分
# 结构化标签要求：括号形式 或 行首独立标签（后跟换行或冒号）
_B = r"(?:【|\[|<)"
_E = r"(?:】|\]|>)"

_LABEL_PATTERNS = [
    # 括号形式：必须带括号
    (re.compile(rf"\s*{_B}\s*(?:题目|题干)\s*{_E}\s*", re.IGNORECASE), "stem"),
    (re.compile(rf"\s*{_B}\s*Question\s*{_E}\s*", re.IGNORECASE), "stem"),
    (re.compile(rf"\s*{_B}\s*(?:选项|Options?|Choices?)\s*{_E}\s*", re.IGNORECASE), "options"),
    (re.compile(rf"\s*{_B}\s*(?:(?:参考|正确)?答案|正确答案)\s*{_E}\s*", re.IGNORECASE), "answer"),
    (re.compile(rf"\s*{_B}\s*Answer\s*{_E}\s*", re.IGNORECASE), "answer"),
    (re.compile(rf"\s*{_B}\s*(?:解析|解答|讲解|分析)\s*{_E}\s*", re.IGNORECASE), "analysis"),
    (re.compile(rf"\s*{_B}\s*(?:Analysis|Explanation)\s*{_E}\s*", re.IGNORECASE), "analysis"),
]

# 纯标签行（用于 heuristic 模式，兼容有括号和无括号两种形式）
_LABEL_LINE_RE = re.compile(
    rf"^\s*(?:{_B}\s*)?\s*(?:题目|题干|选项|(?:参考|正确)?答案|解析|解答|讲解|分析|Question|Options?|Choices?|Answer|Analysis|Explanation)\s*(?:{_E}\s*)?[：:]?\s*$",
    re.IGNORECASE,
)

# ============================================================
# 选项标记
# ============================================================

_OPTION_LINE_RE = re.compile(r"^\s*([A-Da-d])\s*[.．、:：)）]\s*(.+)")
_OPTION_OCR_RE = re.compile(r"^\s*([A-Da-d])\s*[.．、:：)）]\s{1,3}(.+[^\s])")

# ============================================================
# 判断题答案
# ============================================================

_TRUE_FALSE_RE = re.compile(
    r"^\s*(正确|错误|对|错|True|False|√|×|T|F)\s*$",
    re.IGNORECASE,
)
_TRUE_VALUES = {"正确", "对", "true", "√", "t"}
_FALSE_VALUES = {"错误", "错", "false", "×", "f"}

# ============================================================
# 批量题号检测
# ============================================================

_BATCH_Q_NUMBER_RE = re.compile(r"^\s*(\d+)\s*[.．、)）]\s*")


def _normalize_text(text: str) -> str:
    """文本预处理：符号规范化、空行清洗。保留 【】 不被转换。"""
    text = text.replace("\xa0", " ").replace("　", " ")
    text = text.replace("：", ":").replace("（", "(").replace("）", ")")
    text = text.replace("．", ".")
    # 去除中文括号周围的 Markdown 加粗标记（如 **【题目】** → 【题目】）
    text = re.sub(r"\*{1,2}\s*([【\[\<])", r"\1", text)
    text = re.sub(r"([】\]\>])\s*\*{1,2}", r"\1", text)
    # 去除 "第X题" 独立标题行（如 **第一题**、第2题）
    text = re.sub(r"^\*{0,2}\s*第\s*[一二三四五六七八九十\d]+\s*题\s*\*{0,2}\s*$", "", text, flags=re.MULTILINE)
    # 连续空行压缩
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_batch(text: str) -> list[str]:
    """按分隔线或题号拆分批量题目。"""
    # 批量分隔线
    parts = _BATCH_SEPARATOR_RE.split(text)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) > 1:
        return parts

    # 按题号拆分
    lines = text.split("\n")
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if _BATCH_Q_NUMBER_RE.match(line) and current and _has_content(current):
            blocks.append(current)
            current = [line]
        else:
            current.append(line)
    if current and _has_content(current):
        blocks.append(current)

    if len(blocks) > 1:
        return ["\n".join(b) for b in blocks]

    return [text]


def _has_content(lines: list[str]) -> bool:
    return len(" ".join(lines).strip()) > 10


def _find_labels(text: str) -> list[tuple[int, int, str]]:
    """查找所有标签位置。返回 [(start, end, label_type), ...] 按位置排序。"""
    positions: list[tuple[int, int, str]] = []
    for pat, label_type in _LABEL_PATTERNS:
        for m in pat.finditer(text):
            positions.append((m.start(), m.end(), label_type))
    positions.sort(key=lambda x: x[0])
    return positions


def _clean_bracket_residue(text: str) -> str:
    """清除标签解析后残留的括号字符。"""
    text = text.strip()
    # 去除行首孤立的 ] 或 】 残留（后跟非字母数字字符或空白才安全删除）
    text = re.sub(r"^\s*[\]】>](?:\s+)", "", text)
    # 去除行尾孤立的 [ 或 【 残留
    text = re.sub(r"(?:\s+)[\[【<]\s*$", "", text)
    return text.strip()


def _parse_labeled_block(text: str) -> dict[str, Any]:
    """解析带标签格式的题目块。"""
    positions = _find_labels(text)

    result: dict[str, Any] = {
        "stem": "",
        "options_text": "",
        "answer": "",
        "analysis": "",
    }

    if not positions:
        return result

    for i, (start, end, label_type) in enumerate(positions):
        next_start = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        content = text[end:next_start].strip()
        content = _clean_bracket_residue(content)
        result[label_type + "_text" if label_type == "options" else label_type] = content

    return result


def _parse_options_from_text(text: str) -> list[dict[str, str]]:
    """从文本中提取选项。"""
    if not text.strip():
        return []

    options: dict[str, str] = {}
    lines = text.strip().split("\n")

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # 精确匹配
        m = _OPTION_LINE_RE.match(stripped)
        if m:
            key = m.group(1).upper()
            value = m.group(2).strip()
            if key not in options and value:
                options[key] = value
            continue

        # OCR 容错
        m = _OPTION_OCR_RE.match(stripped)
        if m:
            key = m.group(1).upper()
            value = m.group(2).strip()
            if key not in options and value:
                options[key] = value
            continue

    return [{"key": k, "text": v} for k, v in sorted(options.items())]


def _parse_unlabeled_block(text: str) -> dict[str, Any]:
    """解析无标签格式的题目块（位置启发式）。"""
    lines = text.strip().split("\n")
    result: dict[str, Any] = {
        "stem": "",
        "options_text": "",
        "answer": "",
        "analysis": "",
    }

    stem_lines: list[str] = []
    option_lines: list[str] = []
    answer_lines: list[str] = []
    analysis_lines: list[str] = []

    section = "stem"
    option_seen = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # 跳过长分隔线
        if re.match(r"^\-{3,}$", stripped) or re.match(r"^={3,}$", stripped):
            continue

        # 纯标签行检测（独立一行的标签）
        if _LABEL_LINE_RE.match(stripped):
            if re.search(r"题目|题干|Question", stripped, re.IGNORECASE):
                section = "stem"
                stem_lines = []
            elif re.search(r"选项|Options?|Choices?", stripped, re.IGNORECASE):
                section = "options"
            elif re.search(r"答案|Answer", stripped, re.IGNORECASE):
                section = "answer"
            elif re.search(r"解析|解答|分析|Analysis|Explanation", stripped, re.IGNORECASE):
                section = "analysis"
            continue

        # 行首标签 + 内容（如 "题目：xxx" / "答案：C"）
        if section in ("stem",):
            stem_label = re.match(r"^(?:题目|题干|Question)\s*[：:]\s*(.+)", stripped, re.IGNORECASE)
            if stem_label:
                stem_lines = [stem_label.group(1).strip()]
                continue

        if section in ("stem", "options"):
            opt_label = re.match(r"^(?:选项|Options?|Choices?)\s*[：:]\s*(.+)", stripped, re.IGNORECASE)
            if opt_label:
                section = "options"
                # 可能是内联选项，尝试解析
                opt_content = opt_label.group(1).strip()
                if _OPTION_LINE_RE.match(opt_content):
                    option_lines.append(opt_content)
                continue

        # 答案标签 + 内容同行
        if section in ("stem", "options"):
            ans_label = re.match(r"^(?:答案|正确答案|Answer)\s*[：:]\s*(.+)", stripped, re.IGNORECASE)
            if ans_label:
                answer_lines.append(ans_label.group(1).strip())
                section = "answer"
                continue

        # 解析标签 + 内容同行
        if section in ("stem", "options", "answer"):
            ana_label = re.match(r"^(?:解析|解答|分析|Explanation)\s*[：:]\s*(.+)", stripped, re.IGNORECASE)
            if ana_label:
                analysis_lines.append(ana_label.group(1).strip())
                section = "analysis"
                continue

        # 选项行检测
        if section in ("stem", "options"):
            if _OPTION_LINE_RE.match(stripped) or _OPTION_OCR_RE.match(stripped):
                option_lines.append(stripped)
                option_seen = True
                section = "options"
                continue

        # 判断题答案必须在选项前出现（无选项时 option_seen=False，正常识别）
        if section in ("stem", "options", "answer"):
            if _TRUE_FALSE_RE.match(stripped) and not option_seen:
                answer_lines.append(stripped)
                section = "answer"
                continue

        # 单选题答案（单独一行，单个A-D字母）
        if section in ("stem", "options", "answer"):
            if re.match(r"^\s*[A-Da-d]\s*$", stripped) and option_seen:
                answer_lines.append(stripped)
                section = "answer"
                continue

        # 多选题答案（ABCD/ACD等）
        if section in ("stem", "options", "answer"):
            if re.match(r"^\s*[A-Da-d,，、\s]{2,}\s*$", stripped) and option_seen:
                answer_lines.append(stripped)
                section = "answer"
                continue

        # 数字/文本答案（选项后未识别的短行 → 可能是答案）
        if section in ("stem", "options") and option_seen and not answer_lines:
            if len(stripped) <= 40 and not re.match(r"^\s*[A-Da-d]\s*[.．、:：)）]", stripped):
                answer_lines.append(stripped)
                section = "answer"
                continue

        # 累积到当前 section
        if section == "stem":
            stem_lines.append(stripped)
        elif section == "options":
            option_lines.append(stripped)
        elif section == "answer":
            # 答案通常为短文本（1-2行），后续长文本/分析特征 → 自动切换为解析
            if answer_lines and (
                len(stripped) > 60
                or re.search(r"[→=]|故[答案为]|因此|所以|故选|综上|根据|由.*可知", stripped)
            ):
                analysis_lines.append(stripped)
                section = "analysis"
            else:
                answer_lines.append(stripped)
        elif section == "analysis":
            analysis_lines.append(stripped)

    result["stem"] = "\n".join(stem_lines).strip()
    result["options_text"] = "\n".join(option_lines).strip()
    result["answer"] = "\n".join(answer_lines).strip()
    result["analysis"] = "\n".join(analysis_lines).strip()
    return result


# 严格标签：必须有括号且出现在行首
_STRICT_LABEL_RE = re.compile(
    r"^\s*(?:【|\[)\s*(?:题目|题干|选项|(?:参考|正确)?答案|解析|解答|讲解|分析|Question|Options?|Choices?|Answer|Analysis|Explanation)\s*(?:】|\])",
    re.IGNORECASE | re.MULTILINE,
)


def _has_labels(text: str) -> bool:
    """检查文本是否包含结构化标签（括号形式、出现在行首）。"""
    return bool(_STRICT_LABEL_RE.search(text))


def _has_question_indicators(text: str) -> bool:
    """检查文本块是否包含题目特征，用于过滤引言、说明等无关文本。"""
    if _has_labels(text):
        return True
    # 选项标记（2+ 行 A/B/C/D 格式）
    lines = text.split("\n")
    option_count = 0
    for line in lines:
        if _OPTION_LINE_RE.match(line.strip()):
            option_count += 1
    if option_count >= 2:
        return True
    # 问答题特征
    if re.search(r"[？?]|（\s*）|\(\s*\)|_{2,}", text):
        return True
    if re.search(r"(?:答案|正确答案|Answer)\s*[：:]", text):
        return True
    return False


def _detect_question_type(options: list[dict], answer: str | list[str] | bool) -> str:
    """自动判断题型。"""
    # 判断题
    if isinstance(answer, bool):
        return "true_false"

    if isinstance(answer, str):
        cleaned = answer.strip().lower()
        if cleaned in _TRUE_VALUES or cleaned in _FALSE_VALUES:
            return "true_false"

    # 多选题
    if isinstance(answer, list) and len(answer) > 1:
        return "multiple_choice"

    # 多选题（字符串形式，如 "ABCD" 或 "A,C,D"）
    if isinstance(answer, str) and len(answer) > 1:
        parts = [p.strip().upper() for p in re.split(r"[,，、\s]+", answer) if p.strip()]
        if len(parts) > 1 and all(re.fullmatch(r"[A-D]", p) for p in parts):
            return "multiple_choice"

    # 有选项 → 单选题
    if options:
        return "single_choice"

    # 无选项有答案 → 问答题
    if answer:
        return "subjective"

    return "subjective"


def _normalize_answer_text(answer_str: str) -> str | list[str] | bool:
    """规范化答案文本。"""
    cleaned = answer_str.strip()

    if not cleaned:
        return ""

    # 判断题
    lower = cleaned.lower()
    if lower in _TRUE_VALUES:
        return True
    if lower in _FALSE_VALUES:
        return False

    # 多选题（无分隔符连续字母，如 ABCD）
    if len(cleaned) >= 2 and re.fullmatch(r"[A-Da-d]{2,}", cleaned):
        return sorted({c.upper() for c in cleaned})

    # 多选题（有分隔符，如 A,C,D 或 A B D）
    if len(cleaned) > 1:
        parts = [p.strip().upper() for p in re.split(r"[,，、\s]+", cleaned) if p.strip()]
        if len(parts) > 1 and all(re.fullmatch(r"[A-D]", p) for p in parts):
            return sorted(set(parts))

    # 单选题
    if re.fullmatch(r"[A-Da-d]", cleaned):
        return cleaned.upper()

    return cleaned


def _block_to_raw(block_text: str) -> dict[str, Any]:
    """将一个文本块解析为原始题目数据。"""
    warnings: list[str] = []

    if _has_labels(block_text):
        labeled = _parse_labeled_block(block_text)
        stem = labeled["stem"]
        options = _parse_options_from_text(labeled["options_text"])
        answer = _normalize_answer_text(labeled["answer"])
        analysis = labeled["analysis"]
        detection_method = "labeled"
    else:
        unlabeled = _parse_unlabeled_block(block_text)
        stem = unlabeled["stem"]
        options = _parse_options_from_text(unlabeled["options_text"])
        answer = _normalize_answer_text(unlabeled["answer"])
        analysis = unlabeled["analysis"]
        detection_method = "heuristic"
        if not stem:
            warnings.append("无法识别题干，请检查文本格式")

    question_type = _detect_question_type(options, answer)

    if not stem and not options and not answer:
        warnings.append("未能从文本中解析出题目信息")

    return {
        "stem": stem,
        "options": options,
        "answer": answer,
        "analysis": analysis,
        "question_type": question_type,
        "detection_method": detection_method,
        "warnings": warnings,
    }


def parse_text_questions(text: str, subject: str) -> dict[str, Any]:
    """解析用户粘贴的文本，返回结构化题目列表。

    Args:
        text: 用户粘贴的原始文本
        subject: 科目（必填，由前端下拉框选择）

    Returns:
        {
            "questions": [...],
            "warnings": [...],
            "raw_count": int,
            "valid_count": int,
        }
    """
    global_warnings: list[str] = []
    all_questions: list[dict] = []

    # 1. 文本预处理
    text = _normalize_text(text)

    if not text.strip():
        return {
            "questions": [],
            "warnings": ["输入文本为空"],
            "raw_count": 0,
            "valid_count": 0,
        }

    # 2. 拆分为题目块
    blocks = _split_batch(text)

    # 3. 逐个块解析
    raw_questions: list[dict] = []
    q_index = 0
    for i, block in enumerate(blocks):
        # 过滤引言、说明等与题目无关的文本块
        if not _has_question_indicators(block):
            continue

        # 题内分隔线（自测版上下分栏），合并为一块
        sections = _SECTION_SEPARATOR_RE.split(block)
        if len(sections) > 1:
            block = "\n".join(s.strip() for s in sections if s.strip())

        raw = _block_to_raw(block)
        raw["block_index"] = q_index
        raw_questions.append(raw)
        for w in raw.get("warnings", []):
            global_warnings.append(f"第{q_index + 1}题: {w}")
        q_index += 1

    # 4. 通过 pipeline 标准化
    for raw in raw_questions:
        # 自动检测科目
        q_subject = subject or _guess_subject(raw["stem"] + " " + (raw.get("analysis") or "")) or ""

        pipeline_input = {
            "subject": q_subject,
            "stem": raw["stem"],
            "options": raw["options"],
            "answer": raw["answer"],
            "analysis": raw["analysis"],
            "question_type": raw["question_type"],
        }

        # 判断题：bool → 字符串格式（pipeline 能处理）
        if isinstance(pipeline_input["answer"], bool):
            pipeline_input["answer"] = "正确" if pipeline_input["answer"] else "错误"

        result = process_question_pipeline(
            pipeline_input,
            source_type="text",
            source={"file": "text_import", "page": 0},
        )

        normalized = result["normalized"]

        q_data = {
            "subject": normalized.get("subject"),
            "question_type": normalized.get("question_type"),
            "stem": normalized.get("stem"),
            "options": normalized.get("options"),
            "answer": normalized.get("answer"),
            "analysis": normalized.get("analysis"),
            "knowledge_points": normalized.get("knowledge_points"),
            "difficulty": normalized.get("difficulty"),
            "is_valid": result["is_valid"],
            "errors": result["errors"],
            "warnings": result["warnings"] + raw.get("warnings", []),
            "question_hash": normalized.get("question_hash"),
            "stem_hash": normalized.get("stem_hash"),
            "block_index": raw.get("block_index", 0),
            "detection_method": raw.get("detection_method", "unknown"),
        }
        all_questions.append(q_data)

    valid_count = sum(1 for q in all_questions if q["is_valid"])

    if not all_questions:
        global_warnings.append("未识别到任何题目，请检查文本格式")

    return {
        "questions": all_questions,
        "warnings": global_warnings,
        "raw_count": len(raw_questions),
        "valid_count": valid_count,
    }
