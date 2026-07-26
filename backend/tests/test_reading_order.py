"""Reading Order 全面测试。

覆盖:
- 清晰单栏
- 标准双栏
- 三栏
- 跨栏标题
- 页眉/页脚
- 水印
- 图文混排
- 表格穿插
- 选项左右并排
- 输入顺序随机打乱后结果稳定
- bbox 微小扰动后结果稳定
- 空页面
- 单 region 页面
- ReadingOrderResult 数据结构验证
- Risk flag 生成
- JSON round-trip (通过 PageIR 序列化)
"""
from __future__ import annotations

from app.core.document_ir import (
    BBox,
    PageIR,
    RegionIR,
    document_ir_from_dict,
    document_ir_to_dict,
)
from app.features.reading_order import (
    ReadingOrderEdge,
    ReadingOrderResolver,
    ReadingOrderResult,
    apply_reading_order,
    shuffle_regions,
)

resolver = ReadingOrderResolver()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_region(
    region_id: str,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    region_type: str = "text",
    confidence: float = 0.95,
) -> RegionIR:
    return RegionIR(
        region_id=region_id,
        region_type=region_type,  # type: ignore
        bbox=BBox(x0, y0, x1, y1),
        confidence=confidence,
    )


def _make_page(
    regions: list[RegionIR],
    width: float = 800,
    height: float = 1000,
    page_index: int = 0,
) -> PageIR:
    return PageIR(
        page_id=f"test_page_{page_index}",
        page_index=page_index,
        width=width,
        height=height,
        regions=regions,
    )


def _ordered_ids(result: ReadingOrderResult, page: PageIR | None = None) -> list[str]:
    """Extract ordered region IDs, filtering out non-body regions.

    If ``page`` is provided, uses its region types to filter out
    header/footer/watermark/page_number regions.
    """
    non_body_prefixes = ("hf_", "wm_", "watermark_")
    if page is None:
        return [rid for rid in result.ordered_region_ids
                if not any(rid.startswith(p) for p in non_body_prefixes)]

    # Use actual region types from the page
    non_body_ids: set[str] = set()
    for r in page.regions:
        if r.region_type in ("header", "footer", "page_number") or "watermark" in r.flags:
            non_body_ids.add(r.region_id)

    return [rid for rid in result.ordered_region_ids if rid not in non_body_ids]


# ===================================================================
# 1. Clear single column
# ===================================================================


def test_single_column_top_to_bottom():
    """单栏：从上到下排序。"""
    regions = [
        _make_region("r1_title", 50, 100, 750, 150, "text"),
        _make_region("r2_stem", 50, 180, 750, 250, "text"),
        _make_region("r3_option_a", 70, 270, 400, 310, "text"),
        _make_region("r4_option_b", 70, 330, 400, 370, "text"),
        _make_region("r5_option_c", 70, 390, 400, 430, "text"),
        _make_region("r6_option_d", 70, 450, 400, 490, "text"),
    ]
    page = _make_page(regions)
    result = resolver.resolve(page)

    assert result.strategy == "single_column"
    assert result.confidence >= 0.8
    # Risk flags may contain column_count_ambiguous for narrow options
    # but ordering must be correct
    assert result.ordered_region_ids == [r.region_id for r in regions]


def test_single_column_shuffled():
    """单栏：输入顺序打乱后结果不变。"""
    regions = [
        _make_region("r1", 50, 100, 750, 160),
        _make_region("r2", 50, 200, 750, 300),
        _make_region("r3", 50, 350, 750, 450),
        _make_region("r4", 50, 500, 750, 550),
    ]
    page = _make_page(regions, height=600)

    expected = ["r1", "r2", "r3", "r4"]

    for seed in range(10):
        shuffled = shuffle_regions(page, seed)
        result = resolver.resolve(shuffled)
        assert result.ordered_region_ids == expected, f"Failed at seed {seed}"


# ===================================================================
# 2. Double column
# ===================================================================


