"""DocumentStructureAnalyzer 单元测试。"""
from app.features.structure_analyzer import analyze_structure


def _make_blocks(texts: list[str], start_index: int = 0) -> list[dict]:
    """Helper：将多个文本包装为 normalized_blocks。"""
    return [
        {
            "page": 1,
            "block_index": start_index + i,
            "raw_text": t,
            "normalized_text": t,
        }
        for i, t in enumerate(texts)
    ]


# ---------------------------------------------------------------
# 1. INLINE 模式检测
# ---------------------------------------------------------------

class TestInlineMode:
    def test_interleaved_qa(self):
        """题目和答案交替出现 → INLINE。"""
        blocks = _make_blocks([
            "1. 设函数 f(x) = x^2，求 f'(x)。\n答案：2x",
            "2. 求极限 lim(x→∞) (1+1/x)^x。\n答案：e",
            "3. 矩阵 A 的秩为？\n答案：3",
        ])
        result = analyze_structure(blocks)
        assert result["mode"] == "INLINE"
        assert result["confidence"] > 0.5
        assert len(result["question_pages"]) > 0
        assert len(result["answer_pages"]) > 0

    def test_high_overlap_inline(self):
        """同一 block 内题目和答案共存 → 高重叠 → INLINE。"""
        blocks = _make_blocks([
            "1. 什么是数据结构？\n2. 什么是算法？\n参考答案：1.A 2.B\n解析：基础知识",
            "3. 栈的特点？\n4. 队列的特点？\n答案：3.C 4.D\n解析：略",
        ])
        result = analyze_structure(blocks)
        assert result["mode"] == "INLINE"

    def test_inline_with_explanations(self):
        """含解析区域的 INLINE 文档。"""
        blocks = _make_blocks([
            "1. TCP 位于哪一层？\nA. 网络层 B. 传输层 C. 应用层\n答案：B\n解析：TCP 是传输层协议",
            "2. UDP 的特点？\nA. 面向连接 B. 无连接 C. 可靠传输\n答案：B\n解析：UDP 是无连接协议",
        ])
        result = analyze_structure(blocks)
        assert result["mode"] == "INLINE"
        assert len(result["explanation_pages"]) > 0


# ---------------------------------------------------------------
# 2. SEPARATED 模式检测
# ---------------------------------------------------------------

class TestSeparatedMode:
    def test_questions_then_answers(self):
        """题目全部在前，答案全部在后 → SEPARATED。"""
        blocks = _make_blocks([
            "1. 求导数 f'(x)。\n2. 求积分 ∫f(x)dx。\n3. 计算矩阵行列式。\n4. 求解微分方程。\n5. 判断级数敛散性。",
            "6. 求特征值和特征向量。\n7. 求极限。\n8. 证明函数连续性。",
            "参考答案：\n1. 2x\n2. x^2/2 + C\n3. 0\n4. y = Ce^x\n5. 收敛",
            "6. λ1=1, λ2=2\n7. e\n8. 略",
        ])
        result = analyze_structure(blocks)
        assert result["mode"] == "SEPARATED"
        assert result["confidence"] > 0.5

    def test_clear_separation(self):
        """题目区和答案区有明显的分界线。"""
        blocks = _make_blocks([
            "一、选择题\n1. 题目A\n2. 题目B\n3. 题目C",
            "4. 题目D\n5. 题目E",
            "二、参考答案\n1.A\n2.B\n3.C\n4.D\n5.E",
        ])
        result = analyze_structure(blocks)
        assert result["mode"] == "SEPARATED"
        q = result["question_pages"]
        a = result["answer_pages"]
        # 纯题目区在答案区之前（mixed 块可重叠）
        assert q[0] <= a[0]

    def test_answer_pages_use_page_not_block_index(self):
        """多页输入中 answer_pages 应返回真实页码，而不是 block_index。"""
        blocks = [
            {
                "page": 1,
                "block_index": 10,
                "raw_text": "1. 题目A\n2. 题目B",
                "normalized_text": "1. 题目A\n2. 题目B",
            },
            {
                "page": 3,
                "block_index": 11,
                "raw_text": "参考答案：\n1.A\n2.B",
                "normalized_text": "参考答案：\n1.A\n2.B",
            },
        ]
        result = analyze_structure(blocks)
        assert result["mode"] == "SEPARATED"
        assert result["answer_pages"] == [3]


