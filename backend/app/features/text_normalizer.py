"""导入文本标准化层 — 纯规则文本清洗。

职责：清洗换行、乱码、空格、OCR 字符混淆。
不做 AI 分析、不做题目识别、不做答案匹配。
"""

import re


# Unicode 替换字符和常见 OCR 乱码
_RE_GARBLED = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]|�|□+"
)

_CIRCLED_OPTION_CHARS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_OPTION_NOISE_PREFIX = r"(?:[?？]|[" + _CIRCLED_OPTION_CHARS + r"])?\s*"
_OPTION_MARKER = _OPTION_NOISE_PREFIX + r"([A-Da-d])\s*[.．、:：)）]"
_INLINE_OPTION_MARKER = re.compile(r"(?<![A-Za-z0-9])" + _OPTION_MARKER)

# 题号行：用于 OCR 字符纠正的上下文判断
_RE_QUESTION_NUMBER = re.compile(
    r"^\s*\d+\s*[.、)）]"
)

# 行首选项标记（用于 OCR 纠正上下文）
_RE_OPTION_LINE = re.compile(
    r"^[A-Da-d8６0Oo]\s*[.、:：）]"
)

# 结构标记行：不应被合并到上行的模式
_RE_STRUCTURE_LINE = re.compile(
    r"^("
    r"\d+\s*[.、)）]"
    r"|" + _OPTION_MARKER +
    r"|[（(]\s*[A-D]\s*[）)]"
    r"|(?:【)?(?:参考|正确)?答案(?:】)?\s*[：:]"
    r"|(?:【)?(?:解析|解答|讲解|分析)(?:】)?\s*[：:]"
    r")"
)

# 上一行是完整结构行时，下一行默认不继续并入上一行
_RE_PREV_STRUCTURE_LINE = re.compile(
    r"^"
    r"(" + _OPTION_MARKER + r"\s*.{1,}"
    r"|[（(]\s*[A-Da-d]\s*[）)]\s*.{1,}"
    r"|(?:【)?(?:参考|正确)?答案(?:】)?\s*[：:]\s*.{1,}"
    r"|(?:【)?(?:解析|解答|讲解|分析)(?:】)?\s*[：:]\s*.{1,}"
    r")"
)

_SENTENCE_END = frozenset("。！？；…")

# 水印关键词模式（覆盖OCR识别出的各种变体）
_RE_WATERMARK = re.compile(
    r"^(王道|计算?机教育|机教育|算机教育|道计算|几教育|千道|全丰道|"
    r"王道计算机教育|道计算机|道计管教育|kaoya[no]?|Kaoyan|"
    r"w{0,3}\.?com|n\.com|ska|ai\.).*$"
)

# 页码模式：纯数字或带少量空格的1-3位数
_RE_PAGE_NUMBER = re.compile(r"^\s*\d{1,3}\s*$")


class ImportTextNormalizer:
    """导入文本标准化器 — 纯规则实现。"""

    def normalize(self, raw_blocks: list[dict]) -> list[dict]:
        """标准化文本块，返回 normalized_blocks。"""
        normalized = []
        for i, block in enumerate(raw_blocks):
            text = block.get("text", "")
            cleaned = text
            cleaned = self._filter_watermark_text(cleaned)
            cleaned = self._filter_page_number(cleaned)
            cleaned = self._clean_newlines(cleaned)
            cleaned = self._clean_garbled(cleaned)
            cleaned = self._normalize_spaces(cleaned)
            cleaned = self._correct_ocr_errors(cleaned)
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

        for line in lines:
            stripped = line.strip()

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
        text = re.sub(r" {2,}", " ", text)   # 连续空格 → 单空格
        return text

    # ---------------------------------------------------------------
    # OCR 字符纠正
    # ---------------------------------------------------------------

    def _correct_ocr_errors(self, text: str) -> str:
        """OCR 字符纠正：数字/字母常见混淆，上下文感知。"""
        if not text:
            return text

        lines = text.split("\n")
        corrected: list[str] = []

        for line in lines:
            line = self._fix_option_line(line)
            line = self._fix_question_number_line(line)
            corrected.append(line)

        return "\n".join(corrected)

    def _fix_option_line(self, line: str) -> str:
        """修复选项行 OCR 错误：8/６→B, 6→B, 0/O→D。"""
        # 匹配行首的选项标记（A-D 范围，含常见 OCR 混淆）
        m = re.match(r"^([8６6])\s*([.、:：）])", line)
        if m:
            return "B" + m.group(2) + line[m.end():]

        m = re.match(r"^([0Oo])\s*([.、:：）])(?!.*[A-Ha-h]\s*[.、:：）])", line)
        if m:
            return "D" + m.group(2) + line[m.end():]

        return line

    def _fix_question_number_line(self, line: str) -> str:
        """修复题号行 OCR 错误：O/o→0, l/I→1。"""
        # 匹配题号模式：数字后的混淆字符
        # 例："1.O" → "1.0", "2,0" → "2.0"
        m = re.match(r"^(\d+)\s*([.、)）])\s*[Oo](?=\s)", line)
        if m:
            return f"{m.group(1)}{m.group(2)} 0{line[m.end() + 1:]}"

        # "l." → "1." 题号
        m = re.match(r"^([lI])\s*([.、)）])\s*", line)
        if m:
            return f"1{m.group(2)} {line[m.end():]}"

        return line

    # ---------------------------------------------------------------
    # 水印/页码过滤
    # ---------------------------------------------------------------

    def _filter_watermark_text(self, text: str) -> str:
        """过滤水印行：关键词匹配 + 低信息量短文本检测。"""
        if not text:
            return text
        lines = text.split("\n")
        filtered: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                filtered.append(line)
                continue
            if _RE_WATERMARK.match(stripped):
                continue
            if self._is_low_info_noise(stripped):
                continue
            filtered.append(line)
        return "\n".join(filtered)

    def _is_low_info_noise(self, text: str) -> bool:
        """检测低信息量噪声：短文本中非中英文字符占比过高。"""
        if len(text) > 6:
            return False
        cjk_alpha = sum(
            1 for c in text
            if ("一" <= c <= "鿿") or c.isalpha()
        )
        return cjk_alpha / max(len(text), 1) < 0.5

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