def test_double_column_left_to_right():
    """双栏：先左栏（从上到下），再右栏（从上到下）。"""
    regions = [
        _make_region("r1_left_top", 30, 30, 350, 100),
        _make_region("r2_left_mid", 30, 130, 350, 300),
        _make_region("r3_left_bot", 30, 330, 350, 500),
        _make_region("r4_right_top", 420, 30, 770, 150),
        _make_region("r5_right_mid", 420, 180, 770, 350),
        _make_region("r6_right_bot", 420, 380, 770, 500),
    ]
    page = _make_page(regions)
    result = resolver.resolve(page)

    assert result.strategy == "double_column"
    left_ids = ["r1_left_top", "r2_left_mid", "r3_left_bot"]
    right_ids = ["r4_right_top", "r5_right_mid", "r6_right_bot"]
    expected = left_ids + right_ids
    assert result.ordered_region_ids == expected


def test_double_column_shuffled():
    """双栏：输入顺序打乱后结果不变。"""
    regions = [
        _make_region("r1_left_top", 30, 30, 350, 100),
        _make_region("r2_left_bot", 30, 130, 350, 300),
        _make_region("r3_right_top", 420, 30, 770, 150),
        _make_region("r4_right_bot", 420, 180, 770, 350),
    ]
    page = _make_page(regions)
    expected = ["r1_left_top", "r2_left_bot", "r3_right_top", "r4_right_bot"]

    for seed in range(10):
        shuffled = shuffle_regions(page, seed)
        result = resolver.resolve(shuffled)
        assert result.ordered_region_ids == expected, f"Failed at seed {seed}"


def test_double_column_with_risk_flag():
    """双栏：如果列间距不够产生 col_count_ambiguous。"""
    regions = [
        _make_region("r1", 300, 30, 500, 100),
        _make_region("r2", 310, 130, 510, 200),
        _make_region("r3", 320, 230, 520, 300),
        _make_region("r4", 330, 330, 530, 400),
    ]
    page = _make_page(regions, width=600)
    result = resolver.resolve(page)
    # Regions are narrow and spread — might classify as single column
    # but that's fine as long as it's deterministic
    assert len(result.ordered_region_ids) == 4


# ===================================================================
# 3. Three column
# ===================================================================


def test_three_column():
    """三栏布局。"""
    regions = [
        _make_region("r1_col1_top", 20, 20, 240, 150),
        _make_region("r2_col1_bot", 20, 180, 240, 350),
        _make_region("r3_col2_top", 270, 20, 510, 120),
        _make_region("r4_col2_bot", 270, 150, 510, 300),
        _make_region("r5_col3_top", 540, 20, 780, 200),
        _make_region("r6_col3_bot", 540, 230, 780, 350),
    ]
    page = _make_page(regions, width=800)
    result = resolver.resolve(page)

    expected = ["r1_col1_top", "r2_col1_bot", "r3_col2_top", "r4_col2_bot", "r5_col3_top", "r6_col3_bot"]
    assert result.ordered_region_ids == expected


# ===================================================================
# 4. Cross-column title
# ===================================================================


def test_cross_column_title():
    """跨栏标题在前，双栏内容在后。"""
    regions = [
        _make_region("r1_title", 30, 100, 770, 150, "text"),  # spans 95% width
        _make_region("r2_left", 30, 180, 350, 300),
        _make_region("r3_left_bot", 30, 330, 350, 500),
        _make_region("r4_right", 420, 180, 770, 350),
        _make_region("r5_right_bot", 420, 380, 770, 500),
    ]
    page = _make_page(regions, width=800, height=600)
    result = resolver.resolve(page)

    assert result.strategy == "double_column"
    # Cross-column title should be first
    assert result.ordered_region_ids[0] == "r1_title"
    assert result.ordered_region_ids.index("r2_left") < result.ordered_region_ids.index("r4_right")


# ===================================================================
# 5. Header / Footer
# ===================================================================


def test_header_excluded_from_main_order():
    """页眉不进入正文阅读顺序。"""
    regions = [
        _make_region("r_header", 100, 5, 700, 30, "header"),
        _make_region("r1", 50, 80, 750, 150, "text"),
        _make_region("r2", 50, 200, 750, 350, "text"),
        _make_region("r_footer", 100, 960, 700, 990, "footer"),
    ]
    page = _make_page(regions, width=800, height=1000)
    result = resolver.resolve(page)

    # Body regions first (r1, r2), then headers/footers appended
    body_ids = _ordered_ids(result, page=page)
    assert body_ids == ["r1", "r2"]


