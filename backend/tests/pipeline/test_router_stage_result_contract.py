"""Candidate acceptance, layout metadata and final statistics remain compatible."""

import asyncio

import pytest

from app.features import candidate_evaluator
from app.features import pipeline_orchestrator as orchestrator
from tests.pipeline.router_stage_support import result_for, router_harness
from tests.pipeline.test_router_stage_execution_contract import events


@pytest.mark.asyncio
@pytest.mark.parametrize("accept", [True, False])
async def test_safety_gate_controls_text_but_retains_table_layout_metadata(
    monkeypatch, accept
):
    h = router_harness(monkeypatch)
    layout = [
        {"type": "table", "rows": []},
        {"label": "TABLE_CAPTION"},
        {"type": "paragraph"},
        "invalid",
    ]
    h.results[0] = result_for(metadata={"layout_blocks": layout})
    if not accept:
        h.decision.decision = candidate_evaluator.CandidateDecision.REJECT_CONTINUE
    output = await h.pipeline._run_ocr_correction_router(h.blocks, {}, None)
    block = output["normalized_blocks"][0]
    assert block is not h.blocks[0]
    assert block["vl_layout_blocks"] == layout[:2]
    assert block["vl_layout_blocks"][0] is layout[0]
    assert block["normalized_text"] == ("accepted" if accept else "original")
    correction = output["ocr_correction_diagnostics"]["corrections"][0]
    assert correction["corrected"] is accept
    assert correction["safety"] == {
        "stage": "ocr_fix",
        "model": "fixture-model",
        "before": "original",
        "after": "accepted",
        "diff": h.decision.diff,
        "risk_flags": h.decision.risk_flags,
        "accepted": accept,
        "rollback_reason": None if accept else "safe",
        "tokens_used": 7,
        "duration_ms": 12,
    }
    assert correction["safety"]["diff"] is h.decision.diff
    assert correction["safety"]["risk_flags"] is h.decision.risk_flags
    if accept:
        assert block["ocr_correction_applied"] is True
        assert output["warnings"] == [
            "Router corrected 1/1 blocks (model: fixture-model)"
        ]
    else:
        assert "ocr_correction_applied" not in block
        assert events(h, "record_failure") == events(h, "record_unchanged") == []
        assert correction["reason"] == "safety_rejected: safe"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model,confidence,changed,should_evaluate",
    [
        ("fixture", 0.0, True, False),
        ("fixture", None, True, False),
        ("fixture", 0.1, True, True),
        ("paddleocr-vl", 0.0, True, True),
        ("paddleocr-vl", None, True, True),
        ("paddleocr-vl", 1.0, False, False),
    ],
)
async def test_candidate_eligibility_keeps_vl_zero_confidence_exception(
    monkeypatch,
    model,
    confidence,
    changed,
    should_evaluate,
):
    h = router_harness(monkeypatch)
    h.results[0] = result_for(
        text="fixed" if changed else "original", model_used=model, confidence=confidence
    )
    output = await h.pipeline._run_ocr_correction_router(h.blocks, {}, None)
    assert bool(events(h, "evaluate")) is should_evaluate
    assert output["ocr_correction_diagnostics"]["stats"]["corrected_blocks"] == int(
        should_evaluate
    )
    assert bool(events(h, "record_unchanged")) is not should_evaluate


@pytest.mark.asyncio
async def test_evaluator_context_uses_original_text_scores_and_engine(monkeypatch):
    h = router_harness(monkeypatch)
    h.blocks[0]["normalized_text"] = "A. alpha\nB) beta"
    await h.pipeline._run_ocr_correction_router(h.blocks, {}, None)
    assert events(h, "evaluate")[0][2] == {
        "original_text": "A. alpha\nB) beta",
        "candidate_text": "fixed",
        "context": {"has_options": True, "stem_context": "A. alpha\nB) beta"},
        "quality_report": {"low_confidence": True, "garbled_detected": True},
        "provenance": {"engine": "fixture-model", "model_version": "fixture-model"},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["off", "shadow", "enforce"])
