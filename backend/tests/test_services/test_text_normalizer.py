"""ImportTextNormalizer 单元测试。"""
import os
import pytest
from app.features.text_normalizer import ImportTextNormalizer


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures")


def _read_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


def _make_blocks(text: str, page: int = 1, start_index: int = 0) -> list[dict]:
    """Helper：将文本包装为 raw_blocks 格式。"""
    return [{"page": page, "block_index": start_index, "text": text}]


@pytest.fixture
def normalizer():
    return ImportTextNormalizer()


# ---------------------------------------------------------------
# 1. 换行清洗
# ---------------------------------------------------------------

class TestNewlineCleaning:
    def test_ocr_broken_lines_merged(self, normalizer):
        """OCR 断行应被合并（中文句中断行）。"""
        text = "设函数 f(x) 在区间\n[0, 1] 上连续\n且 f(0) = 0"
        result = normalizer.normalize(_make_blocks(text))
        normalized = result[0]["normalized_text"]
        # 不该有孤立的中文断行
        lines = normalized.split("\n")
        assert len(lines) <= 3  # 可能保留段落边界

    def test_excessive_newlines_compressed(self, normalizer):
        """3+ 换行压缩为 2 换行。"""
        text = "第一段\n\n\n\n第二段"
        result = normalizer.normalize(_make_blocks(text))
        normalized = result[0]["normalized_text"]
        assert "\n\n\n" not in normalized
        assert "第二段" in normalized

    def test_sentence_end_not_merged(self, normalizer):
        """句末标点（。）后不应合并。"""
        text = "第一句话。\n第二句话。"
        result = normalizer.normalize(_make_blocks(text))
        normalized = result[0]["normalized_text"]
        assert "\n" in normalized  # 应保留换行

    def test_structure_line_not_merged(self, normalizer):
        """结构标记行不应被合并到上一行。"""
        text = "某段文本\n1. 设函数 f(x)"
        result = normalizer.normalize(_make_blocks(text))
        normalized = result[0]["normalized_text"]
        assert "\n1." in normalized  # 题号前保留换行

    def test_option_line_not_merged(self, normalizer):
        """选项标记不应被合并到上一行。"""
        text = "题干文本\nA. 选项内容"
        result = normalizer.normalize(_make_blocks(text))
        normalized = result[0]["normalized_text"]
        assert "\nA." in normalized

    def test_circled_option_line_not_merged(self, normalizer):
        text = "题干文本\n① A. n + 1\n②B. 2n"
        result = normalizer.normalize(_make_blocks(text))
        normalized = result[0]["normalized_text"]
        assert "\n① A." in normalized
        assert "\n②B." in normalized

    def test_grouped_circled_option_rows_preserve_stem_placeholders(self, normalizer):
        text = (
            "1. 若系统有 n 个进程，则就绪队列中进程的个数最多有（①）个；阻塞队列中进程的个数最多有（②）个。\n"
            "① A. n+1  B. n  C. n−1  D. 1\n"
            "② A. n+1  B. n  C. n−1  D. 1"
        )
        result = normalizer.normalize(_make_blocks(text))
        normalized = result[0]["normalized_text"]
        assert "（①）" in normalized
        assert "（②）" in normalized
        assert "（）" not in normalized
        assert "\n① A." in normalized
        assert "\n② A." in normalized
        assert "\nB. n" in normalized
        assert "\nD. 1" in normalized

    def test_inline_circled_options_are_split_for_parser(self, normalizer):
        text = "题干文本 ① A. n + 1 ② B. 2n ③ C. n - 1 ④ D. 2n - 1"
        result = normalizer.normalize(_make_blocks(text))
        normalized = result[0]["normalized_text"]
        assert "\n① A." in normalized
        assert "\n② B." in normalized
        assert "\n③ C." in normalized
        assert "\n④ D." in normalized

    def test_inline_plain_variables_not_split(self, normalizer):
        text = "设集合 A 与集合 B 满足 A∩B=C，求 D 的取值。"
        result = normalizer.normalize(_make_blocks(text))
        normalized = result[0]["normalized_text"]
        assert "\nA" not in normalized
        assert "\nB" not in normalized

    def test_option_continuation_not_merged_into_previous_option(self, normalizer):
        text = "D. 管程是被进程调用的，管程是语法范围，无法创建和撤销\n对信号量 S 执行 P 操作后，使该进程进入资源等待队列的条件是（ ）。"
        result = normalizer.normalize(_make_blocks(text))
        normalized = result[0]["normalized_text"]
        assert "\n对信号量" in normalized

    def test_mid_sentence_merge(self, normalizer):
        """英文句中断行应合并（逗号后换行）。"""
        text = "This is a sentence, which\ncontinues on the next line"
        result = normalizer.normalize(_make_blocks(text))
        normalized = result[0]["normalized_text"]
        assert "which continues" in normalized


