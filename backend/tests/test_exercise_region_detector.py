"""Tests for exercise_region_detector module."""

import pytest

from app.features.exercise_region_detector import (
    ExerciseRegion,
    _compute_exercise_page_score,
    _has_question_pattern,
    _levenshtein,
    _match_end_keyword,
    _match_exercise_keyword,
    _normalize_for_matching,
    detect_exercise_regions,
    EXERCISE_END_KEYWORDS,
    EXERCISE_START_KEYWORDS,
)


# ---------------------------------------------------------------------------
# Levenshtein
# ---------------------------------------------------------------------------


class TestLevenshtein:
    def test_identical(self):
        assert _levenshtein("abc", "abc") == 0

    def test_empty(self):
        assert _levenshtein("", "abc") == 3
        assert _levenshtein("abc", "") == 3

    def test_one_sub(self):
        assert _levenshtein("精选", "精迭") == 1

    def test_two_edits(self):
        assert _levenshtein("习题精选", "习趣精迭") == 2


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


class TestNormalization:
    def test_strip_punctuation(self):
        assert _normalize_for_matching("习题：精选") == "习题精选"

    def test_traditional_to_simplified(self):
        assert _normalize_for_matching("習題精選") == "习题精选"

    def test_mixed(self):
        assert _normalize_for_matching("本節習題") == "本节习题"


# ---------------------------------------------------------------------------
# Keyword matching
# ---------------------------------------------------------------------------


class TestKeywordMatching:
    def test_exact_match(self):
        result = _match_exercise_keyword("本节习题精选", EXERCISE_START_KEYWORDS)
        assert result is not None
        kw, conf = result
        assert kw == "本节习题精选"
        assert conf == 1.0

    def test_exact_match_with_punctuation(self):
        result = _match_exercise_keyword("习题精选：", EXERCISE_START_KEYWORDS)
        assert result is not None
        kw, conf = result
        assert conf == 1.0

    def test_fuzzy_one_typo(self):
        # "同步训鍊" has 1 edit from "同步训练" and no keyword is a substring of it
        result = _match_exercise_keyword("同步训鍊", EXERCISE_START_KEYWORDS)
        assert result is not None
        _, conf = result
        assert conf == 0.8

    def test_fuzzy_two_typos(self):
        result = _match_exercise_keyword("本节习趣精迭", EXERCISE_START_KEYWORDS)
        assert result is not None
        _, conf = result
        assert conf == 0.6

    def test_traditional_chinese(self):
        result = _match_exercise_keyword("本節習題精選", EXERCISE_START_KEYWORDS)
        assert result is not None
        _, conf = result
        assert conf == 1.0

    def test_no_match(self):
        result = _match_exercise_keyword("第一章 数据结构基础", EXERCISE_START_KEYWORDS)
        assert result is None

    def test_embedded_in_line(self):
        result = _match_exercise_keyword("以下是本章习题部分", EXERCISE_START_KEYWORDS)
        assert result is not None
        kw, conf = result
        assert kw == "本章习题"
        assert conf == 1.0

    def test_multiline_text(self):
        text = "这是正文内容\n本章习题\n1. 请问下列哪个"
        result = _match_exercise_keyword(text, EXERCISE_START_KEYWORDS)
        assert result is not None

    def test_short_keyword_exact_only(self):
        result = _match_exercise_keyword("习题", EXERCISE_START_KEYWORDS)
        assert result is not None
        kw, conf = result
        assert kw == "习题"
        assert conf == 1.0


# ---------------------------------------------------------------------------
# End keyword matching
# ---------------------------------------------------------------------------


class TestEndKeyword:
    def test_answer_keyword(self):
        assert _match_end_keyword("参考答案") == "参考答案"

    def test_answer_with_analysis(self):
        assert _match_end_keyword("答案与解析") == "答案与解析"

    def test_chapter_summary(self):
        assert _match_end_keyword("本章小结") == "本章小结"

    def test_no_match(self):
        assert _match_end_keyword("3. 下列关于操作系统的说法") is None


# ---------------------------------------------------------------------------
# Page scoring
# ---------------------------------------------------------------------------


