"""Contracts for the dashboard and study-hub knowledge-diagnosis request chain."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects import postgresql

from app.api.v1 import study_hub as route
from app.services import knowledge_diagnosis_service as service
from app.services import study_hub_service

NOW = datetime(2026, 10, 30, 12)


def scope(root=10):
    return {
        "practice_mode": "knowledge_chapter",
        "subject_id": 7,
        "root_knowledge_point_id": root,
        "root_name": "chapter",
        "served_knowledge_point_ids": [11, 11, 0, -1, "12"],
        "resolved_knowledge_point_ids": [11, 12, 13],
        "served_knowledge_point_count": 2,
        "resolved_knowledge_point_count": 3,
    }


def row(request_id="request", *, snapshot=None, root=10, finished_at=NOW):
    return SimpleNamespace(
        request_id=request_id,
        scope_root_knowledge_point_id=root,
        scope_snapshot=scope(root) if snapshot is None else snapshot,
        question_count=10,
        correct_count=7,
        finished_at=finished_at,
    )


def subject_map():
    return {
        "subject": {
            "subject_id": 7,
            "subject_code": "data_structure",
            "subject_name": "DS",
            "coverage_ratio": 0.5,
            "reliable_knowledge_points": 2,
            "trainable_knowledge_points": 4,
            "weak_knowledge_points": 1,
        },
        "nodes": [
            {
                "knowledge_point_id": 10,
                "name": "chapter",
                "depth": 0,
                "has_children": True,
                "ancestor_ids": [],
                "subtree_trainable_knowledge_points": 4,
                "subtree_reliable_knowledge_points": 2,
                "subtree_weak_knowledge_points": 1,
                "subtree_coverage_ratio": 0.5,
                "subtree_mastery_score": 60,
                "subtree_status": "weak",
            }
        ],
    }


@pytest.fixture
def db():
    return SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(all=Mock(return_value=[]))),
        commit=AsyncMock(),
        flush=AsyncMock(),
        add=Mock(),
        rollback=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_session_query_and_scope_projection_preserve_order(db):
    good = row("first")
    missing_scope = row("missing")
    missing_scope.scope_snapshot = None
    rows = [
        good,
        missing_scope,
        row("mismatch", snapshot=scope(11)),
        row("invalid-root", root=0),
        row("last", finished_at=NOW - timedelta(days=2)),
    ]
    db.execute.return_value.all.return_value = rows
    since = NOW - timedelta(days=30)
    result = await service._load_chapter_sessions(
        db, user_id=9, subject_id=7, since=since
    )
    assert [item["request_id"] for item in result] == ["first", "last"]
    assert result[0]["served_ids"] == {11, 12}
    assert result[0]["resolved_ids"] == {11, 12, 13}
    assert result[0]["finished_at"] is good.finished_at
    stmt = db.execute.await_args.args[0]
    compiled = stmt.compile(dialect=postgresql.dialect())
    text = " ".join(str(compiled).split())
    assert "practice_sessions.user_id =" in text
    assert "practice_sessions.subject_id =" in text
    assert "practice_sessions.finished_at >=" in text
    assert (
        "ORDER BY practice_sessions.finished_at DESC, practice_sessions.id DESC" in text
    )
    assert set(compiled.params.values()) == {
        9,
        7,
        "knowledge_chapter",
        "completed",
        since,
    }
    db.commit.assert_not_awaited()
    db.flush.assert_not_awaited()
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_missing_map_returns_before_clock_or_history(db, monkeypatch):
    monkeypatch.setattr(
        service.knowledge_map_service, "get_subject_map", AsyncMock(return_value=None)
    )
    clock = Mock(side_effect=AssertionError("must not read the clock"))
    monkeypatch.setattr(service, "utcnow", clock)
    assert await service.get_knowledge_diagnosis(db, 9, 7) is None
    clock.assert_not_called()
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "days,expected", [(-1, 1), (0, 1), (30, 30), (365, 365), (366, 365)]
)
async def test_request_clamps_period_and_keeps_read_only_report(
    db, monkeypatch, days, expected
):
    monkeypatch.setattr(
        service.knowledge_map_service,
        "get_subject_map",
        AsyncMock(return_value=subject_map()),
    )
    monkeypatch.setattr(service, "utcnow", lambda: NOW)
    db.execute.return_value.all.return_value = [row()]
    result = await service.get_knowledge_diagnosis(db, 9, 7, days=days)
    assert result["period_days"] == result["report"]["period_days"] == expected
    assert result["report"]["question_count"] == 10
    assert result["report"]["accuracy"] == 0.7
    assert result["report"]["practiced_chapter_count"] == 1
    assert result["chapters"][0]["scope_coverage_ratio"] == 0.6667
    assert result["primary_recommendation"] is result["recommendations"][0]
    assert (
        result["primary_recommendation"]["route_params"]["source"]
        == "knowledge_diagnosis"
    )
    assert result["recent_sessions"][0]["finished_at"] == "2026-10-30T12:00:00Z"
    assert result["scope"] == "exam408"
    assert (
        NOW - timedelta(days=expected)
        in db.execute.await_args.args[0].compile().params.values()
    )
    for operation in (db.commit, db.flush, db.rollback):
        operation.assert_not_awaited()
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_recent_history_slices_five_before_invalid_time_filter(db, monkeypatch):
    monkeypatch.setattr(
        service.knowledge_map_service,
        "get_subject_map",
        AsyncMock(return_value=subject_map()),
    )
    monkeypatch.setattr(service, "utcnow", lambda: NOW)
    sessions = [
        {
            "request_id": str(index),
            "root_knowledge_point_id": 10,
            "root_name": "chapter",
            "question_count": 10,
            "correct_count": 7,
            "served_ids": {11},
            "resolved_ids": {11, 12},
            "served_count": 1,
            "resolved_count": 2,
            "finished_at": None if index == 0 else NOW,
        }
        for index in range(6)
    ]
    monkeypatch.setattr(
        service, "_load_chapter_sessions", AsyncMock(return_value=sessions)
    )
    result = await service.get_knowledge_diagnosis(db, 9, 7)
    assert [item["request_id"] for item in result["recent_sessions"]] == [
        "1",
        "2",
        "3",
        "4",
    ]
    assert result["report"]["session_count"] == 6
    assert result["report"]["last_7_days_session_count"] == 5


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error", [RuntimeError("history unavailable"), asyncio.CancelledError()]
)
async def test_query_errors_and_cancellation_propagate_without_writes(
    db, monkeypatch, error
):
    monkeypatch.setattr(
        service.knowledge_map_service,
        "get_subject_map",
        AsyncMock(return_value=subject_map()),
    )
    monkeypatch.setattr(service, "utcnow", lambda: NOW)
    db.execute.side_effect = error
    with pytest.raises(type(error)) as caught:
        await service.get_knowledge_diagnosis(db, 9, 7)
    assert caught.value is error
    db.commit.assert_not_awaited()
    db.rollback.assert_not_awaited()


def test_chapter_projection_keeps_root_order_and_distinct_accuracy_scope_rules():
    nodes = [
        {"knowledge_point_id": 3, "depth": 1},
        {
            "knowledge_point_id": 2,
            "name": "second",
            "depth": 0,
            "subtree_coverage_ratio": 2,
            "subtree_mastery_score": 60.55,
        },
        {"knowledge_point_id": 1, "depth": 0, "subtree_mastery_score": None},
    ]
    result = service._root_chapter_reports(
        nodes,
        {
            2: {
                "question_count": 2,
                "correct_count": 3,
                "scope_served_count": 4,
                "scope_resolved_count": 2,
                "last_practiced_at": NOW,
            },
        },
    )
    assert [item["knowledge_point_id"] for item in result] == [2, 1]
    assert result[0]["accuracy"] == 1.5
    assert result[0]["scope_coverage_ratio"] == result[0]["coverage_ratio"] == 1.0
    assert result[0]["mastery_score"] == round(60.55, 1)
    assert result[1]["accuracy"] is None and result[1]["mastery_score"] is None


def test_projection_reads_replaced_service_helpers_at_each_use(monkeypatch):
    calls = []

    def replacement(value):
        calls.append("replacement")
        return "second"

    def initial(value):
        calls.append("initial")
        monkeypatch.setattr(service, "serialize_utc_datetime", replacement)
        return "first"

    monkeypatch.setattr(service, "serialize_utc_datetime", initial)
    nodes = [{"knowledge_point_id": value, "depth": 0} for value in (1, 2)]
    stats = {value: {"last_practiced_at": NOW} for value in (1, 2)}
    result = service._root_chapter_reports(nodes, stats)
    assert [item["last_practiced_at"] for item in result] == ["first", "second"]
    assert calls == ["initial", "replacement"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query,status",
    [
        ("subject_id=7&days=30", 200),
        ("subject_id=0", 422),
        ("subject_id=7&days=0", 422),
        ("subject_id=7&days=366", 422),
    ],
)
async def test_public_route_uses_authenticated_user_and_validates_query(
    db, monkeypatch, query, status
):
    app = FastAPI()
    app.include_router(route.router)
    app.dependency_overrides[route.get_db] = lambda: db
    app.dependency_overrides[route.get_current_user] = lambda: SimpleNamespace(id=9)
    loader = AsyncMock(return_value=subject_map())
    monkeypatch.setattr(service.knowledge_map_service, "get_subject_map", loader)
    monkeypatch.setattr(service, "utcnow", lambda: NOW)
    db.execute.return_value.all.return_value = [row()]
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"/api/v1/study-hub/knowledge-diagnosis?{query}")
    assert response.status_code == status
    if status == 200:
        loader.assert_awaited_once_with(db, 9, 7)
        assert response.json()["report"]["accuracy"] == 0.7
        assert (
            response.json()["primary_recommendation"]["route_params"]["subject_id"] == 7
        )
    else:
        loader.assert_not_awaited()
        db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_public_route_keeps_missing_subject_error(db, monkeypatch):
    app = FastAPI()
    app.include_router(route.router)
    app.dependency_overrides[route.get_db] = lambda: db
    app.dependency_overrides[route.get_current_user] = lambda: SimpleNamespace(id=9)
    monkeypatch.setattr(
        service.knowledge_map_service, "get_subject_map", AsyncMock(return_value=None)
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/study-hub/knowledge-diagnosis?subject_id=7"
        )
    assert response.status_code == 404
    assert response.json()["detail"] == "408 科目不存在、已停用或当前大纲不可用"
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_study_hub_consumes_real_diagnosis_recommendation(db, monkeypatch):
    current_map = subject_map()
    monkeypatch.setattr(
        service.knowledge_map_service,
        "get_subject_map",
        AsyncMock(return_value=current_map),
    )
    monkeypatch.setattr(service, "utcnow", lambda: NOW)
    db.execute.return_value.all.return_value = [row()]
    task = await study_hub_service._chapter_task_for_subject(
        db, 9, current_map["subject"], service
    )
    assert task["knowledge_point_id"] == 10
    assert task["subject_id"] == 7
    assert task["estimated_question_count"] == 4
    db.execute.assert_awaited_once()
    db.commit.assert_not_awaited()
