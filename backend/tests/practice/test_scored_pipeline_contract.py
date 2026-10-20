"""Exercise the scored entry point with SQL ports and real phase orchestration."""

import asyncio
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import sqlite

from app.services import practice_service as svc


class Rows:
    def __init__(self, values):
        self.values = values

    def scalars(self):
        return self

    def all(self):
        return self.values


@pytest.fixture
def scored_ports(monkeypatch):
    events = []
    candidates = [SimpleNamespace(id=qid) for qid in range(1, 56)]
    extra = SimpleNamespace(id=56)
    context = {"prerequisite_candidates": {90: {"priority": 1}}}
    state = SimpleNamespace(
        events=events, graph_error=None, weight_error=None, query_error=None,
        context=context, graph_queries=[], weights=[],
    )

    @asynccontextmanager
    async def nested():
        events.append("savepoint.enter")
        try:
            yield
        except BaseException:
            events.append("savepoint.rollback")
            raise
        else:
            events.append("savepoint.release")

    async def graph(**kwargs):
        events.append("graph")
        if state.graph_error:
            raise state.graph_error
        return state.context

    async def weights(db, user_id):
        events.append("weights")
        if state.weight_error:
            raise state.weight_error
        return {"due_weight": 3.0}

    async def execute(query):
        sql = str(query.compile(dialect=sqlite.dialect()))
        events.append(sql)
        if "FROM user_knowledge_states" in sql:
            return Rows([SimpleNamespace(
                knowledge_point_id=90, mastery_score=20, confidence=0.9,
                attempt_count=4, wrong_count=3,
            )])
        if "FROM user_question_state" in sql:
            return Rows([])
        if "JOIN practice_records" in sql:
            return Rows([(90,)])
        if "FROM question_knowledge_points" in sql and "FROM questions" not in sql:
            return Rows([(q.id, q.id) for q in [*candidates, extra]])
        if "FROM knowledge_points" in sql:
            return Rows([])
        if "FROM question_knowledge_points" in sql:
            state.graph_queries.append(query)
            if state.query_error:
                raise state.query_error
            return Rows([extra])
        assert "FROM questions" in sql, sql
        return Rows(candidates)

    def score(q, *args, **kwargs):
        state.weights.append(kwargs["weights"])
        return float(kwargs["weights"]["due_weight"]), ["due"]

    monkeypatch.setattr(svc.settings, "ADAPTIVE_LEARNING_ENABLED", True)
    monkeypatch.setattr(svc.settings, "ADAPTIVE_PATH_ENABLED", True)
    monkeypatch.setattr(svc.settings, "ADAPTIVE_WEIGHT_ENABLED", True)
    monkeypatch.setattr(svc, "calculate_smart_score", score)
    monkeypatch.setattr(svc, "_build_smart_recommendation_reason", lambda *a, **kw: "due")
    adaptive = SimpleNamespace(
        get_recommendation_graph_context=graph, get_recommend_weights=weights,
    )
    import app.services as services

    monkeypatch.setitem(sys.modules, "app.services.adaptive_learning_service", adaptive)
    monkeypatch.setattr(services, "adaptive_learning_service", adaptive, raising=False)
    from app.services import recommendation_strategy_service

    monkeypatch.setattr(
        recommendation_strategy_service, "get_scored_runtime_config",
        AsyncMock(return_value={"strategy_config_id": 7, "weights": {"due_weight": 2.0}}),
    )
    state.db = SimpleNamespace(
        execute=execute, scalar=AsyncMock(return_value=55), begin_nested=nested,
    )
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [1, 11, 20])
async def test_scored_entry_awaits_weights_and_limits_graph_by_requested_count(scored_ports, count):
    result, metadata = await svc.get_smart_scored_questions(
        scored_ports.db, 7, "ds", count=count, subject_ids=[2],
    )
    assert [q.id for q in result] == list(range(1, count + 1))
    assert set(metadata) == {q.id for q in result}
    assert all(meta["recommend_score"] == 6.0 for meta in metadata.values())
    assert all(meta["strategy_config_id"] == 7 for meta in metadata.values())
    assert all(meta["strategy"] == "smart_scored" for meta in metadata.values())
    query = scored_ports.graph_queries[0]
    assert query._limit_clause.value == max(count * 3, 30)
    events = scored_ports.events
    assert events.index("savepoint.enter") < events.index("graph")
    assert events.index("graph") < events.index("savepoint.release") < events.index("weights")


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", ["graph_error", "query_error", "weight_error"])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_scored_phase_error_and_cancellation_boundaries(scored_ports, failed, error_type):
    error = error_type("synthetic scored phase failure")
    setattr(scored_ports, failed, error)
    if error_type is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError) as caught:
            await svc.get_smart_scored_questions(scored_ports.db, 7, "ds", count=11, subject_ids=[2])
        assert caught.value is error
    else:
        result, metadata = await svc.get_smart_scored_questions(
            scored_ports.db, 7, "ds", count=11, subject_ids=[2],
        )
        assert len(result) == 11
        expected = 2.0 if failed == "weight_error" else 6.0
        assert all(meta["recommend_score"] == expected for meta in metadata.values())
    if failed in {"graph_error", "query_error"}:
        assert "savepoint.rollback" in scored_ports.events


@pytest.mark.asyncio
async def test_graph_context_keeps_provider_identity_and_exact_keys(scored_ports):
    candidates = [SimpleNamespace(id=1)]
    _, _, context = await svc._load_knowledge_and_graph_context(
        scored_ports.db, 7, [2], candidates, [], {}, 11,
    )
    assert context is scored_ports.context
    assert list(context) == ["prerequisite_candidates"]


@pytest.mark.asyncio
@pytest.mark.parametrize("context", [{}, {"prerequisite_candidates": {}}, None])
async def test_missing_graph_candidates_skip_question_query(scored_ports, context):
    scored_ports.context = context
    result, metadata = await svc.get_smart_scored_questions(
        scored_ports.db, 7, "ds", count=11, subject_ids=[2],
    )
    assert len(result) == 11 and len(metadata) == 11
    assert not scored_ports.graph_queries
    assert scored_ports.events.count("weights") == 1
    expected_exit = "savepoint.rollback" if context is None else "savepoint.release"
    assert expected_exit in scored_ports.events


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled,path,weight", [
    (False, True, True), (True, False, True), (True, True, False),
])
async def test_adaptive_flags_keep_graph_and_weight_gates_independent(
    scored_ports, monkeypatch, enabled, path, weight,
):
    monkeypatch.setattr(svc.settings, "ADAPTIVE_LEARNING_ENABLED", enabled)
    monkeypatch.setattr(svc.settings, "ADAPTIVE_PATH_ENABLED", path)
    monkeypatch.setattr(svc.settings, "ADAPTIVE_WEIGHT_ENABLED", weight)
    result, metadata = await svc.get_smart_scored_questions(
        scored_ports.db, 7, "ds", count=11, subject_ids=[2],
    )
    assert len(result) == 11
    assert ("graph" in scored_ports.events) == (enabled and path)
    assert ("weights" in scored_ports.events) == (enabled and weight)
    expected_score = 6.0 if enabled and weight else 2.0
    assert all(meta["recommend_score"] == expected_score for meta in metadata.values())
