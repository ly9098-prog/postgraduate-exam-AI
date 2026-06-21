"""导入文本标准化层 — 纯规则文本清洗。

职责：清洗换行、乱码、空格、OCR 字符混淆。
不做 AI 分析、不做题目识别、不做答案匹配。
"""

import os
import re
from typing import Set as TypedSet

# 已知 OCR 箭头乱码模式（PaddleOCR 特定字体/排版将 -> 误识为 <- + 随机字母前缀）
# 支持环境变量覆盖：OCR_ARROW_GARBLED_PATTERNS="xau,axau,xeu,Aaxd"
_OCR_ARROW_GARBLED_PATTERNS: tuple[str, ...] = tuple(
    p for p in os.environ.get("OCR_ARROW_GARBLED_PATTERNS", "xau,axau,xeu,Aaxd").split(",")
    if p
)

# 低信息量噪声检测阈值（可通过环境变量覆盖）
_SHORT_NOISE_CHAR_LIMIT: int = int(os.environ.get("OCR_SHORT_NOISE_CHAR_LIMIT", "6"))
_LOW_INFO_CASE_SWITCH_RATIO: float = float(os.environ.get("OCR_LOW_INFO_CASE_SWITCH_RATIO", "0.35"))


# Unicode 替换字符和常见 OCR 乱码
_RE_GARBLED = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]|�|□+"
)

_CIRCLED_OPTION_CHARS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_OPTION_PREFIX_MARKER = r"(?:[?？]\s*|[" + _CIRCLED_OPTION_CHARS + r"]\s*)?"
_OPTION_MARKER = _OPTION_PREFIX_MARKER + r"([A-Da-d])\s*[.．、:：)）]"
_INLINE_OPTION_MARKER = re.compile(r"(?<![A-Za-z0-9])" + _OPTION_MARKER)
_RE_OPTION_MARKER = re.compile(_OPTION_MARKER)
_RE_CIRCLED_GROUP_MARKER = re.compile(
    r"^(?:[" + _CIRCLED_OPTION_CHARS + r"]|[（(]\s*[" + _CIRCLED_OPTION_CHARS + r"]\s*[）)])$"
)
_CIRCLED_GROUP_MARKER_PATTERN = r"(?:[" + _CIRCLED_OPTION_CHARS + r"]|[（(]\s*[" + _CIRCLED_OPTION_CHARS + r"]\s*[）)])"
_GROUP_MARKER_PATTERN = r"(?:" + _CIRCLED_GROUP_MARKER_PATTERN + r"|[（(]\s*\d{1,2}\s*[）)]|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ])"

# 题号行：用于 OCR 字符纠正的上下文判断
_RE_QUESTION_NUMBER = re.compile(
    r"^\s*\d+\s*[.、)）]"
)

# 行首选项标记（用于 OCR 纠正上下文）
_RE_OPTION_LINE = re.compile(
    r"^[A-Da-d8６0Oo]\s*[.、:：）]"
)

# Roman numeral constants imported from shared module (single source of truth)
from app.features.roman_schema import (  # noqa: E402
    _ROMAN_SUBITEM_TOKEN, _RE_ROMAN_SUBITEM_MARKER, _ROMAN_TO_VALUE, _VALUE_TO_ROMAN,
)

# 结构标记行：不应被合并到上行的模式
_RE_STRUCTURE_LINE = re.compile(
    r"^("
    r"\d+\s*[.、)）]"
    r"|" + _OPTION_MARKER +
    r"|" + _GROUP_MARKER_PATTERN + r"\s*$"
    r"|" + _ROMAN_SUBITEM_TOKEN + r"\s*[.、)）]"
    r"|[（(]\s*[A-D]\s*[）)]"
    r"|(?:【)?(?:参考|正确)?答案(?:】)?\s*[：:]"
    r"|(?:【)?(?:解析|解答|讲解|分析)(?:】)?\s*[：:]"
    r")"
)

# 上一行是完整结构行时，下一行默认不继续并入上一行
_RE_PREV_STRUCTURE_LINE = re.compile(
    r"^"
    r"(" + _OPTION_MARKER + r"\s*.{1,}"
    r"|" + _GROUP_MARKER_PATTERN + r"\s*$"
    r"|[（(]\s*[A-Da-d]\s*[）)]\s*.{1,}"
    r"|(?:【)?(?:参考|正确)?答案(?:】)?\s*[：:]\s*.{1,}"
    r"|(?:【)?(?:解析|解答|讲解|分析)(?:】)?\s*[：:]\s*.{1,}"
    r")"
)

_SENTENCE_END = frozenset("。！？；…")

# 水印关键词模式（覆盖OCR识别出的各种变体）
# 仅过滤「整行即水印」的安全情形；当水印位置性地渗入题目正文中间时（OCR 版面
# 错乱），无法在文本层安全切除，留给 OCR 引擎层处理（参见 docs/BUGS.md 案例二/十）。
_RE_WATERMARK = re.compile(
    r"^(王道|计算?机教育|机教育|算机教育|道计算|几教育|千道|全丰道|"
    r"王道计算机教育|道计算机|道计管教育|kaoya[no]?|Kaoyan|"
    r"w{0,3}\.?com|n\.com|ska|ai\.|"
    r"后续关注|关注公众号|扫码关注|扫描二维码|永久微信|微信号|公众号|"
    r"[\[【（(]?\s*研大\s*[\]】）)]?|"
    r"\d{4}年.*考研.*指导|"
    r"数据结构.*复习指导|"
    r"计算机.*考研|"
    r"O\s*口\s*医"  # 常见页脚装饰碎片（参见 BUGS.md 案例二）
    r").*$"
)

# 独立章标题行检测 — 仅删除纯章标题行，不删除章标题与题目内容合并的行
# 不应删除："第1章 线性表 1.下列选项中正确的是（）"
# 应删除："第1章 线性表"
_RE_CHAPTER_HEADER = re.compile(
    r"^第\s*\d+\s*章\s*\S+"
)

