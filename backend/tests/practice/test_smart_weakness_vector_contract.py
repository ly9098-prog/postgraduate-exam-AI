"""Compatibility contracts for the smart weakness-vector supplement."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select

from app.services import practice_service as svc


class Rows:
    def __init__(self, values, scalar=0):
        self._values = values
        self._scalar = scalar

    def scalar(self):
        return self._scalar

    def scalars(self):
        return self

    def all(self):
        return self._values


def question(qid: int):
    return SimpleNamespace(id=qid)


def make_db(rows, scalar=0):
    db = Mock()
    db.execute = AsyncMock(return_value=Rows(rows, scalar))
    db.scalar = AsyncMock(return_value=scalar)
    return db


def make_recall(qid: int, score: float = 0.9, similarity: float = 0.8):
    return {
        "question_id": qid,
        "recommend_score": score,
        "similarity": similarity,
    }


@pytest.fixture
def vector_ports(monkeypatch):
    import app.services.mastery_service as mastery_service
    import app.services.vector_retrieval_service as vector_service

    mastery = AsyncMock(return_value=[{"name": "链表"}])
    vector = AsyncMock(return_value=[])
    monkeypatch.setattr(mastery_service, "get_user_weak_knowledge_points", mastery)
    monkeypatch.setattr(vector_service, "vector_recall_by_text", vector)
    return SimpleNamespace(mastery=mastery, vector=vector)


@pytest.mark.asyncio
async def test_no_weak_points_random_fallback_overfetches_and_filters_exclusions(
    vector_ports,
    monkeypatch,
):
    vector_ports.mastery.return_value = []
    db = make_db([])
    rows = [question(1), question(2), question(3), question(4)]
    random_fallback = AsyncMock(return_value=rows)
    monkeypatch.setattr(svc, "get_practice_questions", random_fallback)
    monkeypatch.setattr(
        svc,
        "_compute_weak_knowledge_points",
        AsyncMock(return_value=[]),
    )

    result, metadata = await svc._smart_weakness_vector(
        db,
        9,
        "ds",
        count=2,
        exclude_answered=True,
        no_repeat_days=3,
        use_leitner=False,
        exclude_ids={1, 3},
        subject_ids=[2],
    )

    assert [row.id for row in result] == [2, 4]
    assert set(metadata) == {2, 4}
    assert all(meta["strategy"] == "random_fallback" for meta in metadata.values())
    assert metadata[2]["recommend_reason"] == "随机推荐（薄弱知识点数据不足）"
    vector_ports.mastery.assert_awaited_once_with(db, 9, "ds", limit=5)
    vector_ports.vector.assert_not_awaited()
    random_fallback.assert_awaited_once_with(
        db=db,
        user_id=9,
        subject_code="ds",
        count=4,
        mode="random",
        exclude_answered=True,
        no_repeat_days=3,
        use_leitner=False,
        subject_ids=[2],
    )


@pytest.mark.asyncio
async def test_mastery_failure_falls_back_to_computed_weak_points(
    vector_ports, monkeypatch, caplog
):
    vector_ports.mastery.side_effect = RuntimeError("mastery unavailable")
    vector_ports.vector.return_value = [make_recall(7)]
    db = make_db([question(7)])
    compute = AsyncMock(return_value=[{"name": "队列"}])
    monkeypatch.setattr(svc, "_compute_weak_knowledge_points", compute)

    with caplog.at_level(logging.WARNING):
        result, metadata = await svc._smart_weakness_vector(
            db, 9, "ds", count=1, subject_ids=[2]
        )

    assert [row.id for row in result] == [7]
    assert metadata[7]["strategy"] == "smart_vector"
    vector_ports.vector.assert_awaited_once_with(
        db=db,
        user_id=9,
        subject="ds",
        query_text=(
            "科目：ds。请推荐这些薄弱知识点的练习题：队列。"
            "要求题目适合查漏补缺和变式训练。"
        ),
        count=1,
        exclude_answered=False,
        no_repeat_days=None,
    )
    compute.assert_awaited_once_with(db, 9, [2])
    failure = next(
        record
        for record in caplog.records
        if "mastery_service.get_user_weak_knowledge_points failed" in record.message
    )
    assert failure.name == "app.services.practice_service"


@pytest.mark.asyncio
async def test_vector_result_filters_exclusions_and_repeat_window(
    vector_ports, monkeypatch
):
    vector_ports.vector.return_value = [make_recall(1), make_recall(2), make_recall(3)]
    db = make_db([question(1), question(2), question(3)])
    monkeypatch.setattr(
        svc,
        "_build_excluded_question_subquery",
        Mock(return_value=select(1).scalar_subquery()),
    )

    result, metadata = await svc._smart_weakness_vector(
        db,
        9,
        "ds",
        count=2,
        exclude_answered=True,
        no_repeat_days=3,
        exclude_ids={1},
        subject_ids=[2],
    )

    assert [row.id for row in result] == [2, 3]
    assert set(metadata) == {2, 3}
    assert all(meta["strategy"] == "smart_vector" for meta in metadata.values())
    assert metadata[2]["recommend_score"] == 0.9
    assert metadata[2]["similarity"] == 0.8
    assert metadata[2]["recommend_reason"] == "薄弱知识点推荐：链表"
    assert vector_ports.vector.await_args.kwargs["no_repeat_days"] == 3
    assert vector_ports.vector.await_args.kwargs["exclude_answered"] is True


@pytest.mark.asyncio
async def test_full_vector_result_does_not_random_fill(vector_ports):
    vector_ports.vector.return_value = [make_recall(1), make_recall(2)]
    db = make_db([question(1), question(2)])

    result, metadata = await svc._smart_weakness_vector(
        db, 9, "ds", count=2, subject_ids=[2]
    )

    assert [row.id for row in result] == [1, 2]
    assert set(metadata) == {1, 2}
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_empty_vector_result_fills_without_failure_warning(vector_ports, caplog):
    vector_ports.vector.return_value = []
    db = make_db([question(8)])
    db.execute = AsyncMock(
        side_effect=[
            Rows([], scalar=1),
            Rows([question(8)]),
        ]
    )

    with caplog.at_level(logging.WARNING):
        result, metadata = await svc._smart_weakness_vector(
            db, 9, "ds", count=1, subject_ids=[2]
        )

    assert [row.id for row in result] == [8]
    assert metadata[8]["strategy"] == "kp_fallback"
    assert "weakness_vector 向量召回失败" not in caplog.text


@pytest.mark.asyncio
async def test_vector_shortfall_random_fill_excludes_vector_and_request_ids(
    vector_ports,
):
    vector_ports.vector.return_value = [make_recall(1)]
    db = make_db([question(1)])
    fill_rows = [question(4), question(5)]
    db.execute = AsyncMock(
        side_effect=[
            Rows([question(1)]),
            Rows([], scalar=2),
            Rows(fill_rows),
        ]
    )

    result, metadata = await svc._smart_weakness_vector(
        db,
        9,
        "ds",
        count=3,
        exclude_answered=True,
        no_repeat_days=3,
        exclude_ids={2, 3},
        subject_ids=[2],
    )

    assert [row.id for row in result] == [1, 4, 5]
    assert set(metadata) == {1, 4, 5}
    assert metadata[1]["strategy"] == "smart_vector"
    assert metadata[4]["strategy"] == "kp_fallback"
    assert metadata[5]["recommend_reason"] == "薄弱知识点补齐"
    assert db.execute.await_count == 3


@pytest.mark.asyncio
async def test_vector_failure_falls_back_and_preserves_cancellation(
    vector_ports, monkeypatch, caplog
):
    vector_ports.vector.side_effect = RuntimeError("vector unavailable")
    db = make_db([], scalar=1)
    db.execute = AsyncMock(
        side_effect=[
            Rows([], scalar=1),
            Rows([question(8)]),
        ]
    )

    with caplog.at_level(logging.WARNING):
        result, metadata = await svc._smart_weakness_vector(
            db, 9, "ds", count=1, subject_ids=[2]
        )

    assert [row.id for row in result] == [8]
    assert metadata[8]["strategy"] == "kp_fallback"
    failure = next(
        record
        for record in caplog.records
        if "weakness_vector 向量召回失败" in record.message
    )
    assert failure.name == "app.services.practice_service"

    vector_ports.vector.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await svc._smart_weakness_vector(make_db([]), 9, "ds", count=1, subject_ids=[2])