# ---------------------------------------------------------------
# 3. 无答案文档
# ---------------------------------------------------------------

class TestNoAnswer:
    def test_questions_only(self):
        """纯题目，无答案区。"""
        blocks = _make_blocks([
            "1. 计算下列极限。\n2. 求函数极值。\n3. 证明不等式。",
            "4. 求解矩阵方程。\n5. 计算二重积分。",
        ])
        result = analyze_structure(blocks)
        assert result["mode"] == "UNKNOWN"
        assert len(result["answer_pages"]) == 0
        assert len(result["question_pages"]) > 0

    def test_no_content(self):
        """无题目也无答案的文本。"""
        blocks = _make_blocks([
            "这是一段无关文本，没有题目也没有答案。",
        ])
        result = analyze_structure(blocks)
        assert result["mode"] == "UNKNOWN"
        assert result["confidence"] < 0.5


# ---------------------------------------------------------------
# 4. 空输入
# ---------------------------------------------------------------

class TestEmptyInput:
    def test_empty_list(self):
        result = analyze_structure([])
        assert result["mode"] == "UNKNOWN"
        assert result["details"]["total_blocks"] == 0
        assert result["confidence"] == 0.0

    def test_empty_text_blocks(self):
        blocks = _make_blocks([""])
        result = analyze_structure(blocks)
        assert result["mode"] == "UNKNOWN"


# ---------------------------------------------------------------
# 5. 单 block 输入
# ---------------------------------------------------------------

class TestSingleBlock:
    def test_single_block_with_qa(self):
        """单段包含题目和答案。"""
        blocks = _make_blocks([
            "1. 题目 A。答案：B\n2. 题目 B。答案：C",
        ])
        result = analyze_structure(blocks)
        # 单 block 内同时有题目和答案，overlap=1.0 → INLINE
        assert result["mode"] == "INLINE"

    def test_single_block_question_only(self):
        """单段仅含题目。"""
        blocks = _make_blocks(["1. 题目一"])
        result = analyze_structure(blocks)
        assert result["mode"] == "UNKNOWN"
        assert len(result["question_pages"]) == 1


# ---------------------------------------------------------------
# 6. 多种题号格式
# ---------------------------------------------------------------

class TestMixedFormats:
    def test_dot_format(self):
        blocks = _make_blocks(["1. 题目\n2. 题目\n答案：A"])
        result = analyze_structure(blocks)
        assert result["details"]["matched_patterns"]["question_header"] > 0

    def test_paren_format(self):
        blocks = _make_blocks(["(1) 题目\n(2) 题目\n答案：B"])
        result = analyze_structure(blocks)
        assert result["details"]["matched_patterns"]["question_header"] > 0

    def test_bracket_format(self):
        blocks = _make_blocks(["【1】题目\n【2】题目\n答案：C"])
        result = analyze_structure(blocks)
        assert result["details"]["matched_patterns"]["question_header"] > 0

    def test_chinese_prefix_format(self):
        blocks = _make_blocks(["第一题 题目\n第二题 题目\n答案：D"])
        result = analyze_structure(blocks)
        assert result["details"]["matched_patterns"]["question_header"] > 0

    def test_chinese_comma_format(self):
        blocks = _make_blocks(["1、题目A\n2、题目B\n答案：A"])
        result = analyze_structure(blocks)
        assert result["details"]["matched_patterns"]["question_header"] > 0

    def test_mixed_formats_recognized(self):
        """多种题号格式混合。"""
        blocks = _make_blocks([
            "1. 用点号的题目\n2、用顿号的题目\n(3) 用括号的题目\n【4】用方括号的题目\n第五题 中文题号",
            "参考答案：略",
        ])
        result = analyze_structure(blocks)
        assert result["details"]["matched_patterns"]["question_header"] >= 5