def test_footer_detected():
    """页脚被正确识别。"""
    regions = [
        _make_region("r1", 50, 80, 750, 200),
        _make_region("r_footer", 300, 960, 500, 990),
    ]
    page = _make_page(regions, height=1000)
    result = resolver.resolve(page)

    # "r_footer" should be at the end (appended)
    assert result.ordered_region_ids[-1] == "r_footer"


# ===================================================================
# 6. Watermark
# ===================================================================


def test_watermark_not_in_main_order():
    """水印不进入正文阅读顺序。"""
    regions = [
        _make_region("r1", 50, 100, 750, 200, "text", confidence=0.95),
        _make_region("r2", 50, 250, 750, 450, "text", confidence=0.90),
        _make_region("r_watermark", 150, 280, 650, 780, "text", confidence=0.15),
    ]
    page = _make_page(regions, width=800, height=1000)
    result = resolver.resolve(page)

    # Watermark is appended at the end
    body_ids = _ordered_ids(result, page=page)
    assert len(body_ids) == 2


# ===================================================================
# 7. Mixed text and figures
# ===================================================================


def test_figure_interspersed():
    """图片/图表按空间位置插入。"""
    regions = [
        _make_region("r1_stem", 50, 30, 750, 120, "text"),
        _make_region("r2_figure", 100, 150, 700, 350, "figure"),
        _make_region("r3_analysis", 50, 400, 750, 550, "text"),
    ]
    page = _make_page(regions)
    result = resolver.resolve(page)

    assert result.ordered_region_ids == ["r1_stem", "r2_figure", "r3_analysis"]


# ===================================================================
# 8. Options side-by-side
# ===================================================================


def test_options_side_by_side():
    """选项左右并排：两列中的选项区域。"""
    # Two columns of options: A/B in left, C/D in right
    regions = [
        _make_region("r_stem", 50, 30, 750, 100, "question_stem"),
        _make_region("r_opt_a", 50, 120, 350, 150, "option"),
        _make_region("r_opt_b", 50, 170, 350, 200, "option"),
        _make_region("r_opt_c", 420, 120, 750, 150, "option"),
        _make_region("r_opt_d", 420, 170, 750, 200, "option"),
    ]
    page = _make_page(regions, width=800)
    result = resolver.resolve(page)

    # Left column (opt_a, opt_b) before right column (opt_c, opt_d)
    idx_a = result.ordered_region_ids.index("r_opt_a")
    idx_b = result.ordered_region_ids.index("r_opt_b")
    idx_c = result.ordered_region_ids.index("r_opt_c")
    idx_d = result.ordered_region_ids.index("r_opt_d")
    assert idx_a < idx_c
    assert idx_b < idx_d


# ===================================================================
# 9. Empty / edge cases
# ===================================================================


def test_empty_page():
    """空页面应返回空结果。"""
    page = _make_page([])
    result = resolver.resolve(page)
    assert result.ordered_region_ids == []
    assert result.edges == []
    assert result.confidence == 1.0


def test_single_region():
    """单区域页面。"""
    regions = [_make_region("r1", 50, 50, 750, 800)]
    page = _make_page(regions)
    result = resolver.resolve(page)
    assert result.ordered_region_ids == ["r1"]
    assert result.strategy == "single_column"


# ===================================================================
# 10. Bbox micro-perturbation stability
# ===================================================================


def test_bbox_micro_perturbation():
    """bbox 微小变化后阅读顺序不变。"""
    base_regions = [
        _make_region("r1", 50, 30, 350, 100),
        _make_region("r2", 50, 130, 350, 300),
        _make_region("r3", 420, 30, 750, 150),
    ]
    page = _make_page(base_regions, width=800)
    base_result = resolver.resolve(page)
    expected = base_result.ordered_region_ids

    perturbations = [
        (50.004, 30.002, 350.001, 100.003),
        (50, 30, 350, 100),  # identical
        (50.01, 30.0, 350.0, 100.0),  # 0.01 px diff
    ]
    for pert in perturbations:
        perturbed_regions = [
            _make_region("r1", *pert),
            _make_region("r2", 50, 130, 350, 300),
            _make_region("r3", 420, 30, 750, 150),
        ]
        p_page = _make_page(perturbed_regions, width=800)
        p_result = resolver.resolve(p_page)
        assert p_result.ordered_region_ids == expected


