"""Teacher request ordering and truthful fallbacks without external providers."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import ai_teacher_408_service as svc


@pytest.fixture
def prepared_teacher(monkeypatch):
    state = SimpleNamespace(
        db=object(),
        question=SimpleNamespace(
            id=7, subject_id=2, question_type="single_choice", difficulty=3
        ),
        revision=SimpleNamespace(
            id=11,
            subject_id=2,
            question_type="single_choice",
            difficulty=3,
            content={"text": "server stem"},
            options={"A": "one", "B": "two"},
            answer="A",
            analysis="server explanation",
        ),
        knowledge={
            "knowledge_points": [
                {
                    "name": "queues",
                    "mastery_score": 60,
                    "confidence": 0.7,
                    "attempt_count": 4,
                }
            ],
            "weak_points": [{"name": "stacks", "mastery_score": 30, "wrong_count": 2}],
            "recent_same_kp_errors": [],
            "knowledge_graph_neighbors": [],
        },
        trace=[],
        contexts=[],
    )
    state.exam = AsyncMock(return_value={})
    state.resolve = AsyncMock(return_value=(state.question, state.revision, None))
    state.load = AsyncMock(return_value=state.knowledge)
    state.practice = AsyncMock(return_value={"user_answer": "B", "is_correct": False})
    for name, callback in [
        ("_resolve_exam_context", state.exam),
        ("_resolve_revision_and_diagnosis", state.resolve),
        ("_load_knowledge_context", state.load),
        ("_latest_practice_context", state.practice),
    ]:
        monkeypatch.setattr(svc, name, callback)
    original_prompt = svc.build_408_teacher_prompt

    def prompt(**kwargs):
        state.contexts.append(kwargs["context"])
        return original_prompt(**kwargs)

    async def quota(*args):
        state.trace.append("quota")
        return True

    async def provider(*args, **kwargs):
        state.trace.append("provider")
        return {
            "content": json.dumps({"title": "lesson", "summary": "summary"}),
            "tokens_used": 17,
        }

    async def usage(*args):
        state.trace.append("usage")

    state.quota = AsyncMock(side_effect=quota)
    state.provider = AsyncMock(side_effect=provider)
    state.usage = AsyncMock(side_effect=usage)
    monkeypatch.setattr(svc, "build_408_teacher_prompt", prompt)
    monkeypatch.setattr(svc, "check_token_limit", state.quota)
    monkeypatch.setattr(svc, "chat_with_db_model", state.provider)
    monkeypatch.setattr(svc, "record_token_usage", state.usage)
    return state


@pytest.mark.asyncio
async def test_teacher_uses_server_fact_and_records_usage_before_parsing(
    prepared_teacher, monkeypatch
):
    state = prepared_teacher
    original_parse = svc._parse_json_object

    def parse(value):
        state.trace.append("parse")
        return original_parse(value)

    monkeypatch.setattr(svc, "_parse_json_object", parse)
    result = await svc.run_teacher_action(
        state.db, user_id=3, question_id=7, action="core_concept", user_answer="client"
    )
    assert state.trace[:4] == ["quota", "provider", "usage", "parse"]
    state.quota.assert_awaited_once_with(state.db, 3, 900)
    kwargs = state.provider.await_args.kwargs
    assert kwargs == {
        "feature": "analysis",
        "temperature": 0.2,
        "timeout": 45,
        "max_tokens": 1400,
        "response_format": {"type": "json_object"},
        "prefer_direct_answer": True,
    }
    context = state.contexts[0]
    assert context["question"]["question_version_id"] == 11
    assert context["question"]["stem"] == "server stem"
    assert context["question"]["correct_answer"] == "A"
    assert context["learner_answer"] == {
        "answer": "B",
        "is_correct": False,
        "source": "practice",
    }
    point = context["knowledge"]["本题知识点"][0]
    assert point["学习状态"] == "基本掌握"
    assert "confidence" not in point and "mastery_score" not in point
    assert result["tokens_used"] == 17 and result["from_fallback"] is False
    assert state.usage.await_args.args[2] == "408_teacher:core_concept"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario", ["quota", "unavailable", "exception", "malformed", "invalid_question"]
)
async def test_teacher_fallbacks_preserve_usage_and_action_boundaries(
    prepared_teacher, scenario
):
    state = prepared_teacher
    action = (
        "similar_question" if scenario == "invalid_question" else "high_frequency_traps"
    )
    if scenario == "quota":
        state.quota.side_effect = None
        state.quota.return_value = False
    elif scenario == "unavailable":
        state.provider.side_effect = None
        state.provider.return_value = None
    elif scenario == "exception":
        state.provider.side_effect = RuntimeError("synthetic provider failure")
    elif scenario == "malformed":
        state.provider.side_effect = None
        state.provider.return_value = {"content": "not JSON", "tokens_used": 19}
    result = await svc.run_teacher_action(
        state.db, user_id=3, question_id=7, action=action
    )
    assert result["from_fallback"] is True
    assert result["sections"] == [] and result["practice_question"] is None
    assert result["knowledge_points"] == []
    assert result["question_version_id"] == 11
    if scenario == "quota":
        state.provider.assert_not_awaited()
    else:
        state.provider.assert_awaited_once()
    if scenario in {"malformed", "invalid_question"}:
        state.usage.assert_awaited_once()
        assert result["tokens_used"] == (19 if scenario == "malformed" else 17)
    else:
        state.usage.assert_not_awaited()
        assert result["tokens_used"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [asyncio.CancelledError, RuntimeError])
async def test_teacher_cancellation_and_usage_failure_propagate(
    prepared_teacher, failure
):
    state = prepared_teacher
    callback = state.provider if failure is asyncio.CancelledError else state.usage
    callback.side_effect = failure("synthetic stop")
    with pytest.raises(failure):
        await svc.run_teacher_action(
            state.db, user_id=3, question_id=7, action="core_concept"
        )
    if failure is asyncio.CancelledError:
        state.usage.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source", ["exam", "diagnosis", "practice", "client_context", "none"]
)
async def test_teacher_answer_precedence_and_diagnosis_metadata(
    prepared_teacher, monkeypatch, source
):
    state = prepared_teacher
    diagnosis = SimpleNamespace(user_answer="diagnosis answer", source_context="review")
    if source == "exam":
        state.exam.return_value = {
            "answer": SimpleNamespace(selected_answer="exam answer", is_correct=True)
        }
    if source in {"exam", "diagnosis"}:
        state.resolve.return_value = (state.question, state.revision, diagnosis)
    if source in {"client_context", "none"}:
        state.practice.return_value = {}
    monkeypatch.setattr(
        svc.error_diagnosis_service,
        "serialize_diagnosis",
        lambda _: {
            "primary_type": "concept",
            "primary_label": "concept",
            "model": "private",
        },
    )
    state.quota.side_effect = None
    state.quota.return_value = False
    await svc.run_teacher_action(
        state.db,
        user_id=3,
        question_id=7,
        action="connect_knowledge",
        user_answer=None if source == "none" else "client answer",
    )
    context = state.contexts[0]
    expected = {
        "exam": ("exam answer", True, "exam"),
        "diagnosis": ("diagnosis answer", False, "review"),
        "practice": ("B", False, "practice"),
        "client_context": ("client answer", None, "client_context"),
        "none": ("", None, "none"),
    }[source]
    assert context["learner_answer"] == dict(
        zip(("answer", "is_correct", "source"), expected)
    )
    if context["error_diagnosis"] is not None:
        assert "model" not in context["error_diagnosis"]
        assert set(context["error_diagnosis"]) == {
            "primary_type",
            "primary_label",
            "secondary_labels",
            "effective_source",
            "user_confirmed",
        }


@pytest.mark.asyncio
async def test_teacher_rejects_unknown_action_before_queries(prepared_teacher):
    state = prepared_teacher
    with pytest.raises(svc.AITeacher408AccessError, match="不支持"):
        await svc.run_teacher_action(
            state.db, user_id=3, question_id=7, action="free_prompt"
        )
    state.exam.assert_not_awaited()
    state.quota.assert_not_awaited()
    state.provider.assert_not_awaited()