# 题目特征信号 — 用于判断章标题后是否跟有题目内容
_RE_QUESTION_SIGNAL = re.compile(
    r"\d+\s*[.、)）]|"
    r"[A-D]\s*[.、:：)）]|"
    r"下列|以下|正确|错误|的是|哪|选择|计算|判断|已知|设|若|问|求"
)

# 页码模式：纯数字或带少量空格的1-3位数
_RE_PAGE_NUMBER = re.compile(r"^\s*\d{1,3}\s*$")

# C 指针箭头 OCR 伪影：PaddleOCR 常把 "->" 识别成 "− >"/"- >"（减号/各类破折号 +
# 空格 + 大于号），导致 408 链表代码（p->next、q->prior->next）面目全非。
# 仅当 ">" 紧跟标识符字符时才纠正，避免误伤数学式 "a − > b"（> 后有空格不命中）。
# 规则幂等：已正确的 "p->next" 再跑一次仍是 "p->next"（参见 docs/BUGS.md 案例三/七/十）。
_RE_POINTER_ARROW = re.compile(r"([\w)\]）】])\s*[−\-–—]\s*>(?=\w)")

# PaddleOCR -> 误识为 <- + 随机字母前缀（已知幻觉模式）
# 例: p->next → p xau<- next / p axau<- next / p xeu<- next
# 这些是 OCR 引擎对特定字体/排版的确定性误识，修复安全。
# 模式列表可从环境变量 OCR_ARROW_GARBLED_PATTERNS 追加。
_RE_POINTER_ARROW_GARBLED_KNOWN = re.compile(
    r"\b(" + "|".join(re.escape(p) for p in _OCR_ARROW_GARBLED_PATTERNS) + r")<-(?=\s*[a-zA-Z_])"
)

# 通用箭头方向修复：在 C 指针上下文中 <- 不是合法运算符，
# 小写标识符后跟 <- 极可能是 OCR 将 -> 翻转为 <- 的产物。
# 仅当左侧是单个小写标识符（1-4 个字母+数字）时执行，
# 负向先行断言要求右侧紧跟字母/下划线（C 成员访问模式 —>next/->data）。
_RE_POINTER_ARROW_REVERSED = re.compile(
    r"([a-z_][a-z0-9_]{0,3})<-(?=\s*[a-zA-Z_])"
)

# LaTeX 命令标记清理
_RE_LATEX_DOTS = re.compile(r"\\l(?:dots|dotsquare|ldots)")
_RE_LATEX_CDOTS = re.compile(r"\\c(dots|dotsquare|ldots)")


def normalize_ocr_text(
    text: str,
    *,
    trace_id: str = "",
    enabled_strategies: TypedSet[str] | None = None,
    extra_watermark_patterns: list | None = None,
) -> str:
    """OCR 文本标准化 — 全管线统一入口。

    合并了 ocr_service.clean_ocr_text() 和 ImportTextNormalizer 的所有清洗规则。
    enabled_strategies 控制可选策略（None = 全部启用）：
      - space_newline  — 换行合并、空格规范化
      - digit_letter   — OCR 数字/字母混淆修正、罗马数字修复
      - math_formula   — 数学公式标准化
      - punctuation    — 全角/半角标点规范化
    水印/页码/乱码/指针箭头/LaTeX/代码围栏始终启用，不受策略控制。
    """
    if not text:
        return ""

    def _strategy_on(name: str) -> bool:
        return enabled_strategies is None or name in enabled_strategies

    # ---- Step 0: 代码块围栏保护（必须最早，基于原始文本） ----
    from app.features.code_detector import wrap_code_fences
    text = wrap_code_fences(text, trace_id=trace_id)

    # ---- Step 1: 水印/页码/章标题/噪声行过滤（行级，需在合并前执行） ----
    text = _filter_lines(text, extra_watermark_patterns)

    # ---- Step 2: 乱码字符移除 ----
    text = _RE_GARBLED.sub("", text)
    text = text.replace("\xa0", " ")   # nbsp→space 必须在白名单前执行
    # 追加 Unicode 范围白名单过滤（保留 CJK / ASCII / 希腊 / 数学符号 / 圈号数字）
    text = re.sub(r"[^一-鿿　-〿＀-￯ -~Ͱ-Ͽ∀-⋿\n①-⑳⑴-⒇]", "", text)

    # ---- Step 3: OCR 箭头乱码修正（已知 PaddleOCR 幻觉模式） ----
    text = _RE_POINTER_ARROW_GARBLED_KNOWN.sub(r"->", text)

    # ---- Step 4: 中文断行合并 + 答案行格式修正 ----
    text = re.sub(
        r"([一-鿿，。；：！？])\n(?!((?:参考|正确)?\s*答案|解析|解答)\b)([一-鿿])",
        r"\1\3",
        text,
    )
    text = re.sub(
        r"(?<!\n)(?=(?:【)?(?:参考|正确)?答案(?:】)?\s*[：:])",
        "\n",
        text,
    )
    text = re.sub(r"\n((?:参考|正确)?)\n(答案\s*[：:])", r"\n\1\2", text)

    # ---- Step 5: 换行合并（上下文感知，保留结构行边界） ----
    if _strategy_on("space_newline"):
        text = _merge_ocr_newlines(text)
        text = re.sub(r"\n{3,}", "\n\n", text)

    # ---- Step 6: 空格规范化 ----
    if _strategy_on("space_newline"):
        text = text.replace("　", " ")   # 全角空格 → 半角
        text = text.replace("\xa0", " ")      # 非断空格 → 半角
        parts = re.split(r"(```[\s\S]*?```)", text)
        text = "".join(
            part if part.startswith("```") else re.sub(r" {2,}", " ", part)
            for part in parts
        )

    # ---- Step 7: OCR 数字/字母混淆修正 ----
    if _strategy_on("digit_letter"):
        text = _fix_roman_numeral_duplicates(text)
        lines = text.split("\n")
        has_roman = _has_roman_subitem_list(text)
        corrected: list[str] = []
        for line in lines:
            line = _fix_option_line(line)
            line = _fix_question_number_line(line, has_roman)
            line = _fix_option_roman_digit_confusion(line, has_roman)
            corrected.append(line)
        text = "\n".join(corrected)

    # ---- Step 8: C 指针箭头修复（3-pass） ----
    if ">" in text or "<-" in text:
        text = _RE_POINTER_ARROW_REVERSED.sub(r"\1->", text)
        text = _RE_POINTER_ARROW.sub(r"\1->", text)

    # ---- Step 9: LaTeX 命令标记清理 ----
    text = _RE_LATEX_CDOTS.sub("···", text)
    text = _RE_LATEX_DOTS.sub("...", text)

    # ---- Step 10: LaTeX 符号还原（编程上下文中的 OCR 误识） ----
    text = _fix_latex_substitutions(text)

    # ---- Step 11: 数学公式标准化 ----
    if _strategy_on("math_formula"):
        from app.services.formula_normalizer import fix_ocr_formula
        text = fix_ocr_formula(text)
        # 数学公式标准化可能产生新 LaTeX（如 α→\alpha），重新清理
        text = _fix_latex_substitutions(text)

    # ---- Step 12: 标点符号规范化 ----
    if _strategy_on("punctuation"):
        text = _normalize_punctuation(text)

    # ---- Step 13: 行尾空格清理，收尾 ----
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)
    return text.strip()


