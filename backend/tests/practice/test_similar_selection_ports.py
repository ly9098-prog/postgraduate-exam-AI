"""Pin callable lookup timing, mutations and real task cancellation."""

import asyncio
from types import SimpleNamespace

import pytest

from app.services import practice_service as svc
from tests.similar_selection_support import SimilarHarness


@pytest.fixture
def harness(monkeypatch):
    return SimilarHarness(monkeypatch)


@pytest.mark.asyncio
async def test_recall_lookup_follows_scope_resolution(monkeypatch, harness):
    async def resolve(db, code):
        monkeypatch.setattr(svc, "load_similar_vector_questions", recall)
        return harness.scope

    async def recall(request):
        assert request.scope_ids is harness.scope
        return harness.questions, harness.metadata

    monkeypatch.setattr(svc, "resolve_subject_ids", resolve)
    questions, metadata = await harness.run(count=1)
    assert questions == harness.questions[:1] and metadata is harness.metadata
    assert harness.requests == []


@pytest.mark.asyncio
async def test_recall_and_constructor_are_bound_before_exclusion_arguments(
    monkeypatch, harness
):
    logger, search, revision = object(), object(), object()

    def forbidden(*args, **kwargs):
        raise AssertionError("callable looked up after exclusion argument")

    def exclusion(**kwargs):
        monkeypatch.setattr(svc, "load_similar_vector_questions", forbidden)
        monkeypatch.setattr(svc, "SimilarRecallRequest", forbidden)
        monkeypatch.setattr(svc, "logger", logger)
        monkeypatch.setattr(svc, "_practice_revision_scope_condition", revision)
        harness.vector.search_similar_questions = search
        return None

    monkeypatch.setattr(svc, "_build_excluded_question_subquery", exclusion)
    await harness.run(count=1)
    request = harness.requests[0]
    assert request.logger is logger
    assert request.search_similar is search and request.revision_condition is revision
    assert request.excluded_sub is None


@pytest.mark.asyncio
async def test_supplement_ports_and_scope_are_read_after_recall(monkeypatch, harness):
    calls = []
    scope = [8]
    recall = harness.recall
    revision = harness.revision
    supplement = harness.supplement

    def excluded(**kwargs):
        calls.append("exclude")
        return None

    def live_revision(ids):
        calls.append("revision")
        assert ids is scope and ids == [9, 10]
        return revision(ids)

    async def live_supplement(*args):
        calls.append("fill")
        assert len(args[1]) == 4
        return await supplement(*args)

    async def changing_recall(request):
        result = await recall(request)
        scope[:] = [9, 10]
        monkeypatch.setattr(svc, "_build_excluded_question_subquery", excluded)
        monkeypatch.setattr(svc, "_practice_revision_scope_condition", live_revision)
        monkeypatch.setattr(svc, "load_similar_fill_questions", live_supplement)
        return result

    monkeypatch.setattr(svc, "load_similar_vector_questions", changing_recall)
    await harness.run(count=5, subject_ids=scope)
    assert calls == ["revision", "exclude", "fill"]
    assert harness.fill_calls[0][1][1].right.value == [9, 10]


@pytest.mark.asyncio
async def test_random_port_is_bound_before_fill_and_projection_after_fill(
    monkeypatch, harness
):
    seen = []

    def project(metadata, questions):
        seen.append((metadata, questions))
        metadata[123] = {"changed": True}
        return {"ignored": "return value"}

    async def fill(db, conditions, need, random_sample):
        assert random_sample is harness.random_sample
        monkeypatch.setattr(svc, "_random_sample_query", object())
        monkeypatch.setattr(svc, "apply_fill_metadata", project)
        harness.questions.append(SimpleNamespace(id=90))
        return harness.fill

    monkeypatch.setattr(svc, "load_similar_fill_questions", fill)
    questions, metadata = await harness.run(count=5)
    assert seen == [(harness.metadata, harness.fill)]
    assert metadata is harness.metadata and metadata[123] == {"changed": True}
    assert [q.id for q in questions] == [4, 2, 4, 90, 7, 8]


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["resolve", "recall", "fill"])
async def test_real_task_cancellation_propagates_without_later_phases(
    monkeypatch, harness, stage
):
    entered = asyncio.Event()

    async def blocked(*args):
        harness.events.append(stage)
        entered.set()
        await asyncio.Event().wait()

    name = {
        "resolve": "resolve_subject_ids",
        "recall": "load_similar_vector_questions",
        "fill": "load_similar_fill_questions",
    }[stage]
    monkeypatch.setattr(svc, name, blocked)
    task = asyncio.create_task(harness.run(count=5))
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        task.cancel(f"cancel-{stage}")
        with pytest.raises(asyncio.CancelledError, match=f"cancel-{stage}"):
            await task
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert harness.events[-1] == stage
    assert "metadata" not in harness.events
