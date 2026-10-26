"""Read-time summary contracts, including ports and early-return boundaries."""

from unittest.mock import AsyncMock

import pytest

from app.services.practice import knowledge_session_summary as svc
from tests.practice.knowledge_summary_support import (
    Database,
    legacy,
    read,
    record,
    root_port,
    session,
    state,
)


def durable():
    return {
        "practice_mode": "knowledge_point",
        "root_knowledge_point_id": 20,
        "root_name": "durable name",
        "include_descendants": False,
        "resolved_knowledge_point_count": 9,
    }


@pytest.mark.asyncio
async def test_empty_request_and_missing_session_short_circuit():
    db = Database()
    assert await read(db, "  ") is None
    assert db.events == []
    assert await read(db) is None
    assert db.events == ["scalar"]
    assert db.sql[0][2] == {"user_id_1": 7, "request_id_1": "req"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "snapshot,mode,scope",
    [
        (None, "general", None),
        (
            durable(),
            "knowledge_point",
            {
                "root_knowledge_point_id": 20,
                "root_name": "durable name",
                "include_descendants": False,
                "knowledge_point_count": 9,
            },
        ),
    ],
)
async def test_missing_baseline_response_returns_unavailable(snapshot, mode, scope):
    db = Database(session=session(snapshot=snapshot))
    result = await read(db)
    assert result == {
        "request_id": "req",
        "status": "unavailable",
        "practice_mode": mode,
        "projection_pending_count": 0,
        "scope": scope,
        "chapter": None,
        "touched_knowledge_point_count": 0,
        "points": [],
    }
    assert db.events == ["scalar"]


@pytest.mark.asyncio
async def test_processing_uses_durable_scope_and_original_record_loader_port(
    monkeypatch,
):
    db = Database(
        session=session(
            {"_baseline": {"points": [[12, 1, 2, "bad"]]}}, snapshot=durable()
        )
    )
    loader = AsyncMock(return_value=[record(1, projection="pending"), record(2)])
    monkeypatch.setattr(svc, "_load_session_records", loader)
    result = await read(db)
    assert result["status"] == "processing"
    assert result["projection_pending_count"] == 1
    assert result["practice_mode"] == "knowledge_point"
    assert result["scope"]["root_knowledge_point_id"] == 20
    assert result["chapter"] is None and result["points"] == []
    loader.assert_awaited_once_with(
        db, user_id=7, response=db.session.submission_response
    )
    assert db.events == ["scalar"]


@pytest.mark.asyncio
async def test_read_records_are_deduplicated_reordered_and_filtered_by_user(
    monkeypatch,
):
    rows = [record(2, 102), record(1, correct=True)]
    db = Database(
        session=session(
            legacy([[12, 50, 1, 1]]),
            results=[
                {"record_id": 1},
                "ignored",
                {"record_id": 2},
                {"record_id": 1},
            ],
        ),
        scalars=[rows, [state(12, 70)]],
        execute=[[(101, 12, "first"), (101, 12, "same"), (102, 12, "last")]],
    )
    root_port(monkeypatch, db)
    result = await read(db)
    assert db.events == ["scalar", "scalars", "execute", "scalars", ("root", 12)]
    assert db.sql[1][2] == {"user_id_1": 7, "id_1": [1, 2]}
    assert db.sql[2][2] == {
        "question_version_id_1": [101, 102],
        "knowledge_point_id_1": [12],
    }
    assert "knowledge_points.is_active IS true" in db.sql[2][1]
    assert result["points"] == [
        {
            "knowledge_point_id": 12,
            "name": "last",
            "question_count": 2,
            "correct_count": 1,
            "wrong_count": 1,
            "mastery_before": 50.0,
            "mastery_after": 70.0,
            "mastery_delta": 20.0,
            "confidence_after": 0.8,
            "status_after": "developing",
        }
    ]


@pytest.mark.asyncio
async def test_read_ranks_all_points_before_24_cap_and_counts_full_touched_set(
    monkeypatch,
):
    ids = list(range(1, 31))
    db = Database(
        session=session(
            legacy([[kp, 60, 0.6, 2] for kp in ids]), results=[{"record_id": 1}]
        ),
        scalars=[[record(1)], [state(kp, 70) for kp in ids if kp != 30]],
        execute=[[(101, kp, "") for kp in ids]],
    )
    root_port(monkeypatch, db)
    result = await read(db)
    assert result["touched_knowledge_point_count"] == 30
    assert len(result["points"]) == 24
    assert [item["knowledge_point_id"] for item in result["points"]] == [
        30,
        *range(1, 24),
    ]
    assert result["points"][0]["name"] == "知识点 30"
    assert result["points"][0]["mastery_after"] is None
    assert result["points"][0]["status_after"] == "no_data"


