"""Run real scoring, diversity selection and fallback through the scored entry."""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import sqlite

from app.models.practice_record import PracticeRecord
from app.services import practice_service as svc


class Result:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        return self.value


def question(qid):
    return SimpleNamespace(id=qid)


@pytest.fixture
def selection_ports(monkeypatch):
    state = SimpleNamespace(
        candidates=[question(qid) for qid in range(1, 7)], qkp={}, qstates={},
        queries=[], counts=[0, 0], rows=[[], []], offsets=[], weights={},
        error=None, fail_at=None, now=datetime(2026, 10, 21), logger=Mock(),
        recent_kp_ids=set(), kp_mastery={}, kp_observations={}, graph_context={},
        graph_runtime={},
    )
    excluded = select(PracticeRecord.question_id).where(PracticeRecord.user_id == 7)

    async def candidates(*args):
        return state.candidates, [], [2], excluded, 0

    async def states(*args):
        return state.qstates, state.recent_kp_ids, state.qkp

    async def weights(*args):
        return state.weights

    async def execute(query):
        state.queries.append(query)
        if state.error and (state.fail_at is None or len(state.queries) == state.fail_at):
            raise state.error
        index = (len(state.queries) - 1) // 2
        value = state.counts[index] if len(state.queries) % 2 else state.rows[index]
        return Result(value)

    def randint(low, high):
        state.offsets.append((low, high))
        return min(7, high)

    monkeypatch.setattr(svc, "utcnow", lambda: state.now)
    monkeypatch.setattr(svc, "logger", state.logger)
    monkeypatch.setattr(svc.random, "randint", randint)
    async def runtime_config(*args):
        return {"strategy_config_id": 8, "graph": state.graph_runtime}

    async def knowledge_context(*args):
        return state.kp_mastery, state.kp_observations, state.graph_context

    monkeypatch.setattr(svc, "_load_scored_runtime_config", runtime_config)
    monkeypatch.setattr(svc, "_load_smart_scored_candidates", candidates)
    monkeypatch.setattr(svc, "_load_knowledge_and_graph_context", knowledge_context)
    monkeypatch.setattr(svc, "_load_candidate_states", states)
    monkeypatch.setattr(svc, "_load_kp_names", AsyncMock(return_value={}))
    monkeypatch.setattr(svc, "_compute_recommendation_weights", weights)
    state.db = SimpleNamespace(execute=execute)
    return state


async def run(state, count=4):
    return await svc.get_smart_scored_questions(
        state.db, 7, "ds", count=count, subject_ids=[2],
    )


def fallback_level(state):
    return state.logger.info.call_args.args[-1]


@pytest.mark.asyncio
@pytest.mark.parametrize("mapping,expected,fallback", [
    ({1: [9], 2: [9], 3: [9], 4: [9], 5: [10], 6: [10]}, [1, 2, 5, 6], 0),
    ({qid: [9] for qid in range(1, 7)}, [1, 2, 3, 4], 2),
    ({1: [9], 2: [9], 3: [9, 10], 4: [9], 5: [10], 6: [10]}, [1, 2, 3, 5], 0),
    ({}, [1, 2, 3, 4], 0),
])
async def test_diversity_preserves_minimum_kp_counter_and_relaxation(
    selection_ports, mapping, expected, fallback,
):
    state = selection_ports
    state.qkp = mapping
    selected, metadata = await run(state)
    assert [q.id for q in selected] == expected
    assert list(metadata) == expected
    assert fallback_level(state) == fallback
    assert not state.queries


@pytest.mark.asyncio
async def test_real_score_weights_and_stable_ties(selection_ports):
    state = selection_ports
    state.candidates = [question(qid) for qid in [3, 2, 1, 4]]
    state.qstates[1] = SimpleNamespace(
        next_review_at=state.now - timedelta(days=2), wrong_count=2,
        answer_count=1, last_answered_at=state.now - timedelta(days=40),
    )
    state.weights = {"due_weight": 2.0}
    selected, metadata = await run(state)
    assert [q.id for q in selected] == [1, 3, 2, 4]
    assert metadata[1]["recommend_score"] == 119.0
    assert metadata[3]["recommend_score"] == 20.0
    assert all(meta["strategy_config_id"] == 8 for meta in metadata.values())
    assert all(isinstance(meta["recommend_reason"], str) for meta in metadata.values())
    top = state.logger.info.call_args_list[0].args[2]
    assert [row[0] for row in top] == [1, 3, 2, 4]