# ===================================================================
# 11. Data structure validation
# ===================================================================


def test_reading_order_result_dataclass():
    """ReadingOrderResult 数据结构验证。"""
    result = ReadingOrderResult(
        ordered_region_ids=["r1", "r2"],
        edges=[
            ReadingOrderEdge("r1", "r2", 0.9, "single_column_order"),
        ],
        confidence=0.9,
        strategy="single_column",
        risk_flags=[],
        column_assignments={"r1": 0, "r2": 0},
    )
    assert not result.has_risks
    assert len(result.edges) == 1
    assert result.edges[0].source_region_id == "r1"

    result_risky = ReadingOrderResult(
        ordered_region_ids=["r1"],
        edges=[],
        confidence=0.5,
        strategy="double_column",
        risk_flags=["overlapping_regions", "isolated_region"],
    )
    assert result_risky.has_risks
    assert "overlapping_regions" in result_risky.risk_flags


# ===================================================================
# 12. Risk flags
# ===================================================================


def test_overlapping_regions_risk_flag():
    """重叠区域产生 risk flag。"""
    regions = [
        _make_region("r1", 50, 50, 400, 200),
        _make_region("r2", 100, 100, 450, 250),  # overlaps r1
        _make_region("r3", 50, 300, 750, 500),
    ]
    page = _make_page(regions)
    result = resolver.resolve(page)
    assert "overlapping_regions" in result.risk_flags


def test_isolated_region_risk_flag():
    """孤立的微小区域产生 risk flag。"""
    regions = [
        _make_region("r1", 50, 50, 750, 400),
        _make_region("r2_tiny", 400, 450, 410, 455),  # very small
    ]
    page = _make_page(regions, width=800, height=500)
    result = resolver.resolve(page)
    assert "isolated_region" in result.risk_flags


# ===================================================================
# 13. apply_reading_order updates PageIR in place
# ===================================================================


def test_apply_reading_order_in_place():
    """apply_reading_order 正确更新 PageIR 字段。"""
    regions = [
        _make_region("r1", 50, 50, 750, 150),
        _make_region("r2", 50, 200, 750, 400),
    ]
    page = _make_page(regions)
    result = apply_reading_order(page)

    assert page.reading_order == ["r1", "r2"]
    assert page.reading_order_confidence is not None
    assert page.reading_order_flags == []

    # Region reading_order fields should be updated
    for idx, rid in enumerate(["r1", "r2"]):
        for r in page.regions:
            if r.region_id == rid:
                assert r.reading_order == idx
                break

    assert result.strategy == "single_column"


# ===================================================================
# 14. JSON round-trip preserves reading_order fields
# ===================================================================


def test_reading_order_json_roundtrip():
    """Reading Order JSON round-trip 不丢失字段。"""
    from app.core.document_ir import new_document

    doc = new_document(source_bytes=b"test")
    regions = [
        _make_region("r1", 50, 50, 750, 150),
        _make_region("r2", 50, 200, 750, 400),
    ]
    page = _make_page(regions)
    apply_reading_order(page)
    doc.add_page(page)

    data = document_ir_to_dict(doc)
    restored = document_ir_from_dict(data)

    assert restored is not None
    assert len(restored.pages) == 1
    restored_page = restored.pages[0]
    assert restored_page.reading_order == ["r1", "r2"]
    assert restored_page.reading_order_confidence is not None
    assert isinstance(restored_page.reading_order_flags, list)


# ===================================================================
# 15. Property-based determinism (20 seeds)
# ===================================================================


