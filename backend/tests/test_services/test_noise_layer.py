"""Unit tests for code_language_noise_layer — transition detection, classification, cleaning."""

from __future__ import annotations

from app.features.pipeline_stages.code_language_noise_layer import (
    classify_noise,
    clean_code_language_noise,
    detect_transition_zones,
)

# ===========================================================================
# Phase 1: Transition Zone Detection
# ===========================================================================


class TestDetectTransitionZones:
    def test_case5_transition_detected(self):
        """8．在单链表中进行如下操作： 必须被识别为过渡区起点。

        BUGS.md 案例五的题干，修复前无匹配模式导致 ``<1>`` 无法被清除。
        修复增加了 ``在XXXX中进行如下XX:`` 和 ``进行如下XX:`` 模式。
        """
        text = "8．在单链表中进行如下操作：\n<1>\ntypedef struct LNode {"
        zones = detect_transition_zones(text)
        assert len(zones) >= 1
        assert zones[0][0] == 1  # starts at line 1

    def test_known_ptr_transition_detected(self):
        """已知 p 指向某节点，执行插入操作: 必须被识别为过渡区起点。"""
        text = "已知 p 指向某节点，执行插入操作:\nA. p->next"
        zones = detect_transition_zones(text)
        assert len(zones) >= 1
        assert zones[0][0] == 1

    def test_dui_insert_transition_detected(self):
        """对链表执行插入操作 必须被识别为过渡区起点。"""
        text = "对链表执行插入操作:\ns->next = p->next;"
        zones = detect_transition_zones(text)
        assert len(zones) >= 1
        assert zones[0][0] == 1

    def test_typedef_precursor_detected(self):
        """typedef (无 # 前缀) 必须被识别为代码前驱行。

        BUGS.md 案例五：`typedef struct LNode {` 的首个关键字 `typedef`
        应激活过渡区（作为代码前驱行）。修复前只有 `#\\s*typedef` 匹配。
        """
        text = "typedef struct LNode {\nint data;\n} LNode, *LinkList;"
        zones = detect_transition_zones(text)
        assert len(zones) >= 1
        assert zones[0][0] == 1

    def test_no_false_positive_for_plain_text(self):
        """纯自然语言文本不应误报过渡区。"""
        text = "计算下列各题：\n(1) 2+3=\n(2) 4+5="
        zones = detect_transition_zones(text)
        assert len(zones) == 0

    def test_zone_merging_adjacent(self):
        """相邻的过渡区应合并。"""
        text = "执行如下操作:\n<1>\ntypedef struct LNode {"
        zones = detect_transition_zones(text)
        assert len(zones) >= 1
        # "执行如下操作:" triggers zone line 1-4, "typedef" triggers line 3-6
        # They should merge into one zone
        assert zones[0][1] >= 3

    def test_max_transition_lines(self):
        """过渡区不超过 _MAX_TRANSITION_LINES 行（3行）。"""
        text = "进行如下操作：\nline2\nline3\nline4\nline5"
        zones = detect_transition_zones(text)
        assert len(zones) == 1
        assert zones[0] == (1, 4)  # line 1 + 3 = 4


# ===========================================================================
# Phase 2: Noise Classification
# ===========================================================================


class TestClassifyNoise:
    def test_angle_bracket_digit_noise(self):
        """<1> 应被分类为 c_cpp_noise。"""
        noise_type, confidence = classify_noise("<1>")
        assert noise_type == "c_cpp_noise"
        assert confidence >= 0.9

    def test_angle_bracket_12_noise(self):
        """<12> 应被分类为 c_cpp_noise。"""
        noise_type, confidence = classify_noise("<12>")
        assert noise_type == "c_cpp_noise"
        assert confidence >= 0.9

    def test_angle_bracket_with_space_noise(self):
        """< 1 > 应被分类为 c_cpp_noise。"""
        noise_type, confidence = classify_noise("< 1 >")
        assert noise_type == "c_cpp_noise"
        assert confidence >= 0.9

    def test_cpp_line_is_not_noise(self):
        """包含 C++ 关键词的代码行不应被分类为噪声。"""
        noise_type, confidence = classify_noise("typedef struct LNode {")
        assert noise_type == ""  # clean

    def test_code_with_semicolon_not_noise(self):
        """含分号的代码行不应被分类为噪声。"""
        noise_type, confidence = classify_noise("int data;")
        assert noise_type == ""

    def test_empty_line_not_noise(self):
        noise_type, confidence = classify_noise("")
        assert noise_type == ""

    def test_plain_text_not_noise(self):
        noise_type, confidence = classify_noise("已知 p 指向某节点")
        assert noise_type == ""


# ===========================================================================
# Phase 3: Full Cleaning (integration)
# ===========================================================================


class TestCleanCodeLanguageNoise:
    def test_case5_angle_bracket_removed(self):
        """案例五完整文本：<1> 应在清除后被移除。"""
        text = (
            "8．在单链表中进行如下操作：\n"
            "<1>\n"
            "typedef struct LNode {\n"
            "int data;\n"
            "struct LNode *next;\n"
            "} LNode, *LinkList;\n"
            "已知 p 指向某节点，执行插入操作:"
        )
        cleaned = clean_code_language_noise(text)
        # <1> line should be removed
        lines = cleaned.split("\n")
        noise_lines = [l for l in lines if "<1>" in l or "< 1 >" in l]
        assert len(noise_lines) == 0

    def test_typedef_code_preserved(self):
        """真实代码行不应被清除。"""
        text = "进行如下操作：\n<1>\ntypedef struct LNode {\nint data;\n};"
        cleaned = clean_code_language_noise(text)
        assert "typedef struct LNode" in cleaned
        assert "int data" in cleaned

    def test_no_noise_no_change(self):
        """无噪声的文本应保持不变。"""
        text = "这是一道普通的题目。\nA. 选项一\nB. 选项二"
        cleaned = clean_code_language_noise(text)
        assert cleaned == text

    def test_empty_text(self):
        assert clean_code_language_noise("") == ""
        assert clean_code_language_noise(None) is None

    def test_safe_mode_still_removes_bracket_noise(self):
        """safe_mode 下仍应移除 `<1>` 等高置信度噪声。"""
        text = "执行如下操作:\n<1>\ncode line"
        cleaned = clean_code_language_noise(text, safe_mode=True)
        assert "<1>" not in cleaned