@pytest.mark.asyncio
async def test_score_context_passes_exact_state_and_keeps_candidate_order(selection_ports, monkeypatch):
    state = selection_ports
    state.candidates = [question(1), question(2), question(3)]
    state.qstates = {1: SimpleNamespace(question_id=1), 2: None}
    state.qkp = {1: [11], 2: [12], 3: []}
    state.recent_kp_ids = {11}
    state.kp_mastery = {11: (30.0, 0.8), 12: (70.0, 0.4)}
    state.kp_observations = {11: (3, 2), 12: (1, 0)}
    state.graph_context = {
        "blocked_targets": {11: [{"path_quality": 0.5}]},
        "prerequisite_candidates": {12: {"path_quality": 0.7}},
        "prerequisites_by_target": {11: [{"depth": 1}]},
    }
    state.graph_runtime = {"max_depth": 3}
    state.weights = {"due_weight": 2.0}
    scorer = Mock(side_effect=[(2.0, ["a"]), (3.0, ["b"]), (2.0, ["c"])])
    monkeypatch.setattr(svc, "calculate_smart_score", scorer)
    selected, _ = await run(state)
    assert [q.id for q in selected] == [2, 1, 3]
    assert [q.id for q in state.candidates] == [1, 2, 3]
    assert scorer.call_args_list == [
        ((state.candidates[0], state.qstates[1], [11], state.kp_mastery,
          state.recent_kp_ids, state.now), {
            "kp_observations": state.kp_observations,
            "blocked_kps": {11: [{"path_quality": 0.5}]},
            "graph_candidates": {12: {"path_quality": 0.7}},
            "prerequisites_by_target": {11: [{"depth": 1}]},
            "weights": {"due_weight": 2.0}, "graph_config": {"max_depth": 3},
          }),
        ((state.candidates[1], None, [12], state.kp_mastery,
          state.recent_kp_ids, state.now), {
            "kp_observations": state.kp_observations,
            "blocked_kps": {11: [{"path_quality": 0.5}]},
            "graph_candidates": {12: {"path_quality": 0.7}},
            "prerequisites_by_target": {11: [{"depth": 1}]},
            "weights": {"due_weight": 2.0}, "graph_config": {"max_depth": 3},
          }),
        ((state.candidates[2], None, [], state.kp_mastery,
          state.recent_kp_ids, state.now), {
            "kp_observations": state.kp_observations,
            "blocked_kps": {11: [{"path_quality": 0.5}]},
            "graph_candidates": {12: {"path_quality": 0.7}},
            "prerequisites_by_target": {11: [{"depth": 1}]},
            "weights": {"due_weight": 2.0}, "graph_config": {"max_depth": 3},
          }),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_scorer_failure_stops_later_candidates_metadata_and_fill(
    selection_ports, monkeypatch, error_type,
):
    state = selection_ports
    state.candidates = [question(1), question(2), question(3)]
    error = error_type("synthetic scorer failure")
    scorer = Mock(side_effect=[(1.0, ["a"]), error])
    monkeypatch.setattr(svc, "calculate_smart_score", scorer)
    with pytest.raises(error_type) as caught:
        await run(state)
    assert caught.value is error
    assert scorer.call_count == 2
    assert not state.queries
    assert state.logger.info.call_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("total", [2, 3, 2000, 2001])
async def test_random_fill_query_thresholds_and_metadata(selection_ports, total):
    state = selection_ports
    state.candidates = [question(1)]
    state.counts[0], state.rows[0] = total, [question(2), question(3)]
    selected, metadata = await run(state, count=3)
    assert [q.id for q in selected] == [1, 2, 3]
    assert metadata[1]["strategy"] == "smart_scored"
    assert metadata[2] == {
        "recommend_score": None, "recommend_reason": "\u968f\u673a\u8865\u9f50",
        "strategy": "random_fallback", "similarity": None,
    }
    assert fallback_level(state) == 3
    assert len(state.queries) == 2
    query = state.queries[1]
    sql = str(query.compile(dialect=sqlite.dialect()))
    assert "FROM practice_records" in sql
    if total <= 2:
        assert "ORDER BY questions.id ASC" in sql and query._limit_clause is None
    elif total <= 2000:
        assert "ORDER BY random()" in sql and query._limit_clause.value == 2
    else:
        assert "ORDER BY questions.id ASC" in sql and query._offset_clause.value == 7
        assert state.offsets == [(0, 1999)]


@pytest.mark.asyncio
async def test_last_fill_relaxes_history_only_and_skips_duplicate_ids(selection_ports):
    state = selection_ports
    state.candidates = [question(1)]
    state.counts = [0, 2]
    state.rows = [[], [question(1), question(2), question(3)]]
    selected, metadata = await run(state, count=3)
    assert [q.id for q in selected] == [1, 2, 3]
    assert metadata[1]["strategy"] == "smart_scored"
    assert metadata[2]["strategy"] == "repeat_window_fallback"
    assert "strategy_config_id" not in metadata[2]
    assert fallback_level(state) == 4
    first, final = [str(q.compile(dialect=sqlite.dialect())) for q in state.queries[1::2]]
    assert "FROM practice_records" in first and "FROM practice_records" not in final
    for sql in [first, final]:
        assert "questions.is_active" in sql and "questions.subject_id IN" in sql
        assert "question_versions" in sql and "questions.id NOT IN" in sql


@pytest.mark.asyncio
async def test_fill_preserves_original_metadata_and_slice_when_provider_overfills(selection_ports):
    state = selection_ports
    state.candidates = [question(1)]
    state.counts[0], state.rows[0] = 2, [question(2), question(3), question(4)]
    selected, metadata = await run(state, count=3)
    assert [q.id for q in selected] == [1, 2, 3]
    assert list(metadata) == [1, 2, 3, 4]


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_fill_database_errors_propagate_without_later_query(selection_ports, error_type):
    state = selection_ports
    state.candidates = [question(1)]
    state.error = error_type("synthetic fill error")
    with pytest.raises(error_type) as caught:
        await run(state, count=3)
    assert caught.value is state.error
    assert len(state.queries) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, -1])
