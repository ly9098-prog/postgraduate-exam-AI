"""Tests for page_classifier module."""


from app.features.page_classifier import (
    ANALYSIS_PAGE,
    ANSWER_PAGE,
    BLANK_PAGE,
    CATALOG_PAGE,
    KNOWLEDGE_PAGE,
    QUESTION_PAGE,
    classify_pages,
    filter_blocks_by_classification,
)


def _make_blocks(pages: dict[int, str]) -> list[dict]:
    """Helper: create normalized_blocks from {page: text} mapping."""
    blocks = []
    for i, (page, text) in enumerate(pages.items()):
        blocks.append({
            "page": page,
            "block_index": i,
            "normalized_text": text,
        })
    return blocks


class TestClassifyPages:
    def test_blank_page(self):
        blocks = _make_blocks({1: "", 2: "  "})
        result = classify_pages(blocks)
        assert len(result) == 2
        assert result[0]["label"] == BLANK_PAGE
        assert result[1]["label"] == BLANK_PAGE

    def test_question_page_with_numbers_and_options(self):
        text = (
            "1. 以下哪个是正确的？\n"
            "A. 选项一\n"
            "B. 选项二\n"
            "C. 选项三\n"
            "D. 选项四\n"
            "2. 下列说法错误的是\n"
            "A. 说法一\n"
            "B. 说法二\n"
            "C. 说法三\n"
            "D. 说法四\n"
            "3. 计算机网络的分类\n"
            "A. 局域网\n"
            "B. 广域网\n"
            "C. 城域网\n"
            "D. 以上都是\n"
        )
        blocks = _make_blocks({1: text})
        result = classify_pages(blocks)
        assert result[0]["label"] == QUESTION_PAGE

    def test_answer_page_with_keyword_and_list(self):
        text = (
            "参考答案\n"
            "1. B\n"
            "2. A\n"
            "3. C\n"
            "4. D\n"
            "5. B\n"
            "6. A\n"
        )
        blocks = _make_blocks({1: text})
        result = classify_pages(blocks)
        assert result[0]["label"] == ANSWER_PAGE

    def test_analysis_page(self):
        text = (
            "【解析】本题考查进程同步的概念。\n"
            "解析：信号量是一种同步机制。\n"
            "解答：PV操作是原语操作。\n"
            "详解：进程互斥是指...\n"
        )
        blocks = _make_blocks({1: text})
        result = classify_pages(blocks)
        assert result[0]["label"] == ANALYSIS_PAGE

    def test_knowledge_page_prose(self):
        text = (
            "计算机网络的定义是将地理位置不同的具有独立功能的多台计算机及其外部设备，"
            "通过通信线路连接起来，在网络操作系统、网络管理软件及网络通信协议的管理和"
            "协调下，实现资源共享和信息传递的计算机系统。计算机网络的功能主要包括：数据通信、"
            "资源共享、分布式处理、提高可靠性等。网络协议的三要素是语法、语义和同步。"
            "OSI参考模型将网络通信功能分为七层。"
        )
        blocks = _make_blocks({1: text})
        result = classify_pages(blocks)
        assert result[0]["label"] == KNOWLEDGE_PAGE

    def test_catalog_page(self):
        text = (
            "目 录\n"
            "第一章 计算机系统概述................1\n"
            "第二章 数据的表示和运算..............45\n"
            "第三章 存储器层次结构................89\n"
            "第四章 指令系统.....................130\n"
        )
        blocks = _make_blocks({1: text})
        result = classify_pages(blocks)
        assert result[0]["label"] == CATALOG_PAGE

    def test_multi_page_mixed_document(self):
        pages = {
            1: "目 录\n第一章 概述...........1\n第二章 进程...........30\n",
            2: (
                "操作系统是管理计算机硬件与软件资源的计算机程序。"
                "操作系统的主要功能包括处理器管理、存储器管理、设备管理和文件管理。"
                "操作系统的特征有并发性、共享性、虚拟性和异步性。"
            ),
            3: (
                "1. 下列哪个不是操作系统的特征？\n"
                "A. 并发性\nB. 共享性\nC. 虚拟性\nD. 顺序性\n"
                "2. 操作系统的功能不包括\n"
                "A. 处理器管理\nB. 编译管理\nC. 设备管理\nD. 文件管理\n"
            ),
            4: "参考答案\n1. D\n2. B\n3. A\n4. C\n",
        }
        blocks = _make_blocks(pages)
        result = classify_pages(blocks)

        labels = {r["page"]: r["label"] for r in result}
        assert labels[1] == CATALOG_PAGE
        assert labels[2] == KNOWLEDGE_PAGE
        assert labels[3] == QUESTION_PAGE
        assert labels[4] == ANSWER_PAGE

    def test_section_marker_boost(self):
        text = (
            "1. 某个问题的描述\n"
            "这是一道关于操作系统的题目，请问以下哪个选项是正确的？\n"
        )
        blocks = _make_blocks({5: text})
        markers = [{"page": 5, "block_index": 0, "marker_type": "exercise_start", "text": "习题精选"}]
        result = classify_pages(blocks, section_markers=markers)
        assert result[0]["label"] == QUESTION_PAGE


class TestFilterBlocks:
    def test_filters_knowledge_and_catalog(self):
        blocks = _make_blocks({
            1: "目 录\n第一章...1\n第二章...30\n",
            2: "这是知识点内容" * 20,
            3: "1. 题目一\nA. 选项\nB. 选项\nC. 选项\nD. 选项\n2. 题目二\nA. x\nB. y\nC. z\nD. w\n",
        })
        classifications = classify_pages(blocks)
        filtered = filter_blocks_by_classification(blocks, classifications)

        remaining_pages = {b["page"] for b in filtered}
        assert 1 not in remaining_pages
        assert 3 in remaining_pages

    def test_custom_allowed_labels(self):
        blocks = _make_blocks({
            1: "1. 题目\nA. a\nB. b\nC. c\nD. d\n2. 题目\nA. x\nB. y\nC. z\nD. w\n",
            2: "参考答案\n1. B\n2. A\n3. C\n4. D\n5. A\n",
        })
        classifications = classify_pages(blocks)
        filtered = filter_blocks_by_classification(
            blocks, classifications, allowed_labels={QUESTION_PAGE}
        )
        remaining_pages = {b["page"] for b in filtered}
        assert 1 in remaining_pages
        assert 2 not in remaining_pages

    def test_empty_input(self):
        result = classify_pages([])
        assert result == []
        filtered = filter_blocks_by_classification([], [])
        assert filtered == []