# ---------------------------------------------------------------------------
# normalize_ocr_text 内部辅助函数
# ---------------------------------------------------------------------------


def _filter_lines(text: str, extra_watermark_patterns: list | None = None) -> str:
    """单 pass 行过滤：水印、页码、章标题、低信息量噪声。

    保留代码围栏（```）内的所有内容。
    """
    lines = text.split("\n")
    result: list[str] = []
    in_fence = False
    for line in lines:
        stripped = line.strip()

        # 围栏边界
        if stripped.startswith("```"):
            result.append(line)
            in_fence = not in_fence
            continue
        if in_fence:
            result.append(line)
            continue
        if not stripped:
            result.append(line)
            continue

        # 水印关键词
        if _RE_WATERMARK.match(stripped):
            continue
        # 额外水印规则
        if extra_watermark_patterns and any(pat.search(stripped) for pat in extra_watermark_patterns):
            continue
        # 页码
        if _RE_PAGE_NUMBER.match(stripped) and 1 <= int(stripped) <= 500:
            continue
        # 纯章标题行（无题目内容跟随）
        ch_match = _RE_CHAPTER_HEADER.match(stripped)
        if ch_match and not _RE_QUESTION_SIGNAL.search(stripped[ch_match.end():]):
            continue
        # 选项/圈号标记行不按噪声处理
        if _RE_OPTION_MARKER.match(stripped):
            result.append(line)
            continue
        if _RE_CIRCLED_GROUP_MARKER.match(stripped):
            result.append(line)
            continue
        # OCR 箭头乱码残留
        if _RE_POINTER_ARROW_GARBLED_KNOWN.search(stripped):
            cleaned = _RE_POINTER_ARROW_GARBLED_KNOWN.sub("", stripped)
            if sum(1 for c in cleaned if c.isalpha()) < 3:
                continue
        # 短文本噪声检测
        has_cjk = any("一" <= c <= "鿿" for c in stripped)
        if len(stripped) <= _SHORT_NOISE_CHAR_LIMIT:
            if has_cjk:
                result.append(line)
                continue
            cjk_alpha = sum(1 for c in stripped if c.isalpha())
            if cjk_alpha / max(len(stripped), 1) < 0.5:
                continue
            result.append(line)
            continue
        # 长文本无 CJK + 随机大小写跳变
        if not has_cjk:
            alpha_chars = [c for c in stripped if c.isalpha()]
            if len(alpha_chars) < 4:
                continue
            case_switches = sum(
                1 for i in range(1, len(alpha_chars))
                if alpha_chars[i].islower() != alpha_chars[i - 1].islower()
            )
            if case_switches / max(len(alpha_chars), 1) > _LOW_INFO_CASE_SWITCH_RATIO:
                continue
        result.append(line)
    return "\n".join(result)


def _split_inline_option_sequence(text: str) -> str:
    def split_line(line: str) -> str:
        matches = list(_INLINE_OPTION_MARKER.finditer(line))
        if len(matches) < 2:
            return line
        keys = [m.group(1).upper() for m in matches]
        if not any(ord(keys[i + 1]) == ord(keys[i]) + 1 for i in range(len(keys) - 1)):
            return line
        for match in reversed(matches):
            if match.start() > 0 and line[match.start() - 1] != "\n":
                line = line[:match.start()] + "\n" + line[match.start():]
        return line
    return "\n".join(split_line(line) for line in text.split("\n"))


def _merge_ocr_newlines(text: str) -> str:
    """合并 OCR 断行，但保留结构行边界（题号/选项/答案/解析/罗马子项等）。"""
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = _split_inline_option_sequence(text)

    def _merge_sep(prev: str, curr: str) -> str:
        if not prev:
            return ""
        last_char = prev[-1]
        if "一" <= last_char <= "鿿" or "㐀" <= last_char <= "䶿":
            return ""
        if "豈" <= last_char <= "﫿":
            return ""
        return " "

    lines = text.split("\n")
    result: list[str] = []
    in_fence = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            result.append(line.rstrip())
            in_fence = not in_fence
            continue
        if in_fence:
            result.append(line.rstrip())
            continue
        if not stripped:
            result.append("")
            continue
        if not result or result[-1] == "":
            result.append(stripped)
        elif _RE_STRUCTURE_LINE.match(stripped):
            result.append(stripped)
        elif _RE_PREV_STRUCTURE_LINE.match(result[-1]):
            result.append(stripped)
        elif result[-1][-1] in _SENTENCE_END:
            result.append(stripped)
        else:
            sep = _merge_sep(result[-1], stripped)
            result[-1] += sep + stripped
    merged = "\n".join(result)
    return re.sub(r"\n{3,}", "\n\n", merged)