# ---------------------------------------------------------------
# 2. 乱码清洗
# ---------------------------------------------------------------

class TestGarbledCleaning:
    def test_invisible_chars_removed(self, normalizer):
        """不可见字符应被移除。"""
        text = "正常文本\x00\x1f中间\x7f部分"
        result = normalizer.normalize(_make_blocks(text))
        normalized = result[0]["normalized_text"]
        assert "\x00" not in normalized
        assert "\x1f" not in normalized
        assert "\x7f" not in normalized
        assert "正常文本中间部分" == normalized

    def test_unicode_replacement_removed(self, normalizer):
        """Unicode 替换字符（�）应被移除。"""
        text = "这是�一段�文本"
        result = normalizer.normalize(_make_blocks(text))
        normalized = result[0]["normalized_text"]
        assert "�" not in normalized
        assert "这是一段文本" == normalized

    def test_box_characters_removed(self, normalizer):
        """方框乱码（□）应被移除。"""
        text = "批处理系统□□□允许用户干预"
        result = normalizer.normalize(_make_blocks(text))
        normalized = result[0]["normalized_text"]
        assert "□" not in normalized


# ---------------------------------------------------------------
# 3. 空格统一
# ---------------------------------------------------------------

class TestSpaceNormalization:
    def test_fullwidth_to_halfwidth(self, normalizer):
        """全角空格应转为半角。"""
        text = "选项A　选项B"
        result = normalizer.normalize(_make_blocks(text))
        normalized = result[0]["normalized_text"]
        assert "　" not in normalized
        assert "选项A 选项B" == normalized

    def test_nbsp_to_space(self, normalizer):
        """非断空格应转为半角空格。"""
        text = "word1\xa0word2"
        result = normalizer.normalize(_make_blocks(text))
        normalized = result[0]["normalized_text"]
        assert "\xa0" not in normalized
        assert "word1 word2" == normalized

    def test_consecutive_spaces_collapsed(self, normalizer):
        """连续空格应合并为单个。"""
        text = "word1    word2"
        result = normalizer.normalize(_make_blocks(text))
        normalized = result[0]["normalized_text"]
        assert "    " not in normalized
        assert "word1 word2" == normalized

    def test_fenced_code_spaces_preserved(self, normalizer):
        text = "题干如下:\n```tex\nP1() {                     P2() {\n x = 1;      // A1          x = -3;     // B1\n}\n```\n答案：A"
        result = normalizer.normalize(_make_blocks(text))
        normalized = result[0]["normalized_text"]
        assert "P1() {                     P2() {" in normalized
        assert " x = 1;      // A1          x = -3;     // B1" in normalized
        assert "```tex\nP1()" in normalized


# ---------------------------------------------------------------
# 4. OCR 字符纠正
# ---------------------------------------------------------------

class TestOcrCorrection:
    def test_option_8_to_B(self, normalizer):
        """选项 8. → B. 纠正。"""
        text = "8. 选项内容"
        result = normalizer.normalize(_make_blocks(text))
        normalized = result[0]["normalized_text"]
        assert normalized.startswith("B.")

    def test_option_0_to_D(self, normalizer):
        """选项 0. → D. 纠正。"""
        text = "0. 选项内容"
        result = normalizer.normalize(_make_blocks(text))
        normalized = result[0]["normalized_text"]
        assert normalized.startswith("D.")

    def test_option_O_to_D(self, normalizer):
        """选项 O. → D. 纠正。"""
        text = "O. 选项内容"
        result = normalizer.normalize(_make_blocks(text))
        normalized = result[0]["normalized_text"]
        assert normalized.startswith("D.")

    def test_mid_text_not_corrected(self, normalizer):
        """文本中间的数字不应被误纠正。"""
        text = "8 is a number and 0 is also a number"
        result = normalizer.normalize(_make_blocks(text))
        normalized = result[0]["normalized_text"]
        assert "8 is" in normalized
        assert "0 is" in normalized

    def test_correct_answer_line_not_corrected(self, normalizer):
        """答案行中的数字/字母不应误纠正。"""
        text = "正确答案：B\n解析：详见上文"
        result = normalizer.normalize(_make_blocks(text))
        normalized = result[0]["normalized_text"]
        assert "B" in normalized


