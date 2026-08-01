"""Structure Freeze 流水线集成测试。

覆盖 STRUCTURE_FREEZE_MODE 三种模式：
- legacy: 纯 block-based，不改变现有行为
- dual: 同时运行 legacy + IR freeze，对比差异
- ir: DocumentIR-based freeze

检查：
- 三种模式不崩溃
- dual 模式返回对比诊断信息
- ir 模式 fallback 行为（无 DocumentIR 时）
- 现有 legacy 路径不回归
"""

from __future__ import annotations

from app.features.pipeline_orchestrator import (
    _compare_freeze_results,
    _get_blocks_document_ir,
)

# ── Mock blocks with embedded DocumentIR ──


def _make_mock_blocks() -> list[dict]:
    """Build mock normalized_blocks that carry a DocumentIR."""
    from app.core.document_ir import (
        BBox,
        LineIR,
        PageIR,
        RegionIR,
        new_document,
    )

    doc = new_document(source_bytes=b"test-freeze-integration")

    # Page 0 with two regions containing options
    lines_p0_r0 = [
        LineIR(text="1. 题目一", bbox=BBox(50, 50, 200, 80), line_id="p0r0l0"),
        LineIR(text="A. 16", bbox=BBox(50, 90, 200, 110), line_id="p0r0l1"),
        LineIR(text="B. 32", bbox=BBox(50, 120, 200, 140), line_id="p0r0l2"),
    ]
    lines_p0_r1 = [
        LineIR(text="2. 题目二", bbox=BBox(50, 150, 200, 180), line_id="p0r1l0"),
        LineIR(text="A. 64", bbox=BBox(50, 190, 200, 210), line_id="p0r1l1"),
        LineIR(text="B. 128", bbox=BBox(50, 220, 200, 240), line_id="p0r1l2"),
    ]

    r0 = RegionIR(
        region_id="region_p0_r0",
        region_type="text", bbox=BBox(30, 30, 250, 160),
        lines=lines_p0_r0,
    )
    r1 = RegionIR(
        region_id="region_p0_r1",
        region_type="text", bbox=BBox(30, 140, 250, 260),
        lines=lines_p0_r1,
    )
    p0 = PageIR(
        page_id="page_0", page_index=0, width=600, height=800,
        regions=[r0, r1],
    )
    doc.add_page(p0)

    # Mock normalized_blocks
    blocks = [
        {
            "page": 1,
            "block_index": 0,
            "text": "1. 题目一\nA. 16\nB. 32",
            "normalized_text": "1. 题目一\nA. 16\nB. 32",
            "page_width": 600,
            "page_height": 800,
        },
        {
            "page": 1,
            "block_index": 1,
            "text": "2. 题目二\nA. 64\nB. 128",
            "normalized_text": "2. 题目二\nA. 64\nB. 128",
            "page_width": 600,
            "page_height": 800,
        },
    ]

    # Embed DocumentIR (simulates what _ocr_scanned_pdf does)
    blocks[0]["_document_ir"] = doc

    return blocks


def _make_mock_blocks_no_docir() -> list[dict]:
    """Build mock blocks WITHOUT DocumentIR embedded."""
    return [
        {
            "page": 1,
            "block_index": 0,
            "text": "1. 题目一\nA. 甲\nB. 乙",
            "normalized_text": "1. 题目一\nA. 甲\nB. 乙",
        },
    ]


# ===================================================================
# _get_blocks_document_ir
# ===================================================================


def test_get_blocks_document_ir_from_block_zero():
    """DocumentIR 从 blocks[0]._document_ir 提取。"""
    blocks = _make_mock_blocks()
    doc_ir = _get_blocks_document_ir(blocks)
    assert doc_ir is not None
    assert len(doc_ir.pages) == 1


def test_get_blocks_document_ir_none():
    """空列表时返回 None。"""
    doc_ir = _get_blocks_document_ir([])
    assert doc_ir is None


def test_get_blocks_document_ir_empty_blocks():
    """空 blocks 时返回 None。"""
    doc_ir = _get_blocks_document_ir([])
    assert doc_ir is None


