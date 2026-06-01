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