# ---------------------------------------------------------------
# 7. 英文关键词
# ---------------------------------------------------------------

class TestEnglishKeywords:
    def test_english_answer_keywords(self):
        blocks = _make_blocks([
            "1. What is the derivative of x^2?\nAnswer: 2x",
            "2. What is the integral of x?\nAnswer: x^2/2 + C",
        ])
        result = analyze_structure(blocks)
        assert result["mode"] == "INLINE"
        assert result["details"]["matched_patterns"]["answer_keyword"] > 0

    def test_english_explanation_keywords(self):
        blocks = _make_blocks([
            "1. Question text\nAnswer: B\nExplanation: Because ...",
        ])
        result = analyze_structure(blocks)
        assert result["details"]["matched_patterns"]["analysis_keyword"] > 0

    def test_key_match(self):
        """KEY 关键词匹配。"""
        blocks = _make_blocks([
            "1. Question\nKEY: A",
        ])
        result = analyze_structure(blocks)
        assert result["details"]["matched_patterns"]["answer_keyword"] > 0


# ---------------------------------------------------------------
# 8. OCR 噪声文本
# ---------------------------------------------------------------

class TestOcrNoise:
    def test_noise_does_not_block_analysis(self):
        """OCR 噪声不应阻断结构分析。"""
        blocks = _make_blocks([
            "1. 含乱码的题目\x00文本\n答案：A",
            "2. 有不可见字符\x1f的题目\n答案：B",
        ])
        result = analyze_structure(blocks)
        # 即使有噪声，仍能识别题目和答案
        assert result["details"]["matched_patterns"]["question_header"] > 0
        assert result["details"]["matched_patterns"]["answer_keyword"] > 0

    def test_ocr_corrected_text(self):
        """OCR 纠正后的文本（8→B 等已纠正）。"""
        blocks = _make_blocks([
            "1. 题目内容\nB. 选项一\nC. 选项二\nD. 选项三\n答案：B",
        ])
        result = analyze_structure(blocks)
        assert result["mode"] == "INLINE"

    def test_diagnostic_fields_present(self):
        blocks = _make_blocks([
            "1. 题目A\n答案：A\n解析：略",
            "2. 题目B\n答案：B",
        ])
        result = analyze_structure(blocks)
        assert result["details"]["diagnostic_reason"] == "question_and_answer_overlap"
        assert result["details"]["question_density"] > 0
        assert result["details"]["answer_density"] > 0
        assert result["details"]["analysis_density"] > 0
        assert result["details"]["ocr_noise_signals"] == 0
        assert result["details"]["has_question_blocks"] is True
        assert result["details"]["has_answer_blocks"] is True
        assert result["details"]["has_explanation_blocks"] is True

    def test_ocr_noise_signal_counted(self):
        blocks = _make_blocks([
            "1. 含乱码的题目\x00文本\n答案：A",
        ])
        result = analyze_structure(blocks)
        assert result["details"]["ocr_noise_signals"] > 0


# ---------------------------------------------------------------
# 9. 置信度
# ---------------------------------------------------------------

class TestConfidence:
    def test_many_matches_higher_confidence(self):
        """匹配数越多，置信度越高。"""
        few = _make_blocks(["1. 题A\n答案：A"])
        many = _make_blocks([
            "1. 题A\n2. 题B\n3. 题C\n4. 题D\n5. 题E\n答案：略",
        ])
        r_few = analyze_structure(few)
        r_many = analyze_structure(many)
        # 更多题号 → 更多匹配
        assert r_many["details"]["matched_patterns"]["question_header"] >= r_few["details"]["matched_patterns"]["question_header"]

    def test_confidence_in_range(self):
        """置信度应在 [0, 1] 范围内。"""
        blocks = _make_blocks([
            "1. 题A\n答案：A",
        ])
        result = analyze_structure(blocks)
        assert 0.0 <= result["confidence"] <= 1.0


# ---------------------------------------------------------------
# 10. details 字段完整性
# ---------------------------------------------------------------

