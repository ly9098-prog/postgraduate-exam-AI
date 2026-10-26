"""Current projection versus immutable attempt semantics before any model call."""

import asyncio
from copy import deepcopy
from datetime import UTC

import pytest
from sqlalchemy.sql import operators

from app.models.admin import QuestionVersion
from tests.test_services.ai_revision_guard_support import execute, fail_at, make_harness


@pytest.mark.asyncio
async def test_drift_event_order_warning_and_complete_guard_response(
    monkeypatch,
):
    h = make_harness(monkeypatch)
    output = await execute(h)
    assert h.events == [
        "get_logger",
        "current",
        "scalar",
        "historical",
        "signature",
        "signature",
        "warning",
        "response",
        "now",
        "isoformat",
    ]
    assert output == {
        "content": h.content,
        "from_cache": False,
        "from_fallback": False,
        "tokens_used": 0,
        "model": "revision_guard",
        "duration_ms": 0,
        "force_regenerated": False,
        "visual_input_count": 0,
        "input_mode": "text",
        "generated_at": "stamp",
        "revision_guarded": True,
    }
    assert output["content"] is h.content and h.records["now"] == [UTC]
    assert h.records["warning"] == [
        (
            "ai.error_analysis.revision_guard wq_id=%s question_id=%s "
            "wrong_version_id=%s current_version_id=%s revision_found=%s",
            3,
            11,
            7,
            17,
            True,
        )
    ]


@pytest.mark.asyncio
async def test_grounding_uses_current_and_historical_fields_without_copying_inputs(
    monkeypatch,
):
    h = make_harness(monkeypatch)
    current_ref, historical_ref = h.question.options, h.revision.options
    current_before, historical_before = deepcopy(current_ref), deepcopy(historical_ref)
    await execute(h)
    assert h.records["current"] == [
        {
            "question_type": "single",
            "content": "new",
            "options": current_before,
            "correct_answer": "B",
            "user_answer": "A",
        }
    ]
    assert h.records["current"][0]["options"] is current_ref is h.question.options
    assert h.question.options == current_before
    assert h.records["historical"] == [
        {
            "question_type": "old_type",
            "content": "old",
            "options": historical_before,
            "correct_answer": "A",
            "user_answer": "A",
        }
    ]
    assert h.records["historical"][0]["options"] is historical_ref is h.revision.options
    assert h.revision.options == historical_before
    assert (
        h.records["signature"][0] is h.current
        and h.records["signature"][1] is h.historical
    )


@pytest.mark.asyncio
async def test_revision_query_requires_version_id_and_original_question_id(monkeypatch):
    h = make_harness(monkeypatch)
    h.question.id = 19
    await execute(h)
    query = h.records["scalar"][0]
    assert [column["entity"] for column in query.column_descriptions] == [
        QuestionVersion
    ]
    assert query.compile().params == {"id_1": 7, "question_id_1": 11}
    terms = list(query.whereclause.clauses)
    assert len(terms) == 2 and all(term.operator is operators.eq for term in terms)
    assert (
        terms[0].left.compare(QuestionVersion.id.expression)
        and terms[0].right.value == 7
    )
    assert (
        terms[1].left.compare(QuestionVersion.question_id.expression)
        and terms[1].right.value == 11
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "current,wrong", [(None, None), (0, 7), (17, 0), (7, 7), ("7", 7), ("0", 7)]
)
async def test_missing_zero_equal_versions_skip_db_only_after_current_grounding(
    monkeypatch, current, wrong
):
    h = make_harness(monkeypatch)
    h.question.current_version_id, h.wrong.question_version_id = current, wrong
    assert await execute(h) is None
    assert h.events == ["get_logger", "current"]


@pytest.mark.asyncio
async def test_identical_fact_signatures_allow_changed_revision_without_response(
    monkeypatch,
):
    h = make_harness(monkeypatch)
    h.historical_signature = h.current_signature
    assert await execute(h) is None
    assert h.events == [
        "get_logger",
        "current",
        "scalar",
        "historical",
        "signature",
        "signature",
    ]


@pytest.mark.asyncio
async def test_missing_revision_returns_guard_without_historical_grounding(monkeypatch):
    h = make_harness(monkeypatch)
    h.revision = None
    assert (await execute(h))["revision_guarded"] is True
    assert "signature" not in h.events and "historical" not in h.events
    assert h.records["warning"][0][-1] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [None, "", "historical_type"])
async def test_historical_type_falls_back_only_when_falsy(monkeypatch, kind):
    h = make_harness(monkeypatch)
    h.revision.question_type = kind
    await execute(h)
    assert h.records["historical"][0]["question_type"] == (kind or "single")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "point",
    [
        "get_logger",
        "current",
        "scalar",
        "historical",
        "signature",
        "warning",
        "response",
        "now",
        "isoformat",
    ],
)
@pytest.mark.parametrize("kind", [RuntimeError, asyncio.CancelledError])
async def test_errors_and_cancellation_keep_identity_without_continuing(
    monkeypatch, point, kind
):
    h = make_harness(monkeypatch)
    error = kind(point)
    fail_at(h, point, error)
    with pytest.raises(kind) as caught:
        await execute(h)
    assert caught.value is error and h.events[-1] == point


@pytest.mark.asyncio
async def test_task_cancel_during_database_lookup_propagates_without_guard_publication(
    monkeypatch,
):
    h = make_harness(monkeypatch)
    entered = asyncio.Event()

    async def wait():
        entered.set()
        await asyncio.Event().wait()

    h.wait = wait
    task = asyncio.create_task(execute(h))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2)
        assert h.events == ["get_logger", "current", "scalar"]
    finally:
        if not task.done():
            task.cancel()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=2)


@pytest.mark.asyncio
@pytest.mark.parametrize("attribute", ["current_version_id", "question_version_id"])
async def test_invalid_version_conversion_is_not_coerced_into_no_drift(
    monkeypatch, attribute
):
    h = make_harness(monkeypatch)
    setattr(
        h.question if attribute == "current_version_id" else h.wrong,
        attribute,
        "invalid",
    )
    with pytest.raises(ValueError):
        await execute(h)
    assert h.events == ["get_logger", "current"]