def _fix_roman_numeral_duplicates(text: str) -> str:
    """修复 OCR 将 III. 误识为 II. 造成的罗马数字序列断裂。"""
    if not text:
        return text
    lines = text.split("\n")
    roman_entries: list[dict] = []
    for i, line in enumerate(lines):
        m = _RE_ROMAN_SUBITEM_MARKER.match(line.lstrip())
        if not m:
            continue
        token_m = re.match(_ROMAN_SUBITEM_TOKEN, m.group(0))
        if not token_m:
            continue
        token = token_m.group(0)
        value = _ROMAN_TO_VALUE.get(token)
        if not value:
            continue
        start = line.index(m.group(0))
        roman_entries.append({
            "line_idx": i, "token": token, "value": value,
            "start": start, "end": start + len(m.group(0)),
            "match": m.group(0),
        })
    if len(roman_entries) < 2:
        return text
    for j in range(1, len(roman_entries)):
        prev = roman_entries[j - 1]
        curr = roman_entries[j]
        if curr["value"] == prev["value"]:
            expected = prev["value"] + 1
            new_token = _VALUE_TO_ROMAN.get(expected)
            if new_token and new_token != curr["token"]:
                new_match = curr["match"].replace(curr["token"], new_token, 1)
                li = curr["line_idx"]
                lines[li] = lines[li][:curr["start"]] + new_match + lines[li][curr["end"]:]
                curr["token"] = new_token
                curr["value"] = expected
                curr["match"] = new_match
                curr["end"] = curr["start"] + len(new_match)
    return "\n".join(lines)


def _has_roman_subitem_list(text: str) -> bool:
    markers = _RE_ROMAN_SUBITEM_MARKER.findall(text)
    if len(markers) < 2:
        return False
    distinct = {
        re.match(_ROMAN_SUBITEM_TOKEN, m).group(0)
        for m in markers
        if re.match(_ROMAN_SUBITEM_TOKEN, m)
    }
    return len(distinct) >= 2


def _fix_option_line(line: str) -> str:
    """修复选项行 OCR 错误：8/６→B, 0/O/o/Ｏ→D。"""
    m = re.match(r"^([8６6])\s*([.、:：）])", line)
    if m:
        return "B" + m.group(2) + line[m.end():]
    m = re.match(r"^([0OoＯ])\s*([.、:：）])(?!.*[A-Ha-h]\s*[.、:：）])", line)
    if m:
        return "D" + m.group(2) + line[m.end():]
    return line


def _fix_question_number_line(line: str, has_roman_list: bool = False) -> str:
    """修复题号行 OCR 错误：O/o→0, l/I→1。"""
    m = re.match(r"^(\d+)\s*([.、)）])\s*[Oo](?=\s)", line)
    if m:
        return f"{m.group(1)}{m.group(2)} 0{line[m.end() + 1:]}"
    m = re.match(r"^(l)\s*([.、)）])\s*", line)
    if m:
        return f"1{m.group(2)} {line[m.end():]}"
    if not has_roman_list:
        m = re.match(r"^(I)\s*([.、)）])\s*", line)
        if m:
            return f"1{m.group(2)} {line[m.end():]}"
    return line


def _fix_option_roman_digit_confusion(line: str, has_roman_list: bool) -> str:
    """修复选项文本中数字 1 与罗马数字 I 的 OCR 混淆。"""
    if not has_roman_list:
        return line
    m = re.match(r"^([A-D])\s*[.、:：）]\s*(1\s*[、,]\s*" + _ROMAN_SUBITEM_TOKEN + r")", line)
    if m:
        prefix = m.group(1)
        content = m.group(2)
        fixed_content = re.sub(r"^1\s*([、,])", r"I\1", content)
        return f"{prefix}. {fixed_content}{line[m.end():]}"
    return line


def _fix_latex_substitutions(text: str) -> str:
    """行级：仅在含编程信号的行内还原 OCR 误识的 LaTeX 符号。"""
    if not text or "\\" not in text:
        return text
    _re_latex_greek = re.compile(r"\$?\\" r"(alpha|beta|gamma|delta|theta|lambda)" r"\$?")
    _map = {"alpha": "a", "beta": "B", "gamma": "r", "delta": "d", "theta": "0", "lambda": "l"}
    _signals = (
        "->", "next", "prior", "链表", "结点", "节点", "指针",
        "数组", "栈", "队列", "NULL", "malloc", "struct",
        "单链表", "双链表", "循环链表", "头插法", "前驱", "后继",
    )
    lines = text.split("\n")
    result: list[str] = []
    for line in lines:
        if any(sig in line for sig in _signals):
            result.append(_re_latex_greek.sub(lambda m: _map.get(m.group(1), m.group(0)), line))
        else:
            result.append(line)
    return "\n".join(result)