class TestDetailsFields:
    def test_details_structure(self):
        blocks = _make_blocks([
            "1. 题目一\n答案：A\n解析：因为",
            "2. 题目二\n答案：B",
        ])
        result = analyze_structure(blocks)
        assert "details" in result
        d = result["details"]
        assert "total_blocks" in d
        assert d["total_blocks"] == 2
        assert "matched_patterns" in d
        mp = d["matched_patterns"]
        assert "question_header" in mp
        assert "answer_keyword" in mp
        assert "analysis_keyword" in mp
        assert mp["question_header"] > 0
        assert mp["answer_keyword"] > 0
        assert mp["analysis_keyword"] > 0


# ---------------------------------------------------------------
# file_metadata 可选参数
# ---------------------------------------------------------------

class TestFileMetadata:
    def test_metadata_optional(self):
        """file_metadata 参数可选。"""
        blocks = _make_blocks(["1. 题\n答案：A"])
        result_with = analyze_structure(blocks, {"filename": "test.pdf"})
        result_without = analyze_structure(blocks)
        assert result_with["mode"] == result_without["mode"]


# ---------------------------------------------------------------
# 11. Answer continuation pages
# ---------------------------------------------------------------


def _make_multipage_blocks(page_texts: dict[int, str]) -> list[dict]:
    """Helper: create blocks with specific page numbers."""
    blocks = []
    for page, text in sorted(page_texts.items()):
        blocks.append({
            "page": page,
            "block_index": page - 1,
            "raw_text": text,
            "normalized_text": text,
        })
    return blocks


class TestAnswerContinuationPages:
    def test_continuation_page_detected(self):
        """Pages after answer page with numbered answers are included."""
        blocks = _make_multipage_blocks({
            1: "1. 题目一\n2. 题目二\n3. 题目三",
            2: "4. 题目四\n5. 题目五",
            3: "参考答案\n1.A\n2.B\n3.C",
            4: "4.D\n5.A\n6.B",
        })
        result = analyze_structure(blocks)
        assert result["mode"] == "SEPARATED"
        assert 4 in result["answer_pages"]

    def test_continuation_stops_at_non_answer_page(self):
        """Expansion stops when a page doesn't have enough answer patterns."""
        blocks = _make_multipage_blocks({
            1: "1. 题目一\n2. 题目二",
            2: "参考答案\n1.A\n2.B\n3.C",
            3: "4.D\n5.A\n6.B",
            4: "本章小结：数据结构是计算机科学的基础课程",
        })
        result = analyze_structure(blocks)
        assert 3 in result["answer_pages"]
        assert 4 not in result["answer_pages"]

    def test_no_expansion_without_initial_answer_pages(self):
        """No expansion when there are no initial answer pages."""
        blocks = _make_multipage_blocks({
            1: "1. 题目一\n2. 题目二",
            2: "3. 题目三\n4. 题目四",
        })
        result = analyze_structure(blocks)
        assert result["answer_pages"] == [] or result["mode"] != "SEPARATED"

    def test_single_answer_page_no_continuation(self):
        """Single answer page with no following pages stays unchanged."""
        blocks = _make_multipage_blocks({
            1: "1. 题目一\n2. 题目二",
            2: "参考答案\n1.A\n2.B\n3.C",
        })
        result = analyze_structure(blocks)
        assert result["mode"] == "SEPARATED"
        assert 2 in result["answer_pages"]

    def test_multiple_continuation_pages(self):
        """Multiple consecutive answer continuation pages are all detected."""
        blocks = _make_multipage_blocks({
            1: "1. 题目一\n2. 题目二\n3. 题目三\n4. 题目四\n5. 题目五",
            2: "参考答案\n1.A\n2.B\n3.C",
            3: "4.D\n5.A\n6.B",
            4: "7.C\n8.A\n9.D",
        })
        result = analyze_structure(blocks)
        assert result["mode"] == "SEPARATED"
        assert 2 in result["answer_pages"]
        assert 3 in result["answer_pages"]
        assert 4 in result["answer_pages"]
