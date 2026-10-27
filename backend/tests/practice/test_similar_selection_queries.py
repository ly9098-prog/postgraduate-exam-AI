"""Exercise the actual similar providers through the service with SQL ports."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy.dialects import postgresql, sqlite

from app.services import practice_service as svc
from app.services.practice import similar_supplement as providers
from tests.similar_selection_support import SimilarHarness


class Rows:
    def __init__(self, value):
        self.value = value

    def scalars(self):
        return self

    def all(self):
        return self.value

    def scalar(self):
        return self.value


@pytest.fixture
def harness(monkeypatch):
    state = SimilarHarness(monkeypatch)
    state.logger = Mock()
    state.sql = []
    state.samples = []
    state.provider_calls = []
    state.enabled = True
    state.provider_error = None
    state.query_error = None
    state.recommendations = [
        {"question_id": qid, "recommend_score": score, "similarity": 0.8}
        for qid, score in ((4, 0.9), (2, 0.7), (4, 0.6), (42, 1.0), (77, 0.4))
    ]
    for name in (
        "load_similar_vector_questions",
        "load_similar_fill_questions",
        "apply_fill_metadata",
    ):
        monkeypatch.setattr(svc, name, getattr(providers, name))

    async def search(**kwargs):
        state.provider_calls.append(kwargs)
        if state.provider_error:
            raise state.provider_error
        return {"enabled": state.enabled, "recommendations": state.recommendations}

    async def execute(query):
        state.sql.append(query)
        compiled = str(query.compile(dialect=sqlite.dialect()))
        if "count(*)" in compiled:
            return Rows(100)
        if "questions.id IN (" in compiled:
            if state.query_error:
                raise state.query_error
            return Rows(state.questions[:2])
        return Rows(state.fill)

    def sample(query, total, need, id_column):
        state.samples.append((query, total, need, id_column))
        return query.limit(need)

    state.db = SimpleNamespace(execute=execute)
    state.vector.search_similar_questions = search
    monkeypatch.setattr(svc, "_random_sample_query", sample)
    monkeypatch.setattr(svc, "logger", state.logger)
    return state


@pytest.mark.asyncio
async def test_vector_order_duplicates_full_metadata_and_two_phase_sql(harness):
    questions, metadata = await harness.run(count=5, subject_ids=[8, 9])
    assert [q.id for q in questions] == [4, 2, 4, 7, 8]
    assert metadata[4] == {
        "recommend_reason": "向量相似",
        "recommend_score": 0.6,
        "strategy": "vector",
        "similarity": 0.8,
    }
    assert set(metadata) == {2, 4, 7, 8}
    assert harness.provider_calls == [dict(db=harness.db, user_id=7, question_id=42)]
    assert len(harness.sql) == 3
    assert harness.samples[0][1:3] == (100, 2)
    assert harness.sql[-1]._limit_clause.value == 2
    assert len(harness.sql[0]._with_options) == 1
    assert len(harness.sql[-1]._with_options) == 1
    for dialect in (sqlite.dialect(), postgresql.dialect()):
        sql = [
            str(q.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))
            for q in harness.sql
        ]
        assert "questions.id != 42" in sql[0]
        assert "questions.subject_id IN (8, 9)" in sql[0]
        assert "questions.difficulty >= 2" in sql[0]
        assert "questions.id = 100" in sql[0]
        assert "count(*)" in sql[1] and "questions.id = 101" in sql[1]
        assert "questions.id = 101" in sql[2]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cause", ["disabled", "empty", "provider-failure", "query-failure"]
)
async def test_vector_unavailability_uses_original_random_supplement(harness, cause):
    if cause == "disabled":
        harness.enabled = False
    elif cause == "empty":
        harness.recommendations = []
    elif cause == "provider-failure":
        harness.provider_error = RuntimeError("synthetic provider failure")
    else:
        harness.query_error = RuntimeError("synthetic vector query failure")
    questions, metadata = await harness.run(count=5)
    assert questions == harness.fill
    assert set(metadata) == {7, 8}
    assert harness.samples[0][1:3] == (100, 5)
    assert harness.logger.warning.call_count == int("failure" in cause)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["provider_error", "query_error"])
async def test_vector_cancellation_does_not_enter_random_fallback(harness, stage):
    error = asyncio.CancelledError(f"cancel-{stage}")
    setattr(harness, stage, error)
    with pytest.raises(asyncio.CancelledError) as caught:
        await harness.run(count=5)
    assert caught.value is error
    assert not harness.samples and not harness.logger.warning.called


@pytest.mark.asyncio
async def test_sufficient_vectors_do_not_load_supplement_or_prune_metadata(harness):
    questions, metadata = await harness.run(count=1)
    assert [q.id for q in questions] == [4]
    assert set(metadata) == {2, 4}
    assert len(harness.sql) == 1 and not harness.samples
