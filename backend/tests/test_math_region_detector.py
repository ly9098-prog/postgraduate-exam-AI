"""数学区域检测单元测试"""
import os
import sys

import fitz
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.math_region_detector import (
    MathRegion,
    MathRegionType,
    detect_document,
    detect_from_ocr_boxes,
    detect_page,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _page_text(page):
    """Count formula-like numbered items on a page."""
    import re
    text = page.get_text()
    return len(re.findall(r"\d+\.\s", text))


# ── T01: LaTeX 自制 — 召回率 ≥ 60% ──────────────────────────────────────────

def test_t01_latex_recall():
    """T01 含积分/极限/矩阵，每页应检出 ≥ 60% 的公式行。"""
    path = os.path.join(FIXTURES, "t01_latex_math.pdf")
    doc = fitz.open(path)
    result = detect_document(doc)

    assert len(result) > 0, "应至少在一页检出公式区域"

    total_regions = 0
    total_formula_lines = 0

    for pn in range(len(doc)):
        regions = result.get(pn, [])
        total_regions += len(regions)
        # Count formula-like lines on this page
        text = doc[pn].get_text()
        import re
        formula_lines = len(re.findall(r"\d+\.\s", text))
        total_formula_lines += formula_lines

    doc.close()

    # 至少检出 10 个区域（总共 ~17 个公式行）
    assert total_regions >= 10, f"T01 召回不足：{total_regions} regions, {total_formula_lines} formula lines"

    # 检查区域类型分布
    all_regions = []
    for regions in result.values():
        all_regions.extend(regions)

    types = set(r.region_type for r in all_regions)
    assert len(types) >= 1, "应有至少一种区域类型"


# ── T02: MathType 导出 — 召回率 ≥ 50% ─────────────────────────────────────

def test_t02_mathtype_recall():
    """T02 含混合字体公式，召回率应 ≥ 50%。"""
    path = os.path.join(FIXTURES, "t02_mathtype_export.pdf")
    doc = fitz.open(path)
    result = detect_document(doc)

    total_regions = sum(len(v) for v in result.values())
    assert total_regions >= 8, f"T02 召回不足：{total_regions} regions"

    doc.close()


# ── T03: ASCII 表达式 — 误检率 ≤ 10% ──────────────────────────────────────

def test_t03_ascii_false_positive():
    """T03 为纯 ASCII 表达式，不应触发 Unicode 数学检测。"""
    path = os.path.join(FIXTURES, "t03_ascii_formula.pdf")
    doc = fitz.open(path)
    result = detect_document(doc)

    total_regions = sum(len(v) for v in result.values())

    # T03 全是 ASCII，应该极低检测
    # 10% 误检率：~15 行 → 最多 1-2 个误检
    assert total_regions <= 2, f"T03 误检过多：{total_regions} regions"

    doc.close()


# ── 无公式页面：误检 = 0 ──────────────────────────────────────────────────

def test_no_formula_page_zero_false_positive():
    """纯文字页面应返回 0 个数学区域。"""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_htmlbox((50, 50, 500, 300),
        "<h2>操作系统概述</h2>"
        "<p>操作系统是计算机系统中最基本的系统软件，它管理系统资源，"
        "控制程序执行，并为用户提供各种服务界面。</p>"
        "<p>常见的桌面操作系统包括 Windows、Linux 和 macOS。"
        "服务器端以 Linux 为主，移动端则以 Android 和 iOS 为主。</p>"
        "<p>在考研中，操作系统是 408 统考的重要组成部分。</p>")
    regions = detect_page(page)
    doc.close()
    assert len(regions) == 0, f"纯文字页面误检了 {len(regions)} 个区域"


# ── 空白页面 / 无文字层：返回空列表 ──────────────────────────────────────

def test_blank_page_no_text_layer():
    """扫描版 PDF（无文字层的空白页）应返回空列表。"""
    doc = fitz.open()
    page = doc.new_page()  # 空页面
    regions = detect_page(page)
    doc.close()
    assert regions == [], f"空白页面应返回空列表，实际 {len(regions)}"


# ── 异常降级：任意输入不抛异常 ────────────────────────────────────────────

def test_no_exception_on_edge_cases():
    """各种边界条件不抛出异常。"""
    # 只含图片的 PDF（无文字块）
    doc = fitz.open()
    page = doc.new_page()
    # 插入一个矩形（图片型 block），无文字
    page.draw_rect([50, 50, 200, 200])
    try:
        regions = detect_page(page)
        assert isinstance(regions, list)
    except Exception as e:
        pytest.fail(f"图片型页面不应抛异常：{e}")
    doc.close()


# ── detect_document 多页检测 ──────────────────────────────────────────────

def test_detect_document_pages_filter():
    """detect_document 支持 pages 参数筛选。"""
    path = os.path.join(FIXTURES, "t01_latex_math.pdf")
    doc = fitz.open(path)

    # 只检测第 0 页
    result = detect_document(doc, pages=[0])
    assert 0 in result
    assert len(result) == 1

    # 空列表
    result = detect_document(doc, pages=[])
    assert result == {}

    # None = 全部页
    result = detect_document(doc, pages=None)
    assert len(result) >= 1

    doc.close()


# ── MathRegion 区域类型 ────────────────────────────────────────────────────

def test_math_region_dataclass():
    """MathRegion 数据类字段完整性。"""
    r = MathRegion(
        page_num=1,
        bbox=(10.0, 20.0, 100.0, 40.0),
        region_type=MathRegionType.INLINE,
        raw_latex=r"\int_a^b",
        image_url=None,
    )
    assert r.page_num == 1
    assert r.bbox == (10.0, 20.0, 100.0, 40.0)
    assert r.region_type == MathRegionType.INLINE
    assert r.raw_latex == r"\int_a^b"
    assert r.image_url is None


# ── 区域分类类型覆盖 ──────────────────────────────────────────────────────

def test_region_type_detection_variety():
    """T01+T02 应包含多种区域类型（inline 至少存在）。"""
    all_types = set()
    for fname in ["t01_latex_math.pdf", "t02_mathtype_export.pdf"]:
        path = os.path.join(FIXTURES, fname)
        doc = fitz.open(path)
        result = detect_document(doc)
        for regions in result.values():
            for r in regions:
                all_types.add(r.region_type)
        doc.close()

    assert MathRegionType.INLINE in all_types, "应至少检测到行内公式"


# ── 区域 bbox 合法性 ──────────────────────────────────────────────────────

def test_bbox_validity():
    """所有检测到的 bbox 应合法（x1>x0, y1>y0，非负）。"""
    for fname in ["t01_latex_math.pdf", "t02_mathtype_export.pdf"]:
        path = os.path.join(FIXTURES, fname)
        doc = fitz.open(path)
        result = detect_document(doc)
        for pn, regions in result.items():
            page_w = doc[pn].rect.width
            page_h = doc[pn].rect.height
            for r in regions:
                x0, y0, x1, y1 = r.bbox
                assert x1 > x0, f"bbox x1 <= x0: {r.bbox}"
                assert y1 > y0, f"bbox y1 <= y0: {r.bbox}"
                assert x0 >= 0, f"bbox x0 < 0: {r.bbox}"
                assert y0 >= 0, f"bbox y0 < 0: {r.bbox}"
                assert x1 <= page_w + 20, f"bbox x1 out of range: {r.bbox}"  # padding 可超出一点
                assert y1 <= page_h + 20, f"bbox y1 out of range: {r.bbox}"
        doc.close()


# ── Stage 5：detect_from_ocr_boxes 聚类分支 ───────────────────────────────────

def test_detect_from_ocr_boxes_basic():
    """正常 boxes 输入应返回聚类后的 MathRegion 列表。"""
    boxes = [
        {"bbox": [10, 10, 100, 30], "conf": 0.9},
        {"bbox": [110, 10, 200, 30], "conf": 0.85},  # 与上一个同行，间距 10px < eps=15
        {"bbox": [10, 60, 150, 80], "conf": 0.8},    # 另一行
    ]
    regions = detect_from_ocr_boxes(boxes, page_height=300)
    assert isinstance(regions, list)
    assert len(regions) >= 1


def test_detect_from_ocr_boxes_all_mixed_type():
    """扫描版检测结果 region_type 应全为 MIXED。"""
    boxes = [
        {"bbox": [0, 0, 200, 30], "conf": 0.9},
        {"bbox": [0, 50, 200, 80], "conf": 0.9},
    ]
    regions = detect_from_ocr_boxes(boxes, page_height=300)
    for r in regions:
        assert r.region_type == MathRegionType.MIXED, f"期望 MIXED，实际 {r.region_type}"


def test_detect_from_ocr_boxes_filters_thin_boxes():
    """宽高比 > 5:1 的细条应被过滤（如水平分割线）。"""
    boxes = [
        {"bbox": [0, 50, 500, 55], "conf": 0.9},  # 宽500，高5，宽高比100:1 → 过滤
        {"bbox": [10, 100, 100, 130], "conf": 0.9},  # 正常框
    ]
    regions = detect_from_ocr_boxes(boxes, page_height=300)
    # 只有正常框能产生区域
    assert len(regions) >= 1
    # 细条不应产生宽度极大的区域
    for r in regions:
        w = r.bbox[2] - r.bbox[0]
        assert w < 450, f"细条误检入结果：bbox={r.bbox}"


def test_detect_from_ocr_boxes_filters_tiny_height():
    """高度 < 8px 的框应被过滤。"""
    boxes = [
        {"bbox": [0, 0, 50, 5], "conf": 0.9},   # 高 5px → 过滤
        {"bbox": [0, 50, 50, 70], "conf": 0.9},  # 正常
    ]
    regions = detect_from_ocr_boxes(boxes, page_height=300)
    assert len(regions) >= 1
    for r in regions:
        h = r.bbox[3] - r.bbox[1]
        assert h >= 8, f"过矮框误检入结果：bbox={r.bbox}"


def test_detect_from_ocr_boxes_empty_input():
    """空输入应返回空列表，不抛异常。"""
    assert detect_from_ocr_boxes([], page_height=300) == []


def test_detect_from_ocr_boxes_invalid_bbox():
    """bbox 格式不合法时不抛异常，跳过该框。"""
    boxes = [
        {"bbox": [], "conf": 0.9},            # 空 bbox
        {"bbox": [10, 10, 100, 30], "conf": 0.9},  # 正常
    ]
    try:
        regions = detect_from_ocr_boxes(boxes, page_height=300)
        assert isinstance(regions, list)
    except Exception as e:
        pytest.fail(f"非法 bbox 不应抛异常: {e}")


def test_detect_from_ocr_boxes_nearby_boxes_merged():
    """同行间距 < 15px 的相邻框应合并为一个区域。"""
    boxes = [
        {"bbox": [10, 10,  80, 30], "conf": 0.9},
        {"bbox": [85, 10, 160, 30], "conf": 0.9},  # 间距 5px < eps=15 → 同一 cluster
        {"bbox": [200, 10, 280, 30], "conf": 0.9}, # 间距 40px > eps=15 → 另一 cluster
    ]
    regions = detect_from_ocr_boxes(boxes, page_height=300)
    # 第一行应产生 2 个聚类
    row_regions = [r for r in regions if r.bbox[1] < 40]
    assert len(row_regions) == 2, f"期望 2 个聚类，实际 {len(row_regions)}: {[r.bbox for r in row_regions]}"


def test_detect_from_ocr_boxes_no_exception_on_any_input():
    """任意输入不抛异常（鲁棒性测试）。"""
    cases = [
        [{"bbox": [0, 0, 10, 5], "conf": 0.1}],                # 高度不足
        [{"conf": 0.9}],                                          # 无 bbox 键
        [{"bbox": None, "conf": 0.9}],                            # bbox 为 None
        [{"bbox": [100, 100, 50, 50], "conf": 0.9}],             # 坐标倒置
    ]
    for boxes in cases:
        try:
            result = detect_from_ocr_boxes(boxes, page_height=300)
            assert isinstance(result, list)
        except Exception as e:
            pytest.fail(f"输入 {boxes} 不应抛异常: {e}")
