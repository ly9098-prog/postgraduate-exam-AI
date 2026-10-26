"""Keep live callback lookups and exception boundaries of split publication."""

import asyncio

import pytest

from app.features import pipeline_orchestrator as orchestrator
from tests.pipeline.split_stage_support import question, split_harness


def test_hash_snapshot_reads_counts_before_callback_mutation(monkeypatch):
    h = split_harness(monkeypatch)
    appended = question(2, risk_flags=["book_pdf_prose_like"])

    def snapshot(questions):
        assert questions is h.questions
        questions.append(appended)
        return "snapshot"

    monkeypatch.setattr(orchestrator, "_safe_hash_preview", snapshot)
    result = h.pipeline._run_split(h.blocks)
    assert result["split_count"] == 2
    assert result["split_diagnostics"]["raw_question_count"] == 1
    assert result["split_diagnostics"]["book_prose_downgraded"] == 0
    assert result["raw_questions"][-1] is appended


def test_final_freeze_port_is_resolved_after_observation(monkeypatch):
    h = split_harness(monkeypatch)
    registry = {1: [object()]}
    calls = []
    checksum = object()

    def observe(*args, **kwargs):
        calls.append("observe")
        monkeypatch.setattr(orchestrator, "_apply_frozen_options", freeze)

    def freeze(questions, frozen, **kwargs):
        calls.append("freeze")
        assert questions is h.questions and frozen is registry
        assert kwargs["freeze_checksum"] is checksum
        questions[0]["is_frozen"] = True

    monkeypatch.setattr(orchestrator, "_log_multi_blank_stage", observe)
    result = h.pipeline._run_split(
        h.blocks, frozen_option_registry=registry, freeze_checksum=checksum
    )
    assert calls == ["observe", "freeze"]
    assert result["raw_questions"][0]["is_frozen"] is True
    assert h.infos[-1][-2] == " [FROZEN]"


@pytest.mark.parametrize("failed", ["_log_multi_blank_stage", "_apply_frozen_options"])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
def test_final_observer_and_freeze_failures_propagate_before_question_logs(
    monkeypatch,
    failed,
    error_type,
):
    h = split_harness(monkeypatch)
    error = error_type("final")

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(orchestrator, failed, fail)
    with pytest.raises(error_type) as caught:
        h.pipeline._run_split(h.blocks, frozen_option_registry={1: [object()]})
    assert caught.value is error
    assert h.infos == []