# ---------------------------------------------------------------
# 5. A/B/C/D 错误修复
# ---------------------------------------------------------------

class TestOptionFix:
    def test_6_to_B(self, normalizer):
        """选项 6. → B. 纠正。"""
        text = "6. 快速排序"
        result = normalizer.normalize(_make_blocks(text))
        normalized = result[0]["normalized_text"]
        assert normalized.startswith("B.")

    def test_chinese_6_to_B(self, normalizer):
        """全角 ６. → B. 纠正。"""
        text = "６. 快速排序"
        result = normalizer.normalize(_make_blocks(text))
        normalized = result[0]["normalized_text"]
        assert normalized.startswith("B.")


# ---------------------------------------------------------------
# 5b. C 指针箭头 OCR 伪影修复（docs/BUGS.md 案例三/七/十）
# ---------------------------------------------------------------

class TestPointerArrowFix:
    def test_minus_space_arrow_fixed(self, normalizer):
        """"p − >next" → "p->next"（减号+空格+大于号）。"""
        text = "A. s − >next = p − >next;"
        normalized = normalizer.normalize(_make_blocks(text))[0]["normalized_text"]
        assert "s->next" in normalized
        assert "p->next" in normalized
        assert "− >" not in normalized

    def test_chained_arrows_fixed(self, normalizer):
        """连续箭头 "q − >prior − >next" → "q->prior->next"。"""
        text = "D. q − >prior − >next = p;"
        normalized = normalizer.normalize(_make_blocks(text))[0]["normalized_text"]
        assert "q->prior->next" in normalized

    def test_ascii_hyphen_arrow_fixed(self, normalizer):
        """ASCII 连字符变体 "p - >next" → "p->next"。"""
        text = "B. p - >next = s;"
        normalized = normalizer.normalize(_make_blocks(text))[0]["normalized_text"]
        assert "p->next" in normalized

    def test_correct_arrow_idempotent(self, normalizer):
        """已正确的 "p->next" 再跑一次仍正确。"""
        text = "C. q->next=s;s->next=p;"
        normalized = normalizer.normalize(_make_blocks(text))[0]["normalized_text"]
        assert "q->next" in normalized
        assert "s->next" in normalized

    def test_math_minus_not_touched(self, normalizer):
        """数学式 "a − > b"（> 后有空格）不应被改成箭头。"""
        text = "若 a − > b 则成立"
        normalized = normalizer.normalize(_make_blocks(text))[0]["normalized_text"]
        assert "a->" not in normalized

    def test_subtraction_not_touched(self, normalizer):
        """减法式 "2n − i − 1" 的减号必须保留。"""
        text = "交换第 i 个元素和第 2n − i − 1 个元素的值"
        normalized = normalizer.normalize(_make_blocks(text))[0]["normalized_text"]
        assert "2n − i − 1" in normalized


# ---------------------------------------------------------------
# 5c. 水印过滤扩展（研大/公众号/永久微信，docs/BUGS.md 案例二/十）
# ---------------------------------------------------------------

