"""Relation display and parent practice entry compatibility."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import knowledge_map_service as service
from tests.test_services.test_knowledge_map_compatibility import _make_database, _seed


def _edge(source, target, relation, confidence=0.8, weight=1):
    return SimpleNamespace(
        source_knowledge_point_id=source,
        target_knowledge_point_id=target,
        relation_type=relation,
        confidence=confidence,
        weight=weight,
    )


@pytest.mark.asyncio
async def test_relations_filter_direction_scope_and_rank_before_truncation():
    members = {i: SimpleNamespace(name_snapshot=f"snapshot {i}") for i in range(1, 15)}
    rows = [
        *(_edge(i, 1, "prerequisite", weight=i) for i in range(2, 15)),
        _edge(1, 2, "prerequisite", 1),
        _edge(15, 1, "prerequisite", 1),
        _edge(1, 3, "next"),
        _edge(4, 1, "next", 1),
        _edge(1, 5, "related", 0.12349),
        _edge(6, 1, "related", 0.1234),
        _edge(1, 1, "related", 1),
        _edge(1, 7, "parent", 1),
    ]
    db = SimpleNamespace(
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: rows))
    )
    prerequisites, next_nodes, related = await service._relation_payloads(
        db,
        SimpleNamespace(id=1, subject_id=10),
        members,
    )
    assert [item["knowledge_point_id"] for item in prerequisites] == list(
        range(14, 6, -1)
    )
    assert [item["knowledge_point_id"] for item in next_nodes] == [3]
    assert related == [
        {
            "knowledge_point_id": 5,
            "name": "snapshot 5",
            "relation_type": "related",
            "confidence": 0.123,
            "weight": 1.0,
        },
        {
            "knowledge_point_id": 6,
            "name": "snapshot 6",
            "relation_type": "related",
            "confidence": 0.123,
            "weight": 1.0,
        },
    ]


@pytest.mark.asyncio
async def test_parent_detail_offers_descendant_practice_without_own_questions(tmp_path):
    engine, factory = await _make_database(tmp_path)
    try:
        ids = await _seed(factory)
        async with factory() as db:
            result = await service.get_point_detail(db, 9, 1)
            assert not db.new and not db.dirty and not db.deleted
        assert result["trainable_question_count"] == 0
        assert result["subtree_trainable_knowledge_points"] == 1
        assert result["direct_children"] == [
            {"knowledge_point_id": 2, "name": "链表", "depth": 1},
        ]
        assert result["practice_route_params"] == {
            "subject_id": ids["ds"],
            "mode": "random",
            "count": 10,
            "knowledge_point": "线性表",
            "knowledge_point_id": 1,
            "include_descendants": 1,
            "allow_repeat": 1,
            "autostart": 1,
            "source": "knowledge_map",
        }
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_untrainable_leaf_has_empty_practice_entry(tmp_path):
    engine, factory = await _make_database(tmp_path)
    try:
        await _seed(factory)
        async with factory() as db:
            result = await service.get_point_detail(db, 9, 3)
        assert result["practice_route_params"] == {}
        assert result["ancestors"] == []
        assert result["direct_children"] == []
        assert result["status"] == "no_data"
    finally:
        await engine.dispose()