async def test_shadow_and_enforce_record_observations_without_overriding_acceptance(
    monkeypatch, mode
):
    h = router_harness(monkeypatch)
    h.gate_mode = mode
    h.blocks[0]["page"] = 8
    output = await h.pipeline._run_ocr_correction_router(h.blocks, {}, None)
    records = output["quality_gate_shadow_records"]
    assert records == (
        []
        if mode == "off"
        else [
            {"decision": "fixture", "candidate_index": 0, "page": 8},
            {"decision": "fixture", "candidate_index": 0, "page": 8},
        ]
    )
    assert output["normalized_blocks"][0]["normalized_text"] == "accepted"
    if mode != "off":
        before, after, context = events(h, "shadow")[0][1]
        assert before == "original" and after == "fixed"
        assert context.pipeline_fingerprint == "router-contract"
        assert context.gate_mode == mode and context.existing_decision == "accept"
        assert context.doc_ir_source == "fixture-model"
        assert all(event[1][1] is context for event in events(h, "shadow_record"))
        assert len(events(h, "shadow_record")) == 2
        assert all(
            event[1][0] is decision
            for event, decision in zip(
                events(h, "shadow_record"), h.shadow_decisions, strict=True
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error", [RuntimeError("shadow"), asyncio.CancelledError("shadow")]
)
async def test_shadow_ordinary_failure_warns_but_cancellation_propagates(
    monkeypatch, error
):
    h = router_harness(monkeypatch)
    h.gate_mode, h.shadow_error = "shadow", error
    if isinstance(error, asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError) as caught:
            await h.pipeline._run_ocr_correction_router(h.blocks, {}, None)
        assert caught.value is error
        assert events(h, "flush") == []
    else:
        output = await h.pipeline._run_ocr_correction_router(h.blocks, {}, None)
        assert output["normalized_blocks"][0]["normalized_text"] == "accepted"
        assert events(h, "warning")[0][1] == (
            "[QUALITY-GATE] shadow evaluation failed: %s",
            error,
        )


@pytest.mark.asyncio
async def test_sensitive_filter_mutates_passthrough_blocks_before_flush(monkeypatch):
    h = router_harness(monkeypatch)
    h.config["ocr_filter_sensitive"] = True
    h.blocks = [{"normalized_text": "skip"}, {"normalized_text": ""}]
    monkeypatch.setattr(orchestrator, "_should_correct", lambda *args, **kw: False)
    reads = []

    def filter_text(text):
        reads.append(text)
        return "filtered"

    monkeypatch.setattr(orchestrator, "_filter_sensitive", filter_text)
    output = await h.pipeline._run_ocr_correction_router(h.blocks, {}, None)
    assert reads == ["skip", ""]
    assert output["normalized_blocks"][0] is h.blocks[0]
    assert output["normalized_blocks"][1] is h.blocks[1]
    assert [block["normalized_text"] for block in h.blocks] == ["filtered", "filtered"]
    names = [event[0] for event in h.events]
    assert names.index("debug") < names.index("flush")


@pytest.mark.asyncio
async def test_call_totals_and_model_names_use_router_stats_and_correction_entries(
    monkeypatch,
):
    h = router_harness(monkeypatch)
    h.blocks *= 2
    h.results = {
        0: result_for(
            model_used="z-model",
            metadata={
                "router_call_stats": {
                    "ai_calls": "2",
                    "llm_calls": 1,
                    "tokens_used": 20,
                },
            },
        ),
        1: result_for(
            model_used="a-model",
            metadata={
                "router_call_stats": {"ai_calls": 1, "vl_calls": 1, "tokens_used": 3},
            },
        ),
    }
    output = await h.pipeline._run_ocr_correction_router(h.blocks, {}, None)
    diagnostics = output["ocr_correction_diagnostics"]
    assert {
        key: diagnostics[key]
        for key in ("ai_calls", "llm_calls", "vl_calls", "tokens_used")
    } == {
        "ai_calls": 3,
        "llm_calls": 1,
        "vl_calls": 1,
        "tokens_used": 23,
    }
    assert diagnostics["stats"]["model_used"] == "a-model, z-model"
    flush = events(h, "flush")[0][2]["extra"]
    assert flush["stats"] is diagnostics["stats"]
    assert flush["used_models"] == ["a-model", "z-model"]
