"""文本题目解析器 — 纯规则实现。

从用户粘贴的文本中识别并结构化题目数据。
支持：标签格式、分隔线格式、批量题目、缺失标签容错。

解析结果经 process_question_pipeline() 统一标准化、去重、校验。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.question_pipeline import _guess_subject, process_question_pipeline
from app.services.formula_normalizer import fix_ocr_formula, normalize_text_import_math

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

# 仅匹配 . ． 、 结尾的题号（不含 ) ），避免将 "1）" 等子项标记误判为分题分隔
_BATCH_Q_NUMBER_RE = re.compile(r"^\s*(\d+)\s*[.．、]\s*")

# 回退分题：【题目】/【题干】标签（格式化破坏时可能不在行首）
_QUESTION_LABEL_SPLIT_RE = re.compile(r"(?=(?:【|\[)\s*(?:题目|题干)\s*(?:】|\]))")

# 回退分题：内联 --- 分隔（格式化破坏时可能不在独立行）
_INLINE_BATCH_SEP_RE = re.compile(r"\s{2,}-{3,}\s{2,}|[。！？.!?]\s*-{3,}\s*")

# 子题标记（如 ①、②、(①)、\(①\) 等，常见于 AI 复制格式的多小题题干）
_SUBQ_MARKER_RE = re.compile(r"^\s*(?:\\?[\(\\]?\s*)?[①②③④⑤⑥⑦⑧⑨⑩](?:\s*\\?[\)]?)?\s*")

# 题号前缀（如 "29．"、"30. "、"1) "）
_Q_NUMBER_PREFIX_RE = re.compile(r"^\s*\d+\s*[.．、)）]\s*")


def _normalize_text(text: str) -> str:
    """文本预处理：符号规范化、空行清洗。保留 【】 不被转换。"""
    text = text.replace("\xa0", " ").replace("　", " ")
    text = text.replace("：", ":").replace("（", "(").replace("）", ")")
    text = text.replace("．", ".")
    # 去除 Markdown 加粗标记（如 **答案：C** → 答案：C，**29．xxx** → 29．xxx）
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    # 去除 Markdown 引用标记（> 开头，可能连续多个 > >）
    text = re.sub(r"^(?:>\s?)+", "", text, flags=re.MULTILINE)
    # LaTeX 定界符统一为 $...$ 格式（前端渲染器仅支持 $）
    # 1) 清除 \( 和 \) 旁边多余的 $（如 \($P_{1}\) → \(P_{1}\)）
    text = re.sub(r"\\\(\$", r"\\(", text)
    text = re.sub(r"\$\\\)", r"\\)", text)
    # 2) 将 \(...\) 转换为 $...$（前端只识别 $ 定界符）
    text = re.sub(r"\\\((.+?)\\\)", r"$\1$", text, flags=re.DOTALL)
    # 3) 清除 LaTeX 文本字体命令（AI 常对普通文本过度使用 \mathrm 等）
    text = re.sub(r"\\mathrm\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\textbf\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\textit\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\mathtt\{([^}]*)\}", r"\1", text)
    # 4) 保护成对的 $...$，移除残余孤立 $
    _pairs = re.findall(r"\$[^$\n]+?\$", text)
    _map = {}
    for _i, _p in enumerate(_pairs):
        _k = f"\x00PROT{_i}\x00"
        _map[_k] = _p
        text = text.replace(_p, _k)
    text = re.sub(r"\$", "", text)
    for _k, _p in _map.items():
        text = text.replace(_k, _p)
    # "第X题" 独立标题行 → 批量分隔标记，让 _split_batch 能正确分题
    text = re.sub(r"^\*{0,2}\s*第\s*[一二三四五六七八九十\d]+\s*题\s*\*{0,2}\s*$", "\n===\n", text, flags=re.MULTILINE)
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

    # 回退：【题目】/【题干】标签拆分（格式化破坏时可能不在行首）
    parts = _QUESTION_LABEL_SPLIT_RE.split(text)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) > 1:
        return parts

    # 回退：内联 --- 拆分（格式化破坏时可能不在独立行）
    parts = _INLINE_BATCH_SEP_RE.split(text)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) > 1:
        return parts

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


def _break_inline_text(text: str) -> str:
    """将单行内联文本拆分为多行，便于行级启发式解析器处理。

    处理复制粘贴后格式化被破坏的文本：题干、选项、答案、解析全部连在一行，
    通过插入换行符恢复基本结构。
    """
    # 去除内联 **第X题** / 第X题： 标题
    text = re.sub(r"\*{0,2}\s*第\s*[一二三四五六七八九十\d]+\s*题\s*\*{0,2}\s*[：:]?\s*", "", text)
    # 在选项标记前插入换行（A.xxx B.xxx 等，要求选项后跟空格以确保是真实选项）
    text = re.sub(r"(?<=[^\s])\s*(?=[A-Da-d]\s*[.．、:：)）]\s)", "\n", text)
    # 在子题标记（如 \(①\)、\(②\)）前插入换行，确保其独立成行后被跳过
    text = re.sub(r"\s+(?=[\(\\]?\s*[①②③④⑤⑥⑦⑧⑨⑩]\s*\)?\s*[A-Da-d]\s*[.．、:：)）])", "\n", text)
    return text


def _clean_stem_number(stem: str) -> str:
    """去除题干开头的题号前缀（如 '29．'、'30. '、'1) '）。"""
    lines = stem.split("\n")
    if lines:
        lines[0] = _Q_NUMBER_PREFIX_RE.sub("", lines[0])
    return "\n".join(lines).strip()


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


# 内联选项拆分：A. xxx B. xxx → 拆为独立选项
def _normalize_option_math(text: str) -> str:
    value = fix_ocr_formula(text)
    value = normalize_text_import_math(value, compact=True)
    value = re.sub(r"^\$\s*(.*?)\s*\$$", r"\1", value, flags=re.S)
    return value


_INLINE_OPTION_SPLIT_RE = re.compile(r"\s+(?=[A-Da-d]\s*[.．、:：)）])")


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

        # 检查是否包含内联多选项（一行含多个 A.xxx B.xxx）
        parts = _INLINE_OPTION_SPLIT_RE.split(stripped)
        candidates = parts if len(parts) > 1 else [stripped]

        for cand in candidates:
            cand = cand.strip()
            if not cand:
                continue

            # 精确匹配
            m = _OPTION_LINE_RE.match(cand)
            if m:
                key = m.group(1).upper()
                value = _normalize_option_math(m.group(2).strip())
                if key not in options and value:
                    options[key] = value
                continue

            # OCR 容错
            m = _OPTION_OCR_RE.match(cand)
            if m:
                key = m.group(1).upper()
                value = _normalize_option_math(m.group(2).strip())
                if key not in options and value:
                    options[key] = value
                continue

    return [{"key": k, "text": v} for k, v in sorted(options.items())]


def _parse_unlabeled_block(text: str) -> dict[str, Any]:
    """解析无标签格式的题目块（位置启发式）。"""
    lines = text.strip().split("\n")

    # 检测内联选项：任何行包含多个选项标记（如 "A. xxx B. xxx"）
    has_inline_options = any(
        len(_INLINE_OPTION_SPLIT_RE.split(ln.strip())) > 1
        for ln in lines if ln.strip()
    )
    if has_inline_options or len(lines) <= 2:
        text = _break_inline_text(text)
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

    prev_empty = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            # Preserve blank lines in stem to keep visual separation (e.g. around code blocks)
            # Collapse consecutive blanks — skip if we already recorded an empty line
            if section == "stem" and not prev_empty and stem_lines:
                stem_lines.append("")
                prev_empty = True
            continue
        prev_empty = False

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

        # 选项行检测（先去除子题标记如 ①、② 等，再匹配选项）
        stripped_for_opt = _SUBQ_MARKER_RE.sub("", stripped).strip()
        if not stripped_for_opt:
            continue
        if section in ("stem", "options"):
            opt_m = _OPTION_LINE_RE.match(stripped_for_opt) or _OPTION_OCR_RE.match(stripped_for_opt)
            if opt_m:
                opt_key = opt_m.group(1).upper()
                opt_val = opt_m.group(2).strip()
                # 值中含连续空格 → 后半段可能是答案/解析（内联格式污染）
                if "  " in opt_val:
                    parts = opt_val.split("  ", 1)
                    opt_val = parts[0].strip()
                    excess = parts[1].strip()
                    option_lines.append(f"{opt_key}. {opt_val}")
                    option_seen = True
                    section = "options"
                    # 尝试将 excess 分为答案 + 解析
                    if "  " in excess:
                        ans_part, ana_part = excess.split("  ", 1)
                        answer_lines.append(ans_part.strip())
                        analysis_lines.append(ana_part.strip())
                        section = "analysis"
                    elif len(excess) <= 40:
                        answer_lines.append(excess)
                        section = "answer"
                    else:
                        analysis_lines.append(excess)
                        section = "analysis"
                # 值中嵌入单个答案字母（如 "指令系统 C 虚拟存储器"）
                else:
                    m2 = re.match(r"(.+?)\s+([A-Da-d])\s+(.+)", opt_val)
                    if m2:
                        clean_val = m2.group(1).strip()
                        ans_letter = m2.group(2).upper()
                        ana_text = m2.group(3).strip()
                        if len(clean_val) > 3:  # 选项值必须足够长，避免 "选 A 或 B" 误匹配
                            option_lines.append(f"{opt_key}. {clean_val}")
                            option_seen = True
                            section = "options"
                            answer_lines.append(ans_letter)
                            analysis_lines.append(ana_text)
                            section = "analysis"
                        else:
                            option_lines.append(f"{opt_key}. {opt_val}")
                            option_seen = True
                            section = "options"
                    else:
                        option_lines.append(f"{opt_key}. {opt_val}")
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
            # Preserve leading whitespace for code indentation (use rstrip only)
            stem_lines.append(line.rstrip())
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

    result["stem"] = normalize_text_import_math(_clean_stem_number("\n".join(stem_lines).strip()))
    result["options_text"] = "\n".join(option_lines).strip()
    result["answer"] = "\n".join(answer_lines).strip()
    result["analysis"] = normalize_text_import_math("\n".join(analysis_lines).strip())
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


def _prepare_blocks(text: str) -> tuple[list[str], dict[str, Any] | None]:
    """文本预处理 + 拆分。返回 (blocks, early_return)。"""
    text = _normalize_text(text)
    if not text.strip():
        return [], {
            "questions": [],
            "warnings": ["输入文本为空"],
            "raw_count": 0,
            "valid_count": 0,
        }

    raw_blocks = _split_batch(text)
    cleaned: list[str] = []
    for block in raw_blocks:
        if not _has_question_indicators(block):
            continue
        sections = _SECTION_SEPARATOR_RE.split(block)
        if len(sections) > 1:
            block = "\n".join(s.strip() for s in sections if s.strip())
        cleaned.append(block)
    return cleaned, None


_INLINE_ANSWER_LABEL_RE = re.compile(
    r"(?:【|\[)?\s*(?:参考|正确)?\s*(?:答案|Answer|Ans|Key)\s*(?:】|\])?\s*[：:]",
    re.IGNORECASE,
)
_INLINE_OPTION_MARKER_RE = re.compile(r"\s[A-Da-d]\s*[.．、:：)）]\s*\S")


def _rule_options_look_broken(options: list[dict[str, Any]]) -> bool:
    """检测规则解析出的选项是否明显损坏。

    判定标准：
    - 选项 key 不从 A 开始或不连续（如 [B, C, D] 或 [A, C, D]）
    - 选项 text 内嵌答案标签（"答案：" / "Answer:"）— 说明答案区段被吃进选项
    - 选项 text 内嵌另一个选项标记（如 " B. " / " C. "）— 说明选项之间未被正确切分
    - 选项 text 含换行 — 通常意味着粘合了下一段内容
    """
    if not options:
        return False
    keys = [str(opt.get("key") or "").strip().upper() for opt in options]
    expected = [chr(ord("A") + i) for i in range(len(keys))]
    if keys != expected:
        return True
    for opt in options:
        text = str(opt.get("text") or "")
        if not text:
            continue
        if "\n" in text:
            return True
        if _INLINE_ANSWER_LABEL_RE.search(text):
            return True
        if _INLINE_OPTION_MARKER_RE.search(text):
            return True
    return False


def _merge_llm_into_raw(raw: dict[str, Any], llm_out: dict[str, Any]) -> dict[str, Any]:
    """将 LLM 结构化结果合并回 raw dict。

    合并策略：仅在 LLM 提供了"更完整"或"原本缺失"的字段时替换。
    LLM 输出已经过反幻觉守门，未通过的字段在 llm_out 中为 null / 空。
    """
    merged = dict(raw)

    llm_stem = (llm_out.get("stem") or "").strip()
    if llm_stem and (not merged.get("stem") or len(llm_stem) > len(merged["stem"])):
        # 用 LLM 题干，但仍走规则解析器的去题号 + 数学公式归一化
        merged["stem"] = normalize_text_import_math(_clean_stem_number(llm_stem))

    llm_options = llm_out.get("options") or []
    rule_options = merged.get("options") or []
    if llm_options and (
        len(llm_options) > len(rule_options)
        or (
            len(llm_options) == len(rule_options)
            and _rule_options_look_broken(rule_options)
        )
    ):
        # 重新走选项数学公式归一化
        merged["options"] = [
            {"key": opt["key"], "text": _normalize_option_math(opt["text"])}
            for opt in llm_options
        ]

    llm_answer = llm_out.get("answer")
    rule_answer = merged.get("answer")
    rule_answer_empty = (
        rule_answer is None
        or rule_answer == ""
        or (isinstance(rule_answer, list) and not rule_answer)
    )
    if llm_answer and rule_answer_empty:
        merged["answer"] = _normalize_answer_text(
            llm_answer if isinstance(llm_answer, str) else ",".join(llm_answer)
        )

    llm_analysis = (llm_out.get("analysis") or "").strip() if isinstance(llm_out.get("analysis"), str) else ""
    if llm_analysis and not (merged.get("analysis") or "").strip():
        merged["analysis"] = normalize_text_import_math(llm_analysis)

    llm_qt = llm_out.get("question_type")
    if llm_qt and (
        not merged.get("question_type")
        or merged.get("question_type") == "subjective"
    ):
        merged["question_type"] = llm_qt

    # 重新推断题型（避免 LLM 给的 question_type 与 answer 不一致）
    merged["question_type"] = _detect_question_type(
        merged.get("options") or [], merged.get("answer")
    )
    return merged


def _finalize_questions(
    raw_questions: list[dict[str, Any]],
    subject_code: str,
) -> tuple[list[dict[str, Any]], int]:
    """走 pipeline 标准化 + 校验，返回 (questions, valid_count)。"""
    out: list[dict] = []
    for raw in raw_questions:
        q_subject_code = subject_code or _guess_subject(raw["stem"] + " " + (raw.get("analysis") or "")) or ""

        pipeline_input = {
            "subject": q_subject_code,
            "stem": raw["stem"],
            "options": raw["options"],
            "answer": raw["answer"],
            "analysis": raw["analysis"],
            "question_type": raw["question_type"],
            "preserve_plain_math": True,
        }
        if isinstance(pipeline_input["answer"], bool):
            pipeline_input["answer"] = "正确" if pipeline_input["answer"] else "错误"

        result = process_question_pipeline(
            pipeline_input,
            source_type="text",
            source={"file": "text_import", "page": 0},
        )

        normalized = result["normalized"]
        out.append({
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
        })

    valid_count = sum(1 for q in out if q["is_valid"])
    return out, valid_count


def parse_text_questions(text: str, subject: str) -> dict[str, Any]:
    """解析用户粘贴的文本，返回结构化题目列表（仅规则解析）。

    保留同步入口以兼容现有调用方与测试。需要 LLM 兜底请使用
    parse_text_questions_async。
    """
    blocks, early = _prepare_blocks(text)
    if early is not None:
        return early

    global_warnings: list[str] = []
    raw_questions: list[dict] = []
    for q_index, block in enumerate(blocks):
        raw = _block_to_raw(block)
        raw["block_index"] = q_index
        raw_questions.append(raw)
        for w in raw.get("warnings", []):
            global_warnings.append(f"第{q_index + 1}题: {w}")

    questions, valid_count = _finalize_questions(raw_questions, subject)
    if not questions:
        global_warnings.append("未识别到任何题目，请检查文本格式")

    return {
        "questions": questions,
        "warnings": global_warnings,
        "raw_count": len(raw_questions),
        "valid_count": valid_count,
    }


async def parse_text_questions_async(text: str, subject: str, db: AsyncSession | None = None) -> dict[str, Any]:
    """规则解析为主，结构完整度低时调用 LLM 结构化兜底。

    LLM 仅做格式整理：识别题干 / 选项 / 答案 / 解析区域、修复换行、
    提取多空结构。绝不补全、推测、生成内容。所有 LLM 输出经过反幻觉
    守门后才合并回结果，最终仍走 process_question_pipeline 标准化。
    """
    from app.features.llm_text_structurer import should_call_llm, structure_text_block

    blocks, early = _prepare_blocks(text)
    if early is not None:
        return early

    global_warnings: list[str] = []
    raw_questions: list[dict] = []

    for q_index, block in enumerate(blocks):
        raw = _block_to_raw(block)
        raw["block_index"] = q_index

        should_call, reason = should_call_llm(block, raw)
        if should_call:
            llm_out = await structure_text_block(
                block,
                rule_hint={
                    "stem": raw.get("stem"),
                    "options": raw.get("options"),
                    "answer": raw.get("answer"),
                    "analysis": raw.get("analysis"),
                },
                db=db,
            )
            if llm_out is not None:
                raw = _merge_llm_into_raw(raw, llm_out)
                raw["block_index"] = q_index
                raw["detection_method"] = "llm_structured"
                raw["llm_reason"] = reason
                raw["llm_dropped"] = llm_out.get("_dropped") or []
                # 守门移除字段记录到 warnings，便于排查
                for f in raw["llm_dropped"]:
                    global_warnings.append(
                        f"第{q_index + 1}题: LLM 输出字段 {f} 未通过反幻觉校验，已置空"
                    )
            else:
                raw["llm_reason"] = reason
                raw["detection_method"] = raw.get("detection_method", "heuristic") + "_llm_failed"

        raw_questions.append(raw)
        for w in raw.get("warnings", []):
            global_warnings.append(f"第{q_index + 1}题: {w}")

    questions, valid_count = _finalize_questions(raw_questions, subject)
    if not questions:
        global_warnings.append("未识别到任何题目，请检查文本格式")

    return {
        "questions": questions,
        "warnings": global_warnings,
        "raw_count": len(raw_questions),
        "valid_count": valid_count,
    }
