"""Pin AI result projections, references and the two persistence boundaries."""

import asyncio
from datetime import datetime

import pytest

from app.services.ai import analysis_persistence as persistence
from tests.test_services.analysis_persistence_support import (
    assert_business_payload,
    business_expectation,
    execute,
    harness,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["repair", "valid"])
@pytest.mark.parametrize(
    "image_count,evidence,force", [(0, "", False), (2, "seen", True)]
)
async def test_projection_metadata_chat_fields_and_reference_contracts(
    monkeypatch, kind, image_count, evidence, force
):
    h = harness(monkeypatch)
    h.args.update(
        image_count=image_count, visual_evidence=evidence, effective_force=force
    )
    expected_business = business_expectation(h, kind)
    returned = await execute(h, kind)
    payload = h.safe if kind == "repair" else h.parsed
    assert h.wrong.ai_analysis is payload
    assert_business_payload(payload, kind, expected_business)
    generated = returned[1] if kind == "repair" else returned
    if kind == "repair":
        assert returned[0] is payload
    assert datetime.fromisoformat(generated).tzinfo is not None
    expected = expected_metadata(h, kind, generated)
    assert payload["_meta"] == expected
    assert payload["_meta"]["answer_check"] is h.args["expected_answer_check"]
    assert h.calls == (
        [("safe", h.args["answer_grounding"])]
        if kind == "repair"
        else [("merge", h.args["answer_grounding"], "diagnosis")]
    )
    assert payload["mistake_diagnosis"] == ("safe" if kind == "repair" else "merged")
    assert [event[0] for event in h.db.trace] == ["commit", "add", "commit"]
    assert h.db.trace[0] == ("commit", 1, payload, 0)
    assert h.db.trace[-1] == ("commit", 2, payload, 1)
    assert_chat(h, kind)


def expected_metadata(h, kind, generated):
    args = h.args
    meta = {
        "model": "grounding_guard" if kind == "repair" else "provider-model",
        "provider": "synthetic",
        "model_config_id": 7,
        "generated_at": generated,
        "version": persistence.AI_ANALYSIS_PROMPT_VERSION,
        "from_fallback": False,
        "force_regenerated": args["effective_force"],
        "visual_input_count": args["image_count"],
        "visual_evidence": args["visual_evidence"] or None,
        "visual_ack_retried": True,
        "visual_ack_retry_ms": 12,
        "input_mode": "vision" if args["image_count"] else "text",
        "input_signature": "input-signature",
        "model_signature": "model-signature",
        "answer_check": args["expected_answer_check"],
        "grounding_guard": "repaired" if kind == "repair" else "passed",
    }
    if kind == "repair":
        meta.update(source_model="provider-model", grounding_guard_reason="mismatch")
    return meta


def assert_chat(h, kind):
    chat = h.db.chats[0]
    assert isinstance(chat, persistence.AiChat)
    assert (chat.user_id, chat.session_type, chat.user_message) == (
        9,
        "error_analysis",
        str(h.args["context"]["question"]),
    )
    assert (chat.ai_response, chat.model, chat.tokens_used, chat.duration_ms) == (
        "provider-content",
        "provider-model",
        31,
        51,
    )
    snapshot = chat.context_snapshot
    context = h.args["context"]
    assert snapshot is not context and snapshot["nested"] is context["nested"]
    assert snapshot["question"] is context["question"]
    assert "visual_input_count" not in context
    assert snapshot["visual_input_count"] == h.args["image_count"]
    assert snapshot["visual_evidence"] == (h.args["visual_evidence"] or None)
    assert (
        snapshot["visual_ack_retried"] is True and snapshot["visual_ack_retry_ms"] == 12
    )
    if kind == "repair":
        assert snapshot["grounding_guard"] == {
            "status": "repaired",
            "reason": "mismatch",
            "expected_answer_check": ["B"],
            "actual_answer_check": ["A"],
        }
        assert (
            snapshot["grounding_guard"]["expected_answer_check"]
            is h.args["expected_answer_check"]
        )
    else:
        assert "grounding_guard" not in snapshot


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["repair", "valid"])
@pytest.mark.parametrize("fail_at", ["commit1", "add", "commit2"])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_failure_and_cancellation_leave_exact_partial_persistence(
    monkeypatch, kind, fail_at, error_type
):
    error = error_type(fail_at)
    h = harness(monkeypatch, fail_at=fail_at, error=error)
    with pytest.raises(error_type) as caught:
        await execute(h, kind)
    assert caught.value is error
    assert h.wrong.ai_analysis is (h.safe if kind == "repair" else h.parsed)
    assert [row[0] for row in h.db.trace] == {
        "commit1": ["commit"],
        "add": ["commit", "add"],
        "commit2": ["commit", "add", "commit"],
    }[fail_at]
    assert len(h.db.chats) == (1 if fail_at == "commit2" else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["repair", "valid"])
async def test_first_commit_callback_changes_later_snapshot_and_chat_ports(
    monkeypatch, kind
):
    h = harness(monkeypatch)
    appended = []

    async def append(*args, **kwargs):
        appended.append((args, kwargs))

    def commit(count):
        assert count == 1
        h.args["context"]["after_commit"] = True
        monkeypatch.setattr(persistence, "_append_analysis_chat", append)

    h.db.on_commit = commit
    await execute(h, kind)
    assert len(appended) == 1 and appended[0][0] == (h.db,)
    assert appended[0][1]["snapshot"]["after_commit"] is True
    assert appended[0][1]["context"] is h.args["context"]
    assert appended[0][1]["result"] is h.args["result"]
    assert h.db.commits == 1


@pytest.mark.parametrize(
    "kind,field", [("repair", "knowledge_patch"), ("valid", "review_task")]
)
def test_business_assertion_rejects_field_loss_even_on_original_payload(
    monkeypatch, kind, field
):
    h = harness(monkeypatch)
    expected = business_expectation(h, kind)
    payload = h.safe if kind == "repair" else h.parsed
    payload.pop(field)
    if kind == "valid":
        payload["mistake_diagnosis"] = "merged"
    with pytest.raises(AssertionError):
        assert_business_payload(payload, kind, expected)