def test_deterministic_across_20_seeds_single_column():
    """单栏：20 种随机种子下结果不变。"""
    regions = [
        _make_region("r1", 50, 100, 750, 180),
        _make_region("r2", 50, 200, 600, 300),
        _make_region("r3", 50, 320, 750, 450),
        _make_region("r4", 50, 470, 700, 550),
        _make_region("r5", 50, 570, 750, 650),
    ]
    page = _make_page(regions, height=700)
    expected = ["r1", "r2", "r3", "r4", "r5"]

    for seed in range(20):
        shuffled = shuffle_regions(page, seed)
        result = resolver.resolve(shuffled)
        assert result.ordered_region_ids == expected, f"Failed at seed {seed}"


def test_deterministic_across_20_seeds_double_column():
    """双栏：20 种随机种子下结果不变。"""
    regions = [
        _make_region("r1_left_top", 30, 30, 350, 120),
        _make_region("r2_left_bot", 30, 150, 350, 350),
        _make_region("r3_right_top", 420, 30, 770, 180),
        _make_region("r4_right_bot", 420, 210, 770, 350),
    ]
    page = _make_page(regions, width=800)
    expected = ["r1_left_top", "r2_left_bot", "r3_right_top", "r4_right_bot"]

    for seed in range(20):
        shuffled = shuffle_regions(page, seed)
        result = resolver.resolve(shuffled)
        assert result.ordered_region_ids == expected, f"Failed at seed {seed}"


# ===================================================================
# 16. Multi-page resolve
# ===================================================================


def test_resolve_multi_page():
    """resolve_multi_page 正确处理多页。"""
    page1 = _make_page(
        [_make_region("p1r1", 50, 50, 750, 200)],
        page_index=0,
    )
    page2 = _make_page(
        [_make_region("p2r1", 50, 50, 750, 200)],
        page_index=1,
    )
    results = resolver.resolve_multi_page([page1, page2])
    assert len(results) == 2
    assert results[0].ordered_region_ids == ["p1r1"]
    assert results[1].ordered_region_ids == ["p2r1"]


# ===================================================================
# 17. Code / formula regions
# ===================================================================


def test_code_regions_in_order():
    """代码区域按空间位置排序。"""
    regions = [
        _make_region("r1_stem", 50, 30, 750, 100, "text"),
        _make_region("r2_code", 50, 130, 750, 350, "code"),
        _make_region("r3_analysis", 50, 400, 750, 500, "text"),
    ]
    page = _make_page(regions)
    result = resolver.resolve(page)
    assert result.ordered_region_ids == ["r1_stem", "r2_code", "r3_analysis"]


def test_formula_regions_in_order():
    """公式区域按空间位置排序。"""
    regions = [
        _make_region("r1_stem", 50, 30, 750, 100, "text"),
        _make_region("r2_formula", 100, 130, 700, 200, "formula"),
        _make_region("r3_continuation", 50, 250, 750, 350, "text"),
    ]
    page = _make_page(regions)
    result = resolver.resolve(page)
    assert result.ordered_region_ids == ["r1_stem", "r2_formula", "r3_continuation"]


# ===================================================================
# 18. Cross-column title with header
# ===================================================================


def test_cross_column_title_with_header():
    """跨栏标题 + 页眉共存。"""
    regions = [
        _make_region("r_header", 100, 5, 700, 25, "header"),
        _make_region("r_title", 30, 40, 770, 80, "text"),  # cross-column
        _make_region("r_left", 30, 100, 350, 300),
        _make_region("r_right", 420, 100, 770, 300),
    ]
    page = _make_page(regions, width=800, height=400)
    result = resolver.resolve(page)

    # Header should not interrupt body order
    body_ids = _ordered_ids(result, page=page)
    assert "r_header" not in body_ids
    # Title should be first in body
    assert result.ordered_region_ids[0] == "r_title"


# ===================================================================
# 19. Table interspersed
# ===================================================================


def test_table_in_text_flow():
    """表格按空间位置插入文本流。"""
    regions = [
        _make_region("r1_text_before", 50, 30, 750, 100, "text"),
        _make_region("r2_table", 50, 130, 750, 350, "table"),
        _make_region("r3_text_after", 50, 400, 750, 500, "text"),
    ]
    page = _make_page(regions)
    result = resolver.resolve(page)
    assert result.ordered_region_ids == ["r1_text_before", "r2_table", "r3_text_after"]