async def test_nonpositive_count_keeps_original_selection_and_metadata(selection_ports, count):
    selected, metadata = await run(selection_ports, count=count)
    assert selected == []
    assert list(metadata) == [1]
    assert not selection_ports.queries


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_metadata_failure_stops_selection_before_database_fill(
    selection_ports, monkeypatch, error_type,
):
    error = error_type("synthetic metadata failure")
    factory = Mock(side_effect=error)
    monkeypatch.setattr(svc, "_build_scored_metadata", factory)
    with pytest.raises(error_type) as caught:
        await run(selection_ports)
    assert caught.value is error
    factory.assert_called_once()
    assert not selection_ports.queries


@pytest.mark.asyncio
async def test_empty_candidate_pool_returns_without_scoring(selection_ports, monkeypatch):
    selection_ports.candidates = []
    score = Mock(side_effect=AssertionError("empty pool must not score"))
    monkeypatch.setattr(svc, "calculate_smart_score", score)
    assert await run(selection_ports) == ([], {})
    score.assert_not_called()
    assert not selection_ports.queries


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_query", [1, 2, 3, 4])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_each_fill_count_and_rows_query_preserves_error_boundary(
    selection_ports, failed_query, error_type,
):
    state = selection_ports
    state.candidates = [question(1)]
    state.counts, state.rows = [0, 2], [[], [question(2), question(3)]]
    state.error, state.fail_at = error_type("synthetic fill query failure"), failed_query
    with pytest.raises(error_type) as caught:
        await run(state, count=3)
    assert caught.value is state.error
    assert len(state.queries) == failed_query


@pytest.mark.asyncio
async def test_repeat_fill_keeps_original_sampler_and_offset(selection_ports, monkeypatch):
    state = selection_ports
    state.candidates = [question(1)]
    state.counts, state.rows = [0, 2001], [[], [question(2), question(3)]]
    sampler = Mock(wraps=svc._random_sample_query)
    monkeypatch.setattr(svc, "_random_sample_query", sampler)
    selected, metadata = await run(state, count=3)
    sampler.assert_called_once()
    assert sampler.call_args.kwargs == {
        "total_count": 2001, "need": 2, "id_col": svc.Question.id,
    }
    assert state.offsets == [(0, 1999)]
    assert [q.id for q in selected] == [1, 2, 3]
    assert metadata[2]["strategy"] == "repeat_window_fallback"


@pytest.mark.asyncio
@pytest.mark.parametrize("empty_count", [None, 0])
async def test_empty_fill_counts_keep_original_short_result(selection_ports, empty_count):
    state = selection_ports
    state.candidates = [question(1)]
    state.counts = [empty_count, empty_count]
    selected, metadata = await run(state, count=3)
    assert [q.id for q in selected] == [1]
    assert list(metadata) == [1]
    assert len(state.queries) == 4
    assert fallback_level(state) == 4
