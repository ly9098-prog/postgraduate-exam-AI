"""Live global lookups and captured budget imports keep their original timing."""

import asyncio
from types import SimpleNamespace

import pytest

from app.features import candidate_evaluator, token_budget
from app.features import pipeline_orchestrator as orchestrator
from tests.pipeline.router_stage_support import result_for, router_harness
from tests.pipeline.test_router_stage_execution_contract import events


def raising(error):
    def fail(*args, **kwargs):
        raise error

    return fail


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failed", ["config", "configure", "classify", "evaluate", "flush"]
)
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_stage_setup_and_result_failures_propagate_original_exception(
    monkeypatch,
    failed,
    error_type,
):
    h = router_harness(monkeypatch)
    error = error_type(failed)
    if failed == "config":

        async def config(*args):
            raise error

        monkeypatch.setattr(h.pipeline, "_build_router_config", config)
    elif failed == "configure":
        h.router.configure = raising(error)
    elif failed == "classify":
        monkeypatch.setattr(orchestrator, "_should_correct", raising(error))
    elif failed == "evaluate":
        monkeypatch.setattr(candidate_evaluator, "get_evaluator", raising(error))
    else:
        h.metrics.flush = raising(error)
    with pytest.raises(error_type) as caught:
        await h.pipeline._run_ocr_correction_router(h.blocks, {}, None)
    assert caught.value is error
    if failed in {"config", "configure", "classify"}:
        assert events(h, "fix") == events(h, "check") == events(h, "flush") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", ["estimate", "check", "tokens"])
async def test_pre_or_post_model_task_failures_degrade_per_block(monkeypatch, failed):
    h = router_harness(monkeypatch)
    error = RuntimeError(failed)
    if failed == "estimate":
        monkeypatch.setattr(token_budget, "estimate_tokens", raising(error))
    elif failed == "check":

        async def check(*args):
            raise error

        monkeypatch.setattr(token_budget, "check_token_limit", check)
    else:
        h.results[0] = result_for(
            metadata={"router_call_stats": {"tokens_used": "invalid"}}
        )
    output = await h.pipeline._run_ocr_correction_router(h.blocks, {}, None)
    assert output["normalized_blocks"][0] is h.blocks[0]
    assert output["ocr_correction_diagnostics"]["corrections"][0]["corrected"] is False
    assert len(events(h, "fix")) == int(failed == "tokens")
    assert len(events(h, "record_failure")) == 1


@pytest.mark.asyncio
async def test_budget_functions_are_imported_after_classification_but_captured_for_tasks(
    monkeypatch,
):
    h = router_harness(monkeypatch)
    calls = []

    async def replacement_check(estimated, config):
        calls.append("check")
        monkeypatch.setattr(
            token_budget,
            "record_token_usage",
            lambda value: pytest.fail("late usage must not replace captured import"),
        )
        return True

    def should(*args, **kwargs):
        monkeypatch.setattr(token_budget, "check_token_limit", replacement_check)
        return True

    monkeypatch.setattr(orchestrator, "_should_correct", should)
    await h.pipeline._run_ocr_correction_router(h.blocks, {}, None)
    assert calls == ["check"]
    assert events(h, "usage")[0][1] == (7,)


@pytest.mark.asyncio
async def test_input_logger_method_is_bound_before_noise_callback_replaces_logger(
    monkeypatch,
):
    h = router_harness(monkeypatch)
    calls = []
    count = 0

    def noise(block):
        nonlocal count
        count += 1
        if count == 2:
            monkeypatch.setattr(
                orchestrator,
                "logger",
                SimpleNamespace(
                    info=lambda *args: calls.append(args),
                    warning=lambda *args: calls.append(args),
                    debug=lambda *args: calls.append(args),
                ),
            )
        return 0.4

    monkeypatch.setattr(orchestrator, "_detect_noise", noise)
    await h.pipeline._run_ocr_correction_router(h.blocks, {}, None)
    assert len(events(h, "info")) == 1
    assert events(h, "info")[0][1][0].startswith("【OCR-4】")
    assert calls[0][0].startswith("【OCR-5】")


@pytest.mark.asyncio
async def test_quality_context_reads_mode_again_after_evaluator(monkeypatch):
    h = router_harness(monkeypatch)
    modes = iter(["shadow", "off"])
    monkeypatch.setattr(
        orchestrator, "_get_domain_quality_gate_mode", lambda: next(modes)
    )
    output = await h.pipeline._run_ocr_correction_router(h.blocks, {}, None)
    assert events(h, "shadow")[0][1][2].gate_mode == "off"
    assert len(output["quality_gate_shadow_records"]) == 2


@pytest.mark.asyncio
async def test_decision_enum_import_is_captured_before_evaluator_replaces_module_binding(
    monkeypatch,
):
    h = router_harness(monkeypatch)

    def evaluator():
        def evaluate(**kwargs):
            monkeypatch.setattr(
                candidate_evaluator,
                "CandidateDecision",
                SimpleNamespace(ACCEPT=object()),
            )
            return h.decision

        return SimpleNamespace(evaluate=evaluate)

    monkeypatch.setattr(candidate_evaluator, "get_evaluator", evaluator)
    output = await h.pipeline._run_ocr_correction_router(h.blocks, {}, None)
    assert output["normalized_blocks"][0]["normalized_text"] == "accepted"


@pytest.mark.asyncio
async def test_sensitive_filter_failure_keeps_prior_passthrough_mutation(monkeypatch):
    h = router_harness(monkeypatch)
    h.config["ocr_filter_sensitive"] = True
    h.blocks = [{"normalized_text": "one"}, {"normalized_text": "two"}]
    monkeypatch.setattr(orchestrator, "_should_correct", lambda *args, **kwargs: False)
    error = RuntimeError("sensitive")

    def filter_text(text):
        if text == "two":
            raise error
        return "changed"

    monkeypatch.setattr(orchestrator, "_filter_sensitive", filter_text)
    with pytest.raises(RuntimeError) as caught:
        await h.pipeline._run_ocr_correction_router(h.blocks, {}, None)
    assert caught.value is error
    assert [block["normalized_text"] for block in h.blocks] == ["changed", "two"]
    assert events(h, "flush") == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error", [None, RuntimeError("metric"), asyncio.CancelledError("metric")]
)
async def test_accepted_correction_metrics_follow_output_log_and_propagate_failure(
    monkeypatch, error
):
    h = router_harness(monkeypatch)
    original = h.metrics.record_correction

    def correction(**kwargs):
        assert h.events[-1][0] == "info"
        assert h.events[-1][1][0].startswith("【OCR-5】")
        original(**kwargs)
        if error is not None:
            raise error

    h.metrics.record_correction = correction
    if error is not None:
        with pytest.raises(type(error)) as caught:
            await h.pipeline._run_ocr_correction_router(h.blocks, {}, None)
        assert caught.value is error
        assert events(h, "flush") == []
    else:
        output = await h.pipeline._run_ocr_correction_router(h.blocks, {}, None)
        assert output["normalized_blocks"][0]["normalized_text"] == "accepted"
        names = [event[0] for event in h.events]
        assert names.index("record_correction") < names.index("flush")
    assert len(events(h, "record_correction")) == 1
    assert events(h, "record_correction")[0][2] == {
        "model": "fixture-model",
        "before": "original",
        "after": "accepted",
        "duration_ms": 12,
        "tokens": 7,
    }
