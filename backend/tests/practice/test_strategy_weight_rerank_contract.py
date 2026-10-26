"""Characterize best-effort reranking before separating scores and SQL loaders."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.services import recommendation_strategy_service as weights
from app.services.practice import strategy_weight_rerank as rerank
from tests.practice.strategy_weight_support import build_rerank_ports, rows


def config(**overrides):
    return {"id": 7, "is_active": True, "config_json": {}, **overrides}


@pytest.fixture
def ports(monkeypatch):
    return build_rerank_ports(monkeypatch)


async def run(ports, **overrides):
    return await rerank.apply_strategy_weight_rerank(
        ports.db,
        9,
        overrides.get("questions", ports.questions),
        ports.metadata,
        overrides.get("config", config()),
        overrides.get("weak", ["a"]),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "supplied",
    [
        None,
        {},
        config(is_active=False),
        config(id=None),
        config(config_json={"strategy_type": "knowledge_path"}),
    ],
)
async def test_config_guards_return_original_objects_without_io(ports, supplied):
    result, metadata = await run(ports, config=supplied)
    assert result is ports.questions and metadata is ports.metadata
    assert not ports.events
    ports.db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_single_candidate_returns_original_list_without_loading(ports):
    source = ports.questions[:1]
    result, metadata = await run(ports, questions=source)
    assert result is source and metadata is ports.metadata
    assert not ports.events


@pytest.mark.asyncio
async def test_base_scores_keep_duplicate_denominator_unknown_mastery_and_identity(
    ports,
):
    supplied = config()
    result, metadata = await run(ports, config=supplied)
    assert result is not ports.questions
    assert result[0] is ports.questions[0]
    assert metadata is ports.metadata
    assert ports.db.execute.await_count == 2
    assert ports.events == [
        ("load", [1, 2]),
        (
            "weight",
            {
                "vector_similarity": 0.8,
                "knowledge_overlap": 1 / 3,
                "difficulty_match": 0.5,
                "mastery_gap": 2 / 3,
                "path_priority": 0.0,
            },
            supplied,
        ),
        ("random",),
        (
            "weight",
            {
                "vector_similarity": 0.2,
                "knowledge_overlap": 0.0,
                "difficulty_match": 0.5,
                "mastery_gap": 0.5,
                "path_priority": 0.0,
            },
            supplied,
        ),
        ("random",),
    ]
    assert all(event[2] is supplied for event in ports.events if event[0] == "weight")
    assert metadata[1] == {
        "similarity": 0.8,
        "recommend_score": 0.8,
        "strategy_config_id": 7,
    }


@pytest.mark.asyncio
async def test_no_knowledge_skips_both_queries_and_keeps_random_calls_at_zero_ratio(
    ports,
):
    ports.kp_map.clear()
    ports.metadata.clear()
    result, _ = await run(ports)
    assert result == ports.questions
    ports.db.execute.assert_not_awaited()
    assert [event[0] for event in ports.events] == [
        "load",
        "weight",
        "random",
        "weight",
        "random",
    ]
    for event in ports.events:
        if event[0] == "weight":
            assert event[1] == {
                "vector_similarity": 0.0,
                "knowledge_overlap": 0.0,
                "difficulty_match": 1.0,
                "mastery_gap": 0.5,
                "path_priority": 0.0,
            }


@pytest.mark.asyncio
async def test_duplicate_name_winner_and_none_mastery_do_not_create_extra_queries(
    ports,
):
    ports.db.execute.side_effect = [
        rows([(10, "a"), (20, "a")]),
        rows([(20, None)]),
    ]
    await run(ports)
    assert ports.db.execute.await_count == 2
    first = next(event[1] for event in ports.events if event[0] == "weight")
    assert first["mastery_gap"] == 0.5 and first["difficulty_match"] == 1.0


@pytest.mark.asyncio
async def test_empty_name_query_skips_mastery_query(ports):
    ports.db.execute.side_effect = [rows([])]
    await run(ports)
    assert ports.db.execute.await_count == 1


@pytest.mark.asyncio
async def test_exploration_changes_order_but_metadata_records_only_weighted_score(
    ports, monkeypatch
):
    draws = iter([0.0, 1.0])
    monkeypatch.setattr(rerank.random, "random", lambda: next(draws))
    result, metadata = await run(ports, config=config(exploration_ratio=1))
    assert result == list(reversed(ports.questions))
    assert metadata[1]["recommend_score"] == 0.8
    assert metadata[2]["recommend_score"] == 0.2


@pytest.mark.asyncio
async def test_equal_final_scores_keep_candidate_order(ports, monkeypatch):
    monkeypatch.setattr(weights, "apply_strategy_weights", lambda *_: 0.123456)
    result, metadata = await run(ports)
    assert result == ports.questions
    assert metadata[1]["recommend_score"] == 0.1235


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["load", "query", "weights", "random", "exploration"])
async def test_ordinary_failure_warns_once_and_preserves_inputs(
    ports, monkeypatch, caplog, stage
):
    error = RuntimeError("rerank failed")

    def fail(*args):
        raise error

    if stage == "load":
        monkeypatch.setattr(rerank, "load_question_kps", AsyncMock(side_effect=error))
    elif stage == "query":
        ports.db.execute.side_effect = error
    elif stage == "weights":
        monkeypatch.setattr(weights, "apply_strategy_weights", fail)
    elif stage == "random":
        monkeypatch.setattr(rerank.random, "random", fail)
    supplied = (
        config(exploration_ratio="invalid") if stage == "exploration" else config()
    )
    with caplog.at_level("WARNING", logger=rerank.__name__):
        result, metadata = await run(ports, config=supplied)
    assert result is ports.questions and metadata is ports.metadata
    assert all("recommend_score" not in meta for meta in metadata.values())
    assert len(caplog.records) == 1
    assert caplog.records[0].name == rerank.__name__
    assert caplog.records[0].getMessage() == "策略权重重排失败，保持原顺序"
    assert caplog.records[0].exc_info is not None


@pytest.mark.asyncio
async def test_metadata_failure_retains_already_written_projection(ports, caplog):
    class FailingMetadata(dict):
        def setdefault(self, key, default):
            if key == 2:
                raise RuntimeError("projection failed")
            return super().setdefault(key, default)

    ports.metadata = FailingMetadata(ports.metadata)
    result, metadata = await run(ports)
    assert result is ports.questions and metadata is ports.metadata
    assert metadata[1]["recommend_score"] == 0.8
    assert "recommend_score" not in metadata[2]
    assert len(caplog.records) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["load", "query", "weights", "random"])
async def test_cancellation_propagates_without_warning(
    ports, monkeypatch, caplog, stage
):
    error = asyncio.CancelledError(stage)

    def fail(*args):
        raise error

    if stage == "load":
        monkeypatch.setattr(rerank, "load_question_kps", AsyncMock(side_effect=error))
    elif stage == "query":
        ports.db.execute.side_effect = error
    elif stage == "weights":
        monkeypatch.setattr(weights, "apply_strategy_weights", fail)
    else:
        monkeypatch.setattr(rerank.random, "random", fail)
    with pytest.raises(asyncio.CancelledError) as caught:
        await run(ports)
    assert caught.value is error
    assert not caplog.records


@pytest.mark.asyncio
async def test_queries_keep_name_scope_then_user_mastery_scope(ports):
    await run(ports)
    name_query, mastery_query = [
        call.args[0].compile() for call in ports.db.execute.await_args_list
    ]
    assert set(next(iter(name_query.params.values()))) == {"a", "b", "missing"}
    assert "knowledge_points.name IN" in str(name_query)
    assert "user_knowledge_states.user_id" in str(mastery_query)
    assert 9 in mastery_query.params.values()
    assert any(
        isinstance(value, list) and set(value) == {10, 11}
        for value in mastery_query.params.values()
    )


@pytest.mark.asyncio
async def test_weight_binding_is_once_per_run_but_random_lookup_remains_live(
    ports, monkeypatch
):
    calls = []

    def should_not_be_used(*args):
        raise AssertionError("weight binding must stay local")

    def original_weight(scores, supplied):
        calls.append(scores["vector_similarity"])
        monkeypatch.setattr(weights, "apply_strategy_weights", should_not_be_used)
        return 0.5

    def first_draw():
        monkeypatch.setattr(rerank.random, "random", lambda: 1.0)
        return 0.0

    monkeypatch.setattr(weights, "apply_strategy_weights", original_weight)
    monkeypatch.setattr(rerank.random, "random", first_draw)
    result, _ = await run(ports, config=config(exploration_ratio=1))
    assert calls == [0.8, 0.2]
    assert result == list(reversed(ports.questions))