def _normalize_punctuation(text: str) -> str:
    """标点符号规范化：全角 ASCII → 半角，中文后跟半角 → 中文标点。"""
    if not text:
        return text
    _RE_FULLWIDTH_ASCII = re.compile(r"[！-～]")
    _RE_CJK_PUNCT = re.compile(r"([一-鿿])([,;!?])(?=\s*[一-鿿])")
    _circled_chars = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
    _re_circled_fw = re.compile(r"（(\s*[" + _circled_chars + r"]\s*)）")

    stash: dict[str, str] = {}

    def _stash_circled(m: re.Match) -> str:
        key = f"\x00C{len(stash)}\x00"
        stash[key] = m.group(0)
        return key
    text = _re_circled_fw.sub(_stash_circled, text)

    def _to_halfwidth(m: re.Match) -> str:
        ch = m.group(0)
        code = ord(ch) - 0xfee0
        return chr(code) if 0x21 <= code <= 0x7e else ch
    text = _RE_FULLWIDTH_ASCII.sub(_to_halfwidth, text)

    for key, original in stash.items():
        text = text.replace(key, original)

    text = _RE_CJK_PUNCT.sub(
        lambda m: m.group(1) + {",": "，", ";": "；", "!": "！", "?": "？"}.get(m.group(2), m.group(2)),
        text,
    )
    text = text.replace("'", "'").replace("'", "'")
    return text