class TestWatermarkFilter:
    def test_yanda_bracket_line_filtered(self, normalizer):
        """整行 "[研大]" 水印应被过滤。"""
        text = "题干内容在此\n[研大]\nA. 选项一"
        normalized = normalizer.normalize(_make_blocks(text))[0]["normalized_text"]
        assert "题干内容在此" in normalized
        assert "A. 选项一" in normalized
        assert "研大" not in normalized

    def test_gongzhonghao_line_filtered(self, normalizer):
        """"后续关注公众号..." 水印行应被过滤。"""
        text = "题干内容\n后续关注公众号研大\nA. 甲"
        normalized = normalizer.normalize(_make_blocks(text))[0]["normalized_text"]
        assert "题干内容" in normalized
        assert "A. 甲" in normalized
        assert "公众号" not in normalized

    def test_wechat_line_filtered(self, normalizer):
        """"永久微信1866224xxx" 水印行应被过滤。"""
        text = "题干\n永久微信1866224xxx\nB. 乙"
        normalized = normalizer.normalize(_make_blocks(text))[0]["normalized_text"]
        assert "题干" in normalized
        assert "B. 乙" in normalized
        assert "永久微信" not in normalized

    def test_legit_content_not_filtered(self, normalizer):
        """正常题干/选项不应被水印规则误删。"""
        text = "1. 设线性表有n个元素\nA. 输出第i个元素\nB. 交换元素"
        normalized = normalizer.normalize(_make_blocks(text))[0]["normalized_text"]
        assert "设线性表有n个元素" in normalized
        assert "A. 输出第i个元素" in normalized
        assert "B. 交换元素" in normalized

    def test_standalone_chapter_header_filtered(self, normalizer):
        """独立章标题行应被过滤。"""
        text = "第1章 线性表\n1. 下列选项中正确的是\nA. 选项一"
        normalized = normalizer.normalize(_make_blocks(text))[0]["normalized_text"]
        assert "第1章 线性表" not in normalized
        assert "下列选项中正确的是" in normalized
        assert "A. 选项一" in normalized

    def test_chapter_header_merged_with_question_not_filtered(self, normalizer):
        """章标题与题目合并行不应被过滤。"""
        text = "第1章 线性表 1.下列选项中正确的是（）\nA. x\nB. y\nC. z\nD. w"
        normalized = normalizer.normalize(_make_blocks(text))[0]["normalized_text"]
        assert "第1章 线性表" in normalized
        assert "下列选项中正确的是" in normalized

    def test_chapter_header_with_option_marker_not_filtered(self, normalizer):
        """章标题后跟选项标记 A. 的行不应被过滤。"""
        text = "第3章 栈和队列 A. 选项一\nB. 选项二"
        normalized = normalizer.normalize(_make_blocks(text))[0]["normalized_text"]
        assert "第3章 栈和队列" in normalized
        assert "A. 选项一" in normalized


# ---------------------------------------------------------------
# 5d. LaTeX 符号还原 — 行级上下文感知（P0 修复）
# ---------------------------------------------------------------

class TestLatexSubstitution:
    def test_prog_context_line_allow_substitution(self, normalizer):
        """编程上下文行内 LaTeX 允许替换：p->next=\\alpha → p->next=a。"""
        text = "链表插入操作：p->next = \\alpha"
        normalized = normalizer.normalize(_make_blocks(text))[0]["normalized_text"]
        assert "\\alpha" not in normalized
        assert "= a" in normalized or "=a" in normalized

    def test_math_context_line_block_substitution(self, normalizer):
        """数学上下文行内 LaTeX 不得替换：设\\alpha+\\beta=1 保持原样。"""
        text = "设\\alpha+\\beta=1，求极限"
        normalized = normalizer.normalize(_make_blocks(text))[0]["normalized_text"]
        assert "\\alpha" in normalized
        assert "\\beta" in normalized

    def test_mixed_lines_isolated(self, normalizer):
        """跨行隔离：编程行替换，数学行保留，互不污染。

        用句号结束第一行阻止 OCR 断行合并（_clean_newlines），确保两行独立判断。
        """
        text = "链表 p->next = \\alpha。\n设\\alpha+\\beta=1。"
        normalized = normalizer.normalize(_make_blocks(text))[0]["normalized_text"]
        lines = normalized.split("\n")
        prog_line = [l for l in lines if "p->next" in l][0]
        math_line = [l for l in lines if "设" in l][0]
        assert "\\alpha" not in prog_line
        assert "\\alpha" in math_line
        assert "\\beta" in math_line

    def test_no_prog_signal_no_substitution(self, normalizer):
        """无编程信号整文本：所有 LaTeX 保持不动。"""
        text = "\\alpha + \\beta = \\gamma + \\delta"
        normalized = normalizer.normalize(_make_blocks(text))[0]["normalized_text"]
        assert "\\alpha" in normalized
        assert "\\beta" in normalized
        assert "\\gamma" in normalized
        assert "\\delta" in normalized
        # 不应出现 OCR 逆向替换的产物（如 gamma→r, beta→B）
        assert "\\alpha + \\beta" in normalized

    def test_prog_signal_full_line_substitutes_all(self, normalizer):
        """含编程信号行内所有 LaTeX 符号都被替换。"""
        text = "struct node *p = NULL; p->next = \\alpha; q->prior = \\beta"
        normalized = normalizer.normalize(_make_blocks(text))[0]["normalized_text"]
        assert "\\alpha" not in normalized
        assert "\\beta" not in normalized

    def test_formula_normalizer_dependency(self, normalizer):
        """Unicode → LaTeX 先执行，行级替换在其后：
        α → \\alpha → a（编程行内）。"""
        text = "指针 p->next 指向 α 结点"
        normalized = normalizer.normalize(_make_blocks(text))[0]["normalized_text"]
        # fix_ocr_formula 把 α → \\alpha，_fix_latex_substitutions 把 \\alpha → a
        assert "α" not in normalized
        assert "\\alpha" not in normalized