class TestPageScoring:
    def test_typical_exercise_page(self):
        text = """1. 下列关于数据结构的说法正确的是
A. 数据结构是数据的逻辑结构
B. 数据结构包括数据的存储结构
C. 数据结构与算法无关
D. 以上都不对
2. 线性表的顺序存储中
A. 元素逻辑相邻
B. 元素物理相邻
C. 以上都是
D. 以上都不是
3. 栈的特点是"""
        score = _compute_exercise_page_score(text)
        assert score >= 0.5

    def test_knowledge_page(self):
        text = """定义 1.1 数据结构的基本概念
数据结构是指相互之间存在一种或多种特定关系的数据元素的集合。
定义 1.2 算法的性质
定理 1.1 任何算法的时间复杂度"""
        score = _compute_exercise_page_score(text)
        assert score < 0.2

    def test_empty_page(self):
        assert _compute_exercise_page_score("") == 0.0
        assert _compute_exercise_page_score("   ") == 0.0

    def test_fill_blank_questions(self):
        text = """1. 数据结构中，___是指数据元素的有限集合。
2. 算法的五个特性是___、___、___、___、___。
3. 时间复杂度用___表示。"""
        score = _compute_exercise_page_score(text)
        assert score >= 0.3

    def test_has_question_pattern(self):
        assert _has_question_pattern("1. 请问") is True
        assert _has_question_pattern("这是正文") is False


# ---------------------------------------------------------------------------
# Region detection (integration of all phases)
# ---------------------------------------------------------------------------


class TestDetectExerciseRegions:
    def test_single_region(self):
        page_texts = {
            1: "第一章 数据结构",
            2: "1.1 基本概念\n定义：数据结构是...",
            3: "本章习题",
            4: "1. 下列说法正确的是\nA. xxx\nB. yyy\nC. zzz\nD. www",
            5: "2. 栈的特点\nA. 先进后出\nB. 先进先出\nC. 随机\nD. 无序",
            6: "参考答案\n1. A\n2. A",
        }
        regions = detect_exercise_regions(page_texts)
        assert len(regions) == 1
        assert regions[0].start_page == 3
        assert regions[0].end_page == 6
        assert regions[0].matched_keyword == "本章习题"

    def test_multiple_regions(self):
        page_texts = {
            1: "第一章正文内容",
            2: "定义、定理等知识点",
            3: "本章习题",
            4: "1. 题目一\nA. 选A\nB. 选B\nC. 选C\nD. 选D",
            5: "本章小结\n知识要点回顾",
            6: "第二章正文内容",
            7: "知识点讲解",
            8: "课后习题",
            9: "1. 第二章题目\nA. aaa\nB. bbb\nC. ccc\nD. ddd",
            10: "2. 另一题\nA. xx\nB. yy\nC. zz\nD. ww",
            11: "参考答案",
        }
        regions = detect_exercise_regions(page_texts)
        assert len(regions) == 2
        assert regions[0].start_page == 3
        assert regions[1].start_page == 8

    def test_no_exercise_found(self):
        page_texts = {
            1: "第一章 概述",
            2: "定义、定理、概念、原理",
            3: "更多知识点讲解",
        }
        regions = detect_exercise_regions(page_texts)
        assert regions == []

    def test_empty_input(self):
        assert detect_exercise_regions({}) == []

    def test_end_by_empty_pages(self):
        page_texts = {
            1: "习题精选",
            2: "1. 题目\nA. a\nB. b\nC. c\nD. d",
            3: "2. 题目二\nA. a\nB. b\nC. c\nD. d",
            4: "无关内容",
            5: "还是无关",
            6: "仍然无关",
        }
        regions = detect_exercise_regions(page_texts, config={"max_empty_pages": 3})
        assert len(regions) == 1
        assert regions[0].end_page == 3

    def test_confidence_threshold(self):
        page_texts = {
            1: "习题精选",
            2: "1. 题目\nA. a\nB. b\nC. c\nD. d",
        }
        regions = detect_exercise_regions(page_texts, config={"min_confidence": 1.0})
        assert len(regions) == 1

        regions_strict = detect_exercise_regions(page_texts, config={"min_confidence": 1.1})
        assert regions_strict == []

    def test_exercise_at_end_of_document(self):
        page_texts = {
            1: "正文",
            2: "本节习题",
            3: "1. 题目\nA. a\nB. b\nC. c\nD. d",
            4: "2. 题目\nA. a\nB. b\nC. c\nD. d",
        }
        regions = detect_exercise_regions(page_texts)
        assert len(regions) == 1
        assert regions[0].end_page == 4