@pytest.mark.asyncio
async def test_chapter_uses_only_knowledge_map_aggregation_and_original_rounding(
    monkeypatch,
):
    db = Database(session=session(legacy(root=[50.04, 0.123456, 3, 4, 99])))
    root_port(
        monkeypatch,
        db,
        {
            "name": "current",
            "subtree_mastery_score": 70.06,
            "subtree_coverage_ratio": 0.654321,
            "subtree_weak_knowledge_points": "2",
            "subtree_reliable_knowledge_points": "8",
            "subtree_trainable_knowledge_points": "10",
        },
    )
    result = await read(db)
    assert result["chapter"] == {
        "root_knowledge_point_id": 12,
        "root_name": "signed name",
        "mastery_before": 50.0,
        "mastery_after": 70.1,
        "mastery_delta": 20.0,
        "coverage_before": 0.1235,
        "coverage_after": 0.6543,
        "weak_before": 3,
        "weak_after": 2,
        "reliable_before": 4,
        "reliable_after": 8,
        "trainable_knowledge_points": 10,
    }
    assert db.events == ["scalar", ("root", 12)]


@pytest.mark.asyncio
async def test_durable_leaf_chapter_ignores_subtree_and_baseline_tuple(monkeypatch):
    db = Database(session=session(legacy(root=(80, 0.8, 8)), snapshot=durable()))
    root_port(
        monkeypatch,
        db,
        {
            "status": "weak",
            "mastery_score": 30,
            "subtree_mastery_score": 99,
            "trainable_question_count": 1,
            "subtree_trainable_knowledge_points": 100,
        },
    )
    chapter = (await read(db))["chapter"]
    assert chapter["root_knowledge_point_id"] == 20
    assert chapter["mastery_before"] is None and chapter["mastery_after"] == 30.0
    assert chapter["coverage_before"] == 0 and chapter["coverage_after"] == 1
    assert chapter["weak_after"] == chapter["reliable_after"] == 1
    assert chapter["trainable_knowledge_points"] == 1


@pytest.mark.asyncio
async def test_numeric_and_status_patch_ports_remain_dynamic(monkeypatch):
    db = Database(
        session=session(legacy([[12, 5, 0.1, 1]]), results=[{"record_id": 1}]),
        scalars=[[record(1)], [state(12)]],
        execute=[[(101, 12, "point")]],
    )
    root_port(monkeypatch, db)
    monkeypatch.setattr(svc, "_MAX_SUMMARY_POINTS", 1)
    monkeypatch.setattr(svc, "_number_or_none", lambda *args, **kw: 123.0)
    monkeypatch.setattr(svc, "_delta", lambda *args: -321.0)
    monkeypatch.setattr(svc, "_state_status", lambda *args: "patched")
    point = (await read(db))["points"][0]
    assert point["mastery_before"] == 123.0
    assert point["mastery_delta"] == -321.0 and point["status_after"] == "patched"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "baseline,error_type,expected",
    [
        ({"points": [[12, 0, 0, "bad"]]}, ValueError, ["scalar", "scalars"]),
        ({"points": [[12, 0, 0, 1]]}, TypeError, ["scalar", "scalars"]),
    ],
)
async def test_read_malformed_values_raise_before_later_io(
    monkeypatch, baseline, error_type, expected
):
    rows = [record(1, None)] if error_type is TypeError else [record(1)]
    db = Database(
        session=session(
            {**legacy(), "_baseline": baseline}, results=[{"record_id": 1}]
        ),
        scalars=[rows],
    )
    root_port(monkeypatch, db)
    with pytest.raises(error_type):
        await read(db)
    assert db.events == expected


@pytest.mark.asyncio
async def test_read_state_conversion_error_precedes_root_aggregation(monkeypatch):
    db = Database(
        session=session(legacy([[12, 0, 0, 1]]), results=[{"record_id": 1}]),
        scalars=[[record(1)], [state(12, "invalid")]],
        execute=[[(101, 12, "point")]],
    )
    root_port(monkeypatch, db)
    with pytest.raises(ValueError):
        await read(db)
    assert db.events == ["scalar", "scalars", "execute", "scalars"]
