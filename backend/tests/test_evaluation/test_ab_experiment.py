"""A/B 对照实验 — 验证 layout-aware routing 是否提升 split 质量。

在受控环境下对比 baseline（强制 standard） vs experiment（layout routing）：
- 使用 mock pipeline + 已知 layout 特征的 normalized_blocks
- 不依赖真实 PDF/OCR/数据库
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from app.features.pipeline_orchestrator import ImportPipeline
from tests.test_services.test_pipeline_orchestrator import (
    _make_mock_db,
    _make_normalized_blocks,
    _make_raw_questions,
)


def _make_normalized_blocks_with_bbox(
    n: int,
    *,
    layout_confidence: float = 0.85,
    has_option_patterns: bool = True,
) -> list[dict]:
    """Create normalized blocks with bbox + option content for layout reconstruction."""
    import random
    blocks = []
    for i in range(n):
        page = i // 5 + 1
        line_y = (i % 5) * 60
        bbox = [50, line_y, 750, line_y + 30]

        text = f"{i+1}. Question {i+1} stem text."
        if has_option_patterns:
            text += "\n"
            for k in ["A.", "B.", "C.", "D."]:
                text += f"{k} Option {k} text for question {i+1}  "

        blocks.append({
            "page": page,
            "block_index": i,
            "page_width": 800,
            "page_height": 1200,
            "raw_text": text,
            "normalized_text": text,
            "boxes": [{"bbox": bbox, "conf": layout_confidence}],
        })
    return blocks


def _make_pipeline_with_routing(
    *,
    split_mode: str | None = None,  # None = use router, otherwise force mode
    layout_confidence: float = 0.85,
    option_detection_score: float = 0.9,
    option_detection_failed: bool = False,
    question_count: int = 5,
    question_options: bool = True,
) -> ImportPipeline:
    """Create a pipeline with controlled routing and split behavior."""
    pipeline = ImportPipeline(options={})

    # Resolve effective split mode (use router if not forced)
    effective_split_mode = split_mode
    if effective_split_mode is None:
        from app.features.layout_router import evaluate_routing
        effective_split_mode = evaluate_routing({
            "layout_confidence": layout_confidence,
            "option_detection_score": option_detection_score,
            "option_detection_failed": option_detection_failed,
        })

    pipeline._run_extract = MagicMock(return_value={
        "raw_blocks": [],
        "extracted": 0,
    })
    pipeline._run_normalize_text = MagicMock(return_value={
        "normalized_blocks": _make_normalized_blocks_with_bbox(
            question_count,
            layout_confidence=layout_confidence,
            has_option_patterns=question_options,
        ),
    })
    pipeline._run_ocr_correction = MagicMock(return_value={
        "normalized_blocks": _make_normalized_blocks_with_bbox(
            question_count,
            layout_confidence=layout_confidence,
            has_option_patterns=question_options,
        ),
        "ocr_correction_diagnostics": {"stats": {}, "corrections": [], "skipped_reason": None},
    })

    # Layout reconstruction returns controlled confidence
    pipeline._run_layout_reconstruction = MagicMock(return_value={
        "normalized_blocks": _make_normalized_blocks_with_bbox(
            question_count,
            layout_confidence=layout_confidence,
            has_option_patterns=question_options,
        ),
        "layout_result": {
            "layout_blocks": [],
            "option_groups": {"1": {"A": "x", "B": "y", "C": "z", "D": "w"}},
            "layout_confidence": layout_confidence,
            "option_detection_score": option_detection_score,
            "option_detection_failed": option_detection_failed,
            "reading_order": [],
            "warnings": [],
        },
        "layout_confidence": layout_confidence,
    })

    # Layout router mock returns the resolved split_mode
    pipeline._run_layout_router = MagicMock(return_value={
        "split_mode": effective_split_mode,
    })

    # Split produces questions with configurable option presence
    raw_qs = []
    for i in range(question_count):
        q = {
            "number": i + 1,
            "raw_question_text": f"Question {i+1} text",
            "page_start": 1,
            "page_end": 1,
            "has_options": question_options,
            "option_lines": {"A": "x", "B": "y", "C": "z", "D": "w"} if question_options else {},
            "confidence": layout_confidence,
            "risk_flags": [],
        }
        raw_qs.append(q)

    pipeline._run_split = MagicMock(return_value={
        "raw_questions": raw_qs,
        "split_count": len(raw_qs),
        "split_diagnostics": {
            "split_mode": effective_split_mode,
            "normalized_block_count": question_count,
            "text_block_count": question_count,
            "raw_question_count": len(raw_qs),
            "book_prose_downgraded": 0,
        },
    })

    pipeline._run_match = MagicMock(return_value={
        "matched": [],
        "unmatched": [],
        "matched_count": 0,
    })
    pipeline._run_normalize_schema = MagicMock(return_value={
        "questions": [],
        "normalized_count": 0,
    })
    pipeline._run_repair = MagicMock(return_value={
        "questions": [],
        "repaired_count": 0,
        "unrepaired_count": 0,
        "skipped_count": 0,
        "total_tokens": 0,
    })
    pipeline._run_ai_validation = MagicMock(return_value={
        "questions": [],
        "ai_validation_diagnostics": {},
    })
    pipeline._run_similarity_match = MagicMock(return_value={
        "questions": [],
        "similarity_match_diagnostics": {},
    })
    pipeline._run_review = MagicMock(return_value={
        "batch_id": "AB_TEST",
        "written": 0,
        "skipped": 0,
        "total": 0,
    })
    pipeline._run_batch_validation = MagicMock(return_value={
        "questions": [],
        "batch_validation_diagnostics": {},
    })
    pipeline._run_batch_dedup = MagicMock(return_value={
        "questions": [],
    })
    pipeline._run_math_detect = MagicMock(return_value={
        "questions": [],
    })
    pipeline._run_table_detect = MagicMock(return_value={
        "questions": [],
    })
    pipeline._run_analyze_structure = MagicMock(return_value={
        "structure": {},
    })
    pipeline._run_classify_pages = MagicMock(return_value={
        "filtered_blocks": [],
        "page_classifications": [],
    })

    pipeline._build_pipeline()
    return pipeline


def _run_pipeline_and_collect(pipeline: ImportPipeline) -> dict:
    """Run a pipeline and return routing_metrics + split_quality from results."""
    result = asyncio.run(pipeline.run(
        file_content=b"fake",
        source_type="pdf",
        source_file="ab_test.pdf",
        subject="math2",
        db=_make_mock_db(),
    ))
    qr = result.get("quality_report") or {}
    return {
        "status": result.get("status"),
        "routing_metrics": qr.get("routing_metrics") or {},
        "split_quality": qr.get("split_quality_evaluation") or {},
        "total_questions": qr.get("total_questions", 0),
    }


# ═══════════════════════════════════════════════════════════════
# A/B 实验 Case 1: 高置信度 layout（单栏 + 完整选项）
# ═══════════════════════════════════════════════════════════════

def test_ab_high_confidence_layout():
    """高置信度 layout → router 应选 standard → split 质量应一致。"""
    baseline = _run_pipeline_and_collect(
        _make_pipeline_with_routing(split_mode="standard", layout_confidence=0.9)
    )
    experiment = _run_pipeline_and_collect(
        _make_pipeline_with_routing(split_mode=None, layout_confidence=0.9)
    )

    # Both should produce comparable quality
    b_sq = baseline["split_quality"].get("split_quality_score", 0)
    e_sq = experiment["split_quality"].get("split_quality_score", 0)
    assert abs(b_sq - e_sq) < 0.1, (
        f"High-confidence layout: quality gap too large: "
        f"baseline={b_sq:.3f} experiment={e_sq:.3f}"
    )

    # Experiment should route to standard
    assert experiment["routing_metrics"].get("split_mode") == "standard"


# ═══════════════════════════════════════════════════════════════
# A/B 实验 Case 2: 中置信度 layout（选项检测不完整）
# ═══════════════════════════════════════════════════════════════

def test_ab_medium_confidence_layout():
    """中置信度 layout → router 应选 layout_enhanced → 应提升选项恢复率。"""
    baseline = _run_pipeline_and_collect(
        _make_pipeline_with_routing(
            split_mode="standard",
            layout_confidence=0.6,
            option_detection_score=0.6,
        )
    )
    experiment = _run_pipeline_and_collect(
        _make_pipeline_with_routing(
            split_mode=None,
            layout_confidence=0.6,
            option_detection_score=0.6,
        )
    )

    # Experiment should detect medium confidence and use layout_enhanced
    e_mode = experiment["routing_metrics"].get("split_mode")
    assert e_mode == "layout_enhanced", (
        f"Medium confidence should route to layout_enhanced, got {e_mode}"
    )


# ═══════════════════════════════════════════════════════════════
# A/B 实验 Case 3: 低置信度 layout（选项检测失败）
# ═══════════════════════════════════════════════════════════════

def test_ab_low_confidence_layout():
    """低置信度 layout → router 应选 vl_rebuild。"""
    experiment = _run_pipeline_and_collect(
        _make_pipeline_with_routing(
            split_mode=None,
            layout_confidence=0.3,
            option_detection_score=0.2,
            option_detection_failed=True,
        )
    )

    e_mode = experiment["routing_metrics"].get("split_mode")
    assert e_mode == "vl_rebuild", (
        f"Low confidence should route to vl_rebuild, got {e_mode}"
    )


# ═══════════════════════════════════════════════════════════════
# A/B 实验 Case 4: 无选项的场景（判断题）
# ═══════════════════════════════════════════════════════════════

def test_ab_no_options_question():
    """判断题（无选项）→ 不受 routing 影响。"""
    baseline = _run_pipeline_and_collect(
        _make_pipeline_with_routing(
            split_mode="standard",
            layout_confidence=0.85,
            question_options=False,
        )
    )
    experiment = _run_pipeline_and_collect(
        _make_pipeline_with_routing(
            split_mode=None,
            layout_confidence=0.85,
            question_options=False,
        )
    )

    # Both should show low option recovery (no options in data)
    b_opt = baseline["split_quality"].get("option_recovery_rate", 1)
    e_opt = experiment["split_quality"].get("option_recovery_rate", 1)
    assert b_opt == 0.0
    assert e_opt == 0.0


# ═══════════════════════════════════════════════════════════════
# A/B 实验 Case 5: 批量文档 — 多 routing 模式聚合
# ═══════════════════════════════════════════════════════════════

def test_ab_batch_aggregation():
    """批量运行多个文档 → 验证聚合 metrics 正确。"""
    from app.evaluation.routing_metrics import RoutingMetricsCollector, RoutingRecord

    collector = RoutingMetricsCollector()

    # 3 high-confidence → standard
    for i in range(3):
        r = _run_pipeline_and_collect(
            _make_pipeline_with_routing(split_mode="standard", layout_confidence=0.9)
        )
        rm = r["routing_metrics"]
        collector.add_record(RoutingRecord(
            pipeline_id=f"high_{i}",
            split_mode="standard",
            layout_confidence=0.9,
            option_detection_score=0.9,
            option_detection_failed=False,
            question_count=rm.get("question_count", 0),
            option_missing_questions=rm.get("option_missing_count", 0),
            avg_split_confidence=rm.get("avg_split_confidence", 0.0),
            split_quality_score=rm.get("split_quality_score", 0.0),
        ))

    # 2 low-confidence → vl_rebuild
    for i in range(2):
        r = _run_pipeline_and_collect(
            _make_pipeline_with_routing(
                split_mode=None,
                layout_confidence=0.3,
                option_detection_failed=True,
                option_detection_score=0.2,
            )
        )
        rm = r["routing_metrics"]
        collector.add_record(RoutingRecord(
            pipeline_id=f"low_{i}",
            split_mode="vl_rebuild",
            layout_confidence=0.3,
            option_detection_score=0.2,
            option_detection_failed=True,
            question_count=rm.get("question_count", 0),
            option_missing_questions=rm.get("option_missing_count", 0),
            avg_split_confidence=rm.get("avg_split_confidence", 0.0),
            split_quality_score=rm.get("split_quality_score", 0.0),
            vl_trigger_reason="low_confidence",
        ))

    summary = collector.compute_summary()
    assert summary["total_runs"] == 5
    assert summary["mode_distribution"]["standard"]["count"] == 3
    assert summary["mode_distribution"]["vl_rebuild"]["count"] == 2
    assert summary["vl_trigger_rate"] == 0.4  # 2/5
    assert summary["over_trigger_warning"] is not None  # 40% > 10%


# ═══════════════════════════════════════════════════════════════
# A/B 实验 Case 6: routing_metrics 写入 quality_report
# ═══════════════════════════════════════════════════════════════

def test_routing_metrics_in_quality_report():
    """验证 routing_metrics 和 split_quality 出现在 quality_report 中。"""
    pipeline = _make_pipeline_with_routing(split_mode="standard")
    result = asyncio.run(pipeline.run(
        file_content=b"fake",
        source_type="pdf",
        source_file="test.pdf",
        subject="math2",
        db=_make_mock_db(),
    ))
    qr = result.get("quality_report") or {}
    assert "routing_metrics" in qr, "quality_report should contain routing_metrics"
    assert "split_quality_evaluation" in qr, (
        "quality_report should contain split_quality_evaluation"
    )

    rm = qr["routing_metrics"]
    assert rm["split_mode"] == "standard"
    assert rm["question_count"] == 5

    sq = qr["split_quality_evaluation"]
    assert sq["question_count"] == 5
    assert sq["split_quality_score"] > 0


# ═══════════════════════════════════════════════════════════════
# A/B 实验 Case 7: mode_distribution 正确聚合
# ═══════════════════════════════════════════════════════════════

def test_routing_metrics_mode_distribution():
    """验证 routing_metrics 中的 mode_distribution 正确。"""
    from app.evaluation.routing_metrics import RoutingMetricsCollector, RoutingRecord

    collector = RoutingMetricsCollector()
    for mode in ["standard", "standard", "layout_enhanced", "vl_rebuild"]:
        collector.add_record(RoutingRecord(
            pipeline_id="x", split_mode=mode,
            layout_confidence=0.8, option_detection_score=0.8,
            option_detection_failed=False, question_count=5,
            option_missing_questions=0, avg_split_confidence=0.9,
            split_quality_score=0.85,
        ))

    summary = collector.compute_summary()
    assert summary["mode_distribution"]["standard"]["count"] == 2
    assert summary["mode_distribution"]["standard"]["pct"] == 50.0
    assert summary["mode_distribution"]["layout_enhanced"]["count"] == 1
    assert summary["mode_distribution"]["layout_enhanced"]["pct"] == 25.0
    assert summary["mode_distribution"]["vl_rebuild"]["count"] == 1
    assert summary["mode_distribution"]["vl_rebuild"]["pct"] == 25.0
