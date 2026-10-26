"""Synthetic persistence and observation ports for outcome publication."""

from types import SimpleNamespace

from app.services.ai import analysis_outcomes as outcomes
from app.services.ai.analysis_validation import AnalysisUsage, GroundingValidation


def harness(monkeypatch):
    h = SimpleNamespace(
        events=[],
        persisted=[],
        logs=[],
        log_levels=[],
        responses=[],
        context={"nested": []},
        runtime=SimpleNamespace(provider="test", model_config_id=1),
        safe={"safe": []},
        stamp=object(),
        usage=AnalysisUsage("evidence", True, 3, 11, 17),
        parsed={
            "mistake_diagnosis": "diagnosis",
            "knowledge_patch": "",
            "review_task": [],
            "_meta": {"generated_at": "parsed-time"},
        },
        result={
            "model": "synthetic-model",
            "compatibility_profile": "synthetic-profile",
        },
        grounding=GroundingValidation(False, "mismatch", ["A"], {"answer": "B"}),
        images=["synthetic-image"],
        wrong=SimpleNamespace(id=7),
    )
    def log(level, *args):
        h.events.append("log")
        h.log_levels.append(level)
        h.logs.append(args)

    def response(*args, **kwargs):
        h.events.append("response")
        h.responses.append((args, kwargs))
        return {"published": h.responses[-1]}

    async def persist(*args, **kwargs):
        h.events.append("persist")
        h.persisted.append((args, kwargs))
        return h.safe, h.stamp

    h.logger = SimpleNamespace(
        info=lambda *args: log("info", *args),
        warning=lambda *args: log("warning", *args),
    )
    h.persist = persist
    h.validator = lambda value: True
    for name in ("grounding_repaired_response", "valid_analysis_response"):
        monkeypatch.setattr(outcomes, name, response)
    return h


async def execute(h, kind, *, default_persist=False, db=None):
    args = {
        "wrong_question": h.wrong,
        "user_id": 9,
        "context": h.context,
        "result": h.result,
        "grounding": h.grounding,
        "usage": h.usage,
        "image_data_urls": h.images,
        "input_signature": "input",
        "model_signature": "model",
        "expected_answer_check": ["B"],
        "effective_force": True,
        "runtime": h.runtime,
        "logger": h.logger,
    }
    if not default_persist:
        args["persist"] = h.persist
    if kind == "repair":
        return await outcomes.grounding_repair_outcome(db, **args)
    return await outcomes.valid_analysis_outcome(
        db,
        **args,
        parsed=h.parsed,
        visual_evidence_is_valid=h.validator,
        max_tokens=800,
    )


def assert_persisted_arguments(h, kind):
    args, values = h.persisted[0]
    assert args == (None,)
    assert values["context"] is h.context
    assert values["answer_grounding"] is h.grounding.answer_grounding
    assert values["wrong_question"] is h.wrong
    assert values["result"] is h.result
    assert values["runtime"] is h.runtime
    expected = {
        "wrong_question": h.wrong,
        "user_id": 9,
        "context": {"nested": []},
        "result": h.result,
        "answer_grounding": h.grounding.answer_grounding,
        "visual_evidence": "evidence",
        "visual_ack_retried": True,
        "visual_ack_retry_ms": 3,
        "image_count": 1,
        "input_signature": "input",
        "model_signature": "model",
        "expected_answer_check": ["B"],
        "effective_force": True,
        "tokens_used": 11,
        "duration_ms": 17,
        "runtime": h.runtime,
    }
    if kind == "repair":
        expected.update(grounding_guard_reason="mismatch", actual_answer_check=["A"])
    else:
        expected["parsed"] = h.parsed
        assert values["parsed"] is h.parsed
    assert values == expected
    assert h.log_levels == (["warning"] if kind == "repair" else ["info"])