class ImportTextNormalizer:
    """导入文本标准化器 — 纯规则实现。

    enabled_strategies: 启用的策略名称集合。
        None = 全部启用（向后兼容）。
        可用的策略名: space_newline, digit_letter, math_formula, punctuation
    """

    def __init__(
        self,
        extra_watermark_patterns: list | None = None,
        enabled_strategies: TypedSet[str] | None = None,
    ):
        self._extra_watermark_patterns = extra_watermark_patterns or []
        self._enabled_strategies = enabled_strategies

    def _strategy_enabled(self, name: str) -> bool:
        """检查某策略是否启用。None = 全部启用。"""
        if self._enabled_strategies is None:
            return True
        return name in self._enabled_strategies

    def normalize(self, raw_blocks: list[dict]) -> list[dict]:
        """标准化文本块，返回 normalized_blocks。

        委托给 normalize_ocr_text() —— 全管线统一的 OCR 文本清洗入口。
        """
        normalized = []
        for i, block in enumerate(raw_blocks):
            text = block.get("text", "")
            cleaned = normalize_ocr_text(
                text,
                enabled_strategies=self._enabled_strategies,
                extra_watermark_patterns=self._extra_watermark_patterns,
            )
            out = {
                "page": block.get("page", 1),
                "block_index": block.get("block_index", i),
                "raw_text": text,
                "normalized_text": cleaned,
            }
            if "boxes" in block:
                out["boxes"] = block["boxes"]
            if "page_width" in block:
                out["page_width"] = block["page_width"]
            if "page_height" in block:
                out["page_height"] = block["page_height"]
            normalized.append(out)
        return normalized

    # ---------------------------------------------------------------
    # 换行清洗
    # ---------------------------------------------------------------

    def _clean_newlines(self, text: str) -> str:
        """清洗换行：OCR 断行合并，多余换行压缩。"""
        if not text:
            return text

        # 先压缩 3+ 连续换行 → 2 换行
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = self._split_inline_option_sequence(text)

        lines = text.split("\n")
        result: list[str] = []
        in_code_fence = False

        for line in lines:
            stripped = line.strip()

            if stripped.startswith("```"):
                result.append(line.rstrip())
                in_code_fence = not in_code_fence
                continue

            if in_code_fence:
                result.append(line.rstrip())
                continue

            if not stripped:
                result.append("")
                continue

            if not result or result[-1] == "":
                result.append(stripped)
            elif self._should_merge_lines(result[-1], stripped):
                sep = self._merge_separator(result[-1], stripped)
                result[-1] += sep + stripped
            else:
                result.append(stripped)

        merged = "\n".join(result)
        # 再次压缩因合并产生的多余空行
        merged = re.sub(r"\n{3,}", "\n\n", merged)
        return merged.strip()

    def _split_inline_option_sequence(self, text: str) -> str:
        def split_line(line: str) -> str:
            matches = list(_INLINE_OPTION_MARKER.finditer(line))
            if len(matches) < 2:
                return line
            keys = [m.group(1).upper() for m in matches]
            if not any(ord(keys[i + 1]) == ord(keys[i]) + 1 for i in range(len(keys) - 1)):
                return line
            for match in reversed(matches):
                if match.start() > 0 and line[match.start() - 1] != "\n":
                    line = line[:match.start()] + "\n" + line[match.start():]
            return line

        return "\n".join(split_line(line) for line in text.split("\n"))

    def _merge_separator(self, prev: str, curr: str) -> str:
        """返回两行合并时使用的分隔符：CJK 末尾不插空格，否则插空格。"""
        if not prev:
            return ""
        last_char = prev[-1]
        # CJK 字符范围（含标点）
        if "一" <= last_char <= "鿿" or "㐀" <= last_char <= "䶿":
            return ""
        if "豈" <= last_char <= "﫿":
            return ""
        return " "

    def _should_merge_lines(self, prev: str, curr: str) -> bool:
        """判断当前行是否应合并到上一行（OCR 断行检测）。"""
        if not prev or not curr:
            return False
        if _RE_STRUCTURE_LINE.match(curr):
            return False
        if _RE_PREV_STRUCTURE_LINE.match(prev):
            return False
        if prev[-1] in _SENTENCE_END:
            return False
        return True

    # ---------------------------------------------------------------
    # 乱码清洗
    # ---------------------------------------------------------------

    def _clean_garbled(self, text: str) -> str:
        """清洗乱码：不可见字符、Unicode 替换字符、OCR 乱码模式。"""
        if not text:
            return text
        # 移除不可见字符（保留 \n \t）和乱码字符
        text = _RE_GARBLED.sub("", text)
        return text

    # ---------------------------------------------------------------
    # 空格统一
    # ---------------------------------------------------------------

    def _normalize_spaces(self, text: str) -> str:
        """统一空格：全角→半角，连续空格合并。"""
        if not text:
            return text
        text = text.replace("　", " ")   # 全角空格 → 半角
        text = text.replace("\xa0", " ")     # 非断空格 → 半角
        parts = re.split(r"(```[\s\S]*?```)", text)
        return "".join(
            part if part.startswith("```") else re.sub(r" {2,}", " ", part)
            for part in parts
        )

    # ---------------------------------------------------------------
    # OCR 字符纠正
    # ---------------------------------------------------------------

    def _correct_ocr_errors(self, text: str) -> str:
        """OCR 字符纠正：数字/字母常见混淆，上下文感知。"""
        if not text:
            return text

        # Pre-process: fix Roman numeral duplicates before line-by-line correction
        text = self._fix_roman_numeral_duplicates(text)

        lines = text.split("\n")
        has_roman_list = self._has_roman_subitem_list(text)
        corrected: list[str] = []

        for line in lines:
            line = self._fix_option_line(line)
            line = self._fix_question_number_line(line, has_roman_list)
            line = self._fix_option_roman_digit_confusion(line, has_roman_list)
            corrected.append(line)

        return "\n".join(corrected)

    def _has_roman_subitem_list(self, text: str) -> bool:
        """检测文本中是否存在 ASCII 罗马数字子项列表（I./II./III. ...）。

        命中条件：出现至少 2 个不同的罗马标记（如 I. 和 II.）。这种枚举几乎
        只出现在「下列说法正确的是」类多选子项中，此时行首的 ``I.`` 是子项而非
        OCR 误识的题号 ``1.``，不应被 _fix_question_number_line 改写。
        """
        markers = _RE_ROMAN_SUBITEM_MARKER.findall(text)
        if len(markers) < 2:
            return False
        # 提取标记字符（去掉尾部分隔符），确认至少两种不同罗马数字
        distinct = {
            re.match(_ROMAN_SUBITEM_TOKEN, m).group(0)
            for m in markers
            if re.match(_ROMAN_SUBITEM_TOKEN, m)
        }
        return len(distinct) >= 2

    def _fix_option_line(self, line: str) -> str:
        """修复选项行 OCR 错误：8/６→B, 6→B, 0/O/o/Ｏ→D。

        Primary OCR option-marker correction. question_splitter._OCR_OPTION_MAP
        provides a defense-in-depth secondary pass for edge cases surviving
        this normalization.
        """
        # 匹配行首的选项标记（A-D 范围，含常见 OCR 混淆）
        m = re.match(r"^([8６6])\s*([.、:：）])", line)
        if m:
            return "B" + m.group(2) + line[m.end():]

        m = re.match(r"^([0OoＯ])\s*([.、:：）])(?!.*[A-Ha-h]\s*[.、:：）])", line)
        if m:
            return "D" + m.group(2) + line[m.end():]

        return line

    def _fix_question_number_line(self, line: str, has_roman_list: bool = False) -> str:
        """修复题号行 OCR 错误：O/o→0, l/I→1。

        当 ``has_roman_list`` 为真（文本含 I./II./III. 罗马子项枚举）时，行首大写
        ``I.`` 是多选子项标记而非误识题号，跳过 I→1 改写，避免把一道多选题
        撕成两题（参见 docs/BUGS.md 案例一/二/五/六）。小写 ``l.`` 仍始终纠正，
        因为罗马数字不会用小写 l。
        """
        # 匹配题号模式：数字后的混淆字符
        # 例："1.O" → "1.0", "2,0" → "2.0"
        m = re.match(r"^(\d+)\s*([.、)）])\s*[Oo](?=\s)", line)
        if m:
            return f"{m.group(1)}{m.group(2)} 0{line[m.end() + 1:]}"

        # 小写 "l." → "1." 题号（罗马数字不用小写 l，始终纠正）
        m = re.match(r"^(l)\s*([.、)）])\s*", line)
        if m:
            return f"1{m.group(2)} {line[m.end():]}"

        # 大写 "I." → "1." 题号：仅当不在罗马子项列表上下文中才纠正
        if not has_roman_list:
            m = re.match(r"^(I)\s*([.、)）])\s*", line)
            if m:
                return f"1{m.group(2)} {line[m.end():]}"

        return line

    def _fix_option_roman_digit_confusion(self, line: str, has_roman_list: bool) -> str:
        """修复选项文本中数字 1 与罗马数字 I 的 OCR 混淆。

        当题干含罗马子项枚举时，选项内容中的 "1、" → "I、"，
        如 "A. 1、I" → "A. I、I"（OCR 将 I、II 误识为 1、I）。
        """
        if not has_roman_list:
            return line
        m = re.match(r"^([A-D])\s*[.、:：）]\s*(1\s*[、,]\s*" + _ROMAN_SUBITEM_TOKEN + r")", line)
        if m:
            prefix = m.group(1)
            content = m.group(2)
            fixed_content = re.sub(r"^1\s*([、,])", r"I\1", content)
            return f"{prefix}. {fixed_content}{line[m.end():]}"
        return line

    def _fix_roman_numeral_duplicates(self, text: str) -> str:
        """修复 OCR 将 III. 误识为 II. 造成的罗马数字序列断裂。

        仅检测行首罗马枚举标记（I./II./III.），修复已知 OCR 误识模式（III→II）。
        选项内的罗马数字引用（如 A. I、II）不参与序列校验。
        """
        if not text:
            return text

        lines = text.split("\n")
        roman_entries: list[dict] = []  # {line_idx, token, value, start, end}

        for i, line in enumerate(lines):
            m = _RE_ROMAN_SUBITEM_MARKER.match(line.lstrip())
            if not m:
                continue
            token_m = re.match(_ROMAN_SUBITEM_TOKEN, m.group(0))
            if not token_m:
                continue
            token = token_m.group(0)
            value = _ROMAN_TO_VALUE.get(token)
            if not value:
                continue
            # start/end positions in the original line
            start = line.index(m.group(0))
            roman_entries.append({
                "line_idx": i, "token": token, "value": value,
                "start": start, "end": start + len(m.group(0)),
                "match": m.group(0),
            })

        if len(roman_entries) < 2:
            return text

        for j in range(1, len(roman_entries)):
            prev = roman_entries[j - 1]
            curr = roman_entries[j]
            # Skip if values are on different lines but both are option lines —
            # those are independent references, not a sequence
            if curr["value"] == prev["value"]:
                expected = prev["value"] + 1
                new_token = _VALUE_TO_ROMAN.get(expected)
                if new_token and new_token != curr["token"]:
                    new_match = curr["match"].replace(curr["token"], new_token, 1)
                    li = curr["line_idx"]
                    lines[li] = lines[li][:curr["start"]] + new_match + lines[li][curr["end"]:]
                    curr["token"] = new_token
                    curr["value"] = expected
                    curr["match"] = new_match
                    curr["end"] = curr["start"] + len(new_match)

        return "\n".join(lines)

    def _fix_pointer_arrows(self, text: str) -> str:
        """修复 C 指针箭头 OCR 伪影： "p − >next" / "p - >next" → "p->next"。

        PaddleOCR 常把 "->" 拆成「减号/破折号 + 空格 + 大于号」，链表代码因此不可读。
        仅在 ">" 后紧跟标识符字符时纠正（数学式 "a − > b" 因 > 后有空格不命中），
        规则幂等。连续箭头（p->next->prev）逐个命中，正则全局替换即可。

        同时修复 PaddleOCR 对特定字体/排版将 -> 误识为 <- + 随机字母前缀的已知问题。
        """
        if not text:
            return text
        # Pass 1: 已知 OCR 幻觉模式 xau<- / axau<- / xeu<- → ->
        text = _RE_POINTER_ARROW_GARBLED_KNOWN.sub(r"->", text)
        # Pass 2: 通用箭头方向修复 identifier<- → identifier->
        text = _RE_POINTER_ARROW_REVERSED.sub(r"\1->", text)
        # Pass 3: 破折号+空格+> 修复（原有逻辑）
        if ">" in text:
            text = _RE_POINTER_ARROW.sub(r"\1->", text)
        return text

    # ---------------------------------------------------------------
    # LaTeX 标记清洗
    # ---------------------------------------------------------------

    _RE_LATEX_DOTS = re.compile(r"\\l(?:dots|dotsquare|ldots)")
    _RE_LATEX_CDOTS = re.compile(r"\\c(dots|dotsquare|ldots)")

    def _clean_latex_markers(self, text: str) -> str:
        """清理 OCR 保留的 LaTeX 命令标记。

        OCR 有时直接保留 LaTeX 源码（如 ``\\ldots``、``\\cdots``），
        未渲染为实际符号。将它们转为可读的纯文本。
        """
        if not text or "\\" not in text:
            return text
        text = self._RE_LATEX_CDOTS.sub("···", text)
        text = self._RE_LATEX_DOTS.sub("...", text)
        return text

    # ---------------------------------------------------------------
    # LaTeX 符号还原 — 编程上下文中的 OCR 误识（行级作用域）
    # ---------------------------------------------------------------

    # OCR 视觉误识逆向映射表
    # 这不是希腊字母到拉丁字母的语义映射，而是 OCR 视觉错误的修复：
    # OCR 看到拉丁字母，输出 LaTeX 希腊符号。此表将这些误识产物还原。
    # 例如 gamma→r 是因为 OCR 视觉上 γ 像 r，不代表希腊语义（γ=g）
    _OCR_LATEX_REVERSION_MAP = {
        "alpha": "a",   # OCR 视觉: a/q → \alpha
        "beta": "B",    # OCR 视觉: B → \beta
        "gamma": "r",   # OCR 视觉: r → \gamma（视觉误识，非希腊语义映射）
        "delta": "d",   # OCR 视觉: d → \delta
        "theta": "0",   # OCR 视觉: 0 → \theta
        "lambda": "l",  # OCR 视觉: l → \lambda
    }

    _PROG_CONTEXT_SIGNALS = (
        "->", "next", "prior", "链表", "结点", "节点", "指针",
        "数组", "栈", "队列", "NULL", "malloc", "struct",
        "单链表", "双链表", "循环链表", "头插法", "前驱", "后继",
    )

    _RE_LATEX_GREEK_SINGLE = re.compile(
        r"\$?\\" r"(alpha|beta|gamma|delta|theta|lambda)" r"\$?"
    )

    def _fix_latex_substitutions(self, text: str) -> str:
        """行级作用域：仅在含编程信号的「行」内还原 OCR 误识的 LaTeX 符号。

        OCR 常把 ``q``/``a`` 误识为 ``\\alpha``，``B`` 误识为 ``\\beta`` 等。
        改为逐行判断上下文，避免跨区域污染：
        - ``链表 p->next = \\alpha`` → 该行含编程信号，允许替换
        - ``设\\alpha+\\beta=1`` → 无编程信号，保留 LaTeX 不动
        """
        if not text:
            return text

        def _replace(m: re.Match) -> str:
            cmd = m.group(1)
            return self._OCR_LATEX_REVERSION_MAP.get(cmd, m.group(0))

        lines = text.split("\n")
        result: list[str] = []
        for line in lines:
            if any(sig in line for sig in self._PROG_CONTEXT_SIGNALS):
                result.append(self._RE_LATEX_GREEK_SINGLE.sub(_replace, line))
            else:
                result.append(line)
        return "\n".join(result)

    # ---------------------------------------------------------------
    # 标点符号规范化
    # ---------------------------------------------------------------

    _RE_FULLWIDTH_ASCII = re.compile(r"[！-～]")
    _RE_CJK_PUNCT = re.compile(r"([一-鿿])([,;!?])(?=\s*[一-鿿])")

    _RE_CIRCLED_FW_PAREN = re.compile(
        r"（(\s*[" + _CIRCLED_OPTION_CHARS + r"]\s*)）"
    )

    def _normalize_punctuation(self, text: str) -> str:
        """标点符号规范化：统一中英文标点。

        1. 全角 ASCII → 半角（保留中文全角标点）
        2. 中文语境下半角逗号/分号/感叹号/问号 → 中文标点
        """
        if not text:
            return text

        # 保护全角括号包围的圈号占位符（如 （①）），避免被转为半角
        stash: dict[str, str] = {}
        def _stash_circled(m: re.Match) -> str:
            key = f"\x00C{len(stash)}\x00"
            stash[key] = m.group(0)
            return key
        text = self._RE_CIRCLED_FW_PAREN.sub(_stash_circled, text)

        # 全角 ASCII 转半角（! " # $ % & ' ( ) * + , - . / : ; < = > ? @ [ \ ] ^ _ ` { | } ~）
        def _to_halfwidth(m: re.Match) -> str:
            ch = m.group(0)
            code = ord(ch) - 0xfee0
            return chr(code) if 0x21 <= code <= 0x7e else ch

        text = self._RE_FULLWIDTH_ASCII.sub(_to_halfwidth, text)

        # 恢复圈号占位符
        for key, original in stash.items():
            text = text.replace(key, original)

        # 中文后跟半角逗号/分号/叹号/问号 → 中文标点
        text = self._RE_CJK_PUNCT.sub(
            lambda m: m.group(1) + {
                ",": "，", ";": "；", "!": "！", "?": "？",
            }.get(m.group(2), m.group(2)),
            text,
        )

        # 连续中文引号配对统一
        text = text.replace("'", "'").replace("'", "'")
        return text

    # ---------------------------------------------------------------
    # 水印/页码过滤
    # ---------------------------------------------------------------

    def _filter_watermark_text(self, text: str) -> str:
        """过滤水印行：关键词匹配 + 低信息量短文本检测 + 自定义规则。"""
        if not text:
            return text
        lines = text.split("\n")
        filtered: list[str] = []
        in_code_fence = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("```"):
                filtered.append(line)
                in_code_fence = not in_code_fence
                continue
            if in_code_fence:
                filtered.append(line)
                continue
            if not stripped:
                filtered.append(line)
                continue
            if _RE_WATERMARK.match(stripped):
                continue
            if self._is_low_info_noise(stripped):
                continue
            if self._match_extra_watermark(stripped):
                continue
            # 章标题行：仅当后续无题目特征时才过滤（避免误删合并行）
            ch_match = _RE_CHAPTER_HEADER.match(stripped)
            if ch_match and not _RE_QUESTION_SIGNAL.search(stripped[ch_match.end():]):
                continue
            filtered.append(line)
        return "\n".join(filtered)

    def _match_extra_watermark(self, text: str) -> bool:
        """检查是否匹配自定义水印规则。"""
        for pat in self._extra_watermark_patterns:
            if pat.search(text):
                return True
        return False

    def _is_low_info_noise(self, text: str) -> bool:
        """检测低信息量噪声：随机字符占比过高或结构异常的文本。

        针对多种噪声模式：
        1. OCR 箭头乱码残留（xau<-, axau<- 等独立出现）
        2. 短文本（≤6 字符）无 CJK 且非纯字母
        3. 长文本（>6 字符）无 CJK 且存在随机大小写跳变特征
        """
        if _RE_OPTION_MARKER.match(text):
            return False
        if _RE_CIRCLED_GROUP_MARKER.match(text):
            return False

        # OCR 箭头乱码残留：独立出现的 xau<- / axau<- 等无上下文噪声
        if _RE_POINTER_ARROW_GARBLED_KNOWN.search(text):
            # 只过滤独立出现的情况（整个文本就是乱码或主要成分是乱码）
            cleaned = _RE_POINTER_ARROW_GARBLED_KNOWN.sub("", text)
            alpha_remaining = sum(1 for c in cleaned if c.isalpha())
            if alpha_remaining < 3:
                return True

        # 含 CJK 字符的文本不按噪声处理（中文内容有语义价值）
        has_cjk = any("一" <= c <= "鿿" for c in text)

        if len(text) <= _SHORT_NOISE_CHAR_LIMIT:
            if has_cjk:
                return False
            cjk_alpha = sum(1 for c in text if c.isalpha())
            return cjk_alpha / max(len(text), 1) < 0.5

        # 长文本无 CJK 且存在随机大小写跳变：检查大小写切换频率
        if not has_cjk:
            alpha_chars = [c for c in text if c.isalpha()]
            if len(alpha_chars) < 4:
                return True  # 几乎没有字母字符的纯符号文本
            # 统计大小写切换次数 — 正常英文/C 代码切换率较低
            case_switches = sum(
                1 for i in range(1, len(alpha_chars))
                if alpha_chars[i].islower() != alpha_chars[i - 1].islower()
            )
            switch_ratio = case_switches / max(len(alpha_chars), 1)
            # 随机水印文本大小写频繁切换（如 axuK, dayOOeB），
            # 正常英文单词和 C 标识符切换率通常 < 0.3
            if switch_ratio > _LOW_INFO_CASE_SWITCH_RATIO:
                return True

        return False

    def _filter_page_number(self, text: str) -> str:
        """过滤页码行：纯数字且在合理页码范围内。"""
        if not text:
            return text
        lines = text.split("\n")
        filtered: list[str] = []
        for line in lines:
            stripped = line.strip()
            if _RE_PAGE_NUMBER.match(stripped):
                num = int(stripped)
                if 1 <= num <= 500:
                    continue
            filtered.append(line)
        return "\n".join(filtered)