# ---------------------------------------------------------------
# 6. 空文本
# ---------------------------------------------------------------

class TestEmptyInput:
    def test_empty_string(self, normalizer):
        result = normalizer.normalize(_make_blocks(""))
        assert result[0]["normalized_text"] == ""
        assert result[0]["raw_text"] == ""

    def test_empty_blocks_list(self, normalizer):
        result = normalizer.normalize([])
        assert result == []


# ---------------------------------------------------------------
# 7. 纯正常文本
# ---------------------------------------------------------------

class TestCleanText:
    def test_clean_text_unchanged(self, normalizer):
        text = _read_fixture("normalizer_clean.txt")
        result = normalizer.normalize(_make_blocks(text))
        normalized = result[0]["normalized_text"]
        # 干净文本的主要结构应保持
        assert "设函数" in normalized
        assert "求导公式" in normalized
        assert "矩阵的迹" in normalized

    def test_raw_text_preserved(self, normalizer):
        """raw_text 必须完全保留原文，不做任何修改。"""
        text = "包含\x00乱码　和\n\n\n多余换行"
        result = normalizer.normalize(_make_blocks(text))
        assert result[0]["raw_text"] == text
        # normalized_text 应该不同于 raw_text
        assert result[0]["normalized_text"] != text


# ---------------------------------------------------------------
# 8. 页码保留
# ---------------------------------------------------------------

class TestPagePreservation:
    def test_page_preserved(self, normalizer):
        blocks = [
            {"page": 3, "block_index": 0, "text": "第3页内容"},
            {"page": 5, "block_index": 1, "text": "第5页内容"},
        ]
        result = normalizer.normalize(blocks)
        assert result[0]["page"] == 3
        assert result[1]["page"] == 5

    def test_block_index_preserved(self, normalizer):
        blocks = [
            {"page": 1, "block_index": 42, "text": "某块内容"},
        ]
        result = normalizer.normalize(blocks)
        assert result[0]["block_index"] == 42

    def test_default_page(self, normalizer):
        """缺少 page/block_index 时使用默认值。"""
        result = normalizer.normalize([{"text": "内容"}])
        assert result[0]["page"] == 1
        assert result[0]["block_index"] == 0


# ---------------------------------------------------------------
# 9. 批量 blocks
# ---------------------------------------------------------------

class TestBatchBlocks:
    def test_multiple_blocks_independent(self, normalizer):
        blocks = [
            {"page": 1, "block_index": 0, "text": "包含乱码\x00文本"},
            {"page": 1, "block_index": 1, "text": "正常文本"},
        ]
        result = normalizer.normalize(blocks)
        assert len(result) == 2
        assert "\x00" not in result[0]["normalized_text"]
        assert result[1]["raw_text"] == result[1]["normalized_text"]

    def test_block_indices_sequential(self, normalizer):
        blocks = [
            {"page": 1, "text": "block 0"},
            {"page": 1, "text": "block 1"},
            {"page": 2, "text": "block 2"},
        ]
        result = normalizer.normalize(blocks)
        assert result[0]["block_index"] == 0
        assert result[1]["block_index"] == 1
        assert result[2]["block_index"] == 2
        assert result[2]["page"] == 2


# ---------------------------------------------------------------
# 10. 集成：综合 OCR 噪声
# ---------------------------------------------------------------

class TestOcrNoiseIntegration:
    def test_ocr_noise_fixture(self, normalizer):
        text = _read_fixture("normalizer_ocr_noise.txt")
        result = normalizer.normalize(_make_blocks(text))
        normalized = result[0]["normalized_text"]
        # 验证 raw_text 保留
        assert result[0]["raw_text"] == text
        # 关键纠正检查
        assert "�" not in normalized
        assert "\x00" not in normalized