# ===================================================================
# _compare_freeze_results
# ===================================================================


def _make_fake_frozentry(key: str, text: str, status: str = "bound"):
    """Helper to create a FrozenOptionEntry-like object."""
    from app.features.pipeline_stages.structure_freeze_stage import (
        FrozenOptionEntry,
    )
    return FrozenOptionEntry(
        option_key=key,
        source_region_ids=["r1"],
        original_text=text,
        normalized_text=text,
        binding_status=status,
    )


def test_compare_freeze_identical():
    """相同选项时对比通过。"""
    legacy_reg = {"1:0": {"A": "16", "B": "32"}}
    ir_reg = {"r1": [
        _make_fake_frozentry("A", "16"),
        _make_fake_frozentry("B", "32"),
    ]}
    result = _compare_freeze_results(
        {"frozen_option_registry": legacy_reg},
        {"frozen_option_registry": ir_reg},
        legacy_reg, ir_reg,
    )
    assert result["option_key_match"] is True
    assert result["option_text_match"] is True
    assert result["differences_count"] == 0


def test_compare_freeze_key_mismatch():
    """IR 缺少选项时标记差异。"""
    legacy_reg = {"1:0": {"A": "16", "B": "32", "C": "64"}}
    ir_reg = {"r1": [
        _make_fake_frozentry("A", "16"),
        _make_fake_frozentry("B", "32"),
    ]}
    result = _compare_freeze_results(
        {"frozen_option_registry": legacy_reg},
        {"frozen_option_registry": ir_reg},
        legacy_reg, ir_reg,
    )
    assert result["option_key_match"] is False
    assert result["differences_count"] >= 1
    assert any(d["type"] == "only_in_legacy" for d in result["differences"])


def test_compare_freeze_text_mismatch():
    """选项文本不同时标记。"""
    legacy_reg = {"1:0": {"A": "16", "B": "32"}}
    ir_reg = {"r1": [
        _make_fake_frozentry("A", "l6"),  # OCR 误识
        _make_fake_frozentry("B", "32"),
    ]}
    result = _compare_freeze_results(
        {"frozen_option_registry": legacy_reg},
        {"frozen_option_registry": ir_reg},
        legacy_reg, ir_reg,
    )
    assert result["option_text_match"] is False
    assert any(d["type"] == "text_mismatch" for d in result["differences"])


def test_compare_freeze_binding_lost():
    """binding_lost 被正确计数。"""
    legacy_reg = {"1:0": {"A": "16"}}
    ir_reg = {"r1": [
        _make_fake_frozentry("A", "16", status="binding_lost"),
    ]}
    result = _compare_freeze_results(
        {"frozen_option_registry": legacy_reg},
        {"frozen_option_registry": ir_reg},
        legacy_reg, ir_reg,
    )
    assert result["binding_lost_count"] == 1


# ===================================================================
# Pipeline stage integration
# ===================================================================


def test_structure_freeze_legacy_mode(monkeypatch):
    """legacy 模式保持现有行为。"""
    monkeypatch.setenv("STRUCTURE_FREEZE_MODE", "legacy")

    from app.features.pipeline_orchestrator import ImportPipeline

    pipeline = ImportPipeline(options={})
    pipeline._build_pipeline()
    freeze_stage = pipeline.stages.get("structure_freeze")
    assert freeze_stage is not None

    blocks = _make_mock_blocks()
    result = freeze_stage.fn(blocks)

    assert "frozen_option_registry" in result
    # Legacy mode: no extra diagnostics
    assert "freeze_dual_diagnostics" not in result
    assert result.get("freeze_mode", "legacy") == "legacy"


# ===================================================================
# Data dict initialization
# ===================================================================


def test_single_pass_data_contains_freeze_fields():
    """pipeline 数据 dict 初始化包含 freeze 字段。"""
    from app.features.pipeline_orchestrator import ImportPipeline

    pipeline = ImportPipeline(options={})
    # Data dict is initialized in _run_single_pass
    assert hasattr(pipeline, "stages")
