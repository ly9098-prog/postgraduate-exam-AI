"""Contracts for the study-report detail split.

Pins the observable behaviour of ``get_review_plan`` and
``get_wrong_questions_summary``: the count/detail/knowledge-point statement order,
the optional subject join, the first-knowledge-point rule and the projected payload.
Drives only the database double, so the same file passes when the frozen HEAD
implementations are replayed through the pytest plugin.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services import study_report_service as srs

NOW = datetime(2026, 10, 28, 3, 4, 5)


class Result:
    def __init__(self, *, rows=(), scalar=0):
        self._rows = list(rows)
        self._scalar = scalar

    def all(self):
        return list(self._rows)

    def one(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        return self._scalar

    def scalar_one(self):
        return self._scalar


class FakeDb:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        if self.responses:
            return self.responses.pop(0)
        return Result()

    def sql(self, index):
        return " ".join(str(self.statements[index]).split())

    def params(self, index):
        return dict(self.statements[index].compile().params)


def state_row(**kw):
    defaults = {
        "question_id": 100,
        "box_level": 2,
        "wrong_count": 3,
        "correct_count": 4,
        "next_review_at": NOW - timedelta(hours=6),
    }
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def content_row(question_id=200, **kw):
    defaults = {
        "question_id": question_id,
        "box_level": 1,
        "wrong_count": 4,
        "correct_count": 1,
        "answer_count": 6,
        "next_review_at": NOW - timedelta(days=2),
        "last_answered_at": NOW - timedelta(days=3),
        "q_content": [{"type": "text", "text": "题干"}],
    }
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def kp_row(question_id, kp_id, name):
    return SimpleNamespace(
        question_id=question_id, knowledge_point_id=kp_id, name=name
    )


@pytest.fixture
def frozen_now(monkeypatch):
    monkeypatch.setattr(srs, "utcnow", lambda: NOW)
    return NOW


# ── get_review_plan ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_review_plan_statement_order_and_payload(frozen_now):
    rows = [state_row(question_id=100), state_row(question_id=101, box_level=5)]
    db = FakeDb(
        [
            Result(scalar=7),
            Result(scalar=2),
            Result(rows=rows),
            Result(rows=[kp_row(100, 11, "函数"), kp_row(101, 12, "极限")]),
        ]
    )

    payload = await srs.get_review_plan(db, user_id=7)

    assert payload["due_count"] == 7
    assert payload["overdue_count"] == 2
    assert payload["today_recommended_count"] == 2
    assert [item["question_id"] for item in payload["items"]] == [100, 101]
    assert payload["items"][0] == {
        "question_id": 100,
        "knowledge_point_id": 11,
        "knowledge_point_name": "函数",
        "box_level": 2,
        "wrong_count": 3,
        "correct_count": 4,
        "next_review_at": rows[0].next_review_at,
        "overdue_days": 0,
        "priority": srs.calc_priority(0, 3, 2),
    }
    assert payload["items"][1]["knowledge_point_name"] == "极限"

    assert len(db.statements) == 4
    assert "questions" not in db.sql(0)
    assert "next_review_at <=" in db.sql(0)
    assert "next_review_at <" in db.sql(1)
    assert db.params(0)["next_review_at_1"] == NOW
    assert db.params(1)["next_review_at_1"] == NOW - timedelta(days=1)
    order = db.sql(2).lower()
    assert "order by" in order
    assert "limit" in order
    assert order.index("next_review_at asc") < order.index("box_level asc")
    assert order.index("box_level asc") < order.index("wrong_count desc")
    assert "is not null" in order
    assert "next_review_at <= :next_review_at_1" in db.sql(2)
    assert db.params(2)["next_review_at_1"] == NOW
    assert db.params(2)["param_1"] == 20
    assert "user_question_state.correct_count" in db.sql(2)
    assert "join knowledge_points" in db.sql(3).lower()


@pytest.mark.asyncio
async def test_review_plan_uses_one_consistent_timestamp(monkeypatch):
    """The entry reads the clock once and projects every row against that instant."""
    calls = []

    def clock():
        calls.append(1)
        return NOW if len(calls) == 1 else NOW + timedelta(days=5)

    monkeypatch.setattr(srs, "utcnow", clock)
    row = state_row(question_id=100, next_review_at=NOW - timedelta(hours=6))
    db = FakeDb([Result(scalar=1), Result(scalar=0), Result(rows=[row]), Result(rows=[])])

    payload = await srs.get_review_plan(db, user_id=7)

    assert len(calls) == 1
    assert payload["items"][0]["overdue_days"] == 0


@pytest.mark.asyncio
async def test_review_plan_propagates_limit_to_the_detail_query(frozen_now):
    db = FakeDb([Result(scalar=1), Result(scalar=0), Result(rows=[])])

    await srs.get_review_plan(db, user_id=7, limit=3)

    assert len(db.statements) == 3
    assert db.params(2)["param_1"] == 3


@pytest.mark.asyncio
async def test_review_plan_subject_scope_joins_questions(frozen_now):
    db = FakeDb(
        [
            Result(scalar=1),
            Result(scalar=0),
            Result(rows=[state_row(question_id=100)]),
            Result(rows=[]),
        ]
    )

    await srs.get_review_plan(db, user_id=7, subject_id=3)

    assert "join questions" in db.sql(0).lower()
    assert "questions.subject_id = " in db.sql(0)
    assert "join questions" in db.sql(2).lower()
    assert "questions.subject_id = " in db.sql(2)


@pytest.mark.asyncio
async def test_review_plan_skips_knowledge_points_without_rows(frozen_now):
    db = FakeDb([Result(scalar=0), Result(scalar=0), Result(rows=[])])

    payload = await srs.get_review_plan(db, user_id=7)

    assert payload == {
        "due_count": 0,
        "overdue_count": 0,
        "today_recommended_count": 0,
        "items": [],
    }
    assert len(db.statements) == 3


@pytest.mark.asyncio
async def test_review_plan_keeps_the_first_knowledge_point(frozen_now):
    db = FakeDb(
        [
            Result(scalar=1),
            Result(scalar=0),
            Result(rows=[state_row(question_id=100)]),
            Result(
                rows=[
                    kp_row(100, 11, "先"),
                    kp_row(100, 12, "后"),
                ]
            ),
        ]
    )

    payload = await srs.get_review_plan(db, user_id=7)

    assert payload["items"][0]["knowledge_point_id"] == 11
    assert payload["items"][0]["knowledge_point_name"] == "先"
    order = db.sql(3).lower()
    assert "order by question_knowledge_points.question_id" in order
    assert "question_knowledge_points.id" in order


# ── get_wrong_questions_summary ──────────────────────────────────────


@pytest.mark.asyncio
async def test_wrong_summary_counts_and_payload(frozen_now):
    rows = [
        content_row(200, wrong_count=4),
        content_row(201, wrong_count=1, correct_count=0, box_level=3),
    ]
    db = FakeDb(
        [
            Result(scalar=9),
            Result(scalar=3),
            Result(rows=rows),
            Result(rows=[kp_row(200, 21, "数列")]),
        ]
    )

    payload = await srs.get_wrong_questions_summary(db, user_id=7)

    assert payload["wrong_question_count"] == 9
    assert payload["repeated_wrong_question_count"] == 3
    assert [item["question_id"] for item in payload["items"]] == [200, 201]
    assert payload["items"][0]["status"] == "repeated_wrong"
    assert payload["items"][0]["title"] == "题干"
    assert payload["items"][0]["knowledge_point_name"] == "数列"
    assert payload["items"][1]["status"] == "not_mastered"
    assert payload["items"][1]["knowledge_point_id"] is None

    assert len(db.statements) == 4
    assert db.sql(0).count("wrong_count >=") == 1
    assert db.sql(1).count("wrong_count >=") == 2
    # The repeated-wrong count carries both thresholds: >= 3 and the caller's floor.
    assert db.params(1)["wrong_count_1"] == 3
    assert db.params(1)["wrong_count_2"] == 1
    assert db.params(0)["wrong_count_1"] == 1
    assert "join questions" in db.sql(2).lower()
    assert "questions.content as q_content" in db.sql(2).lower()
    assert "wrong_count >=" in db.sql(2)
    assert db.params(2)["wrong_count_1"] == 1
    assert db.params(2)["param_1"] == 20
    order = db.sql(2).lower()
    assert "wrong_count desc" in order
    assert order.index("wrong_count desc") < order.index("box_level asc")
    assert "last_answered_at desc nulls last" in order
    assert "limit" in order
    assert "join knowledge_points" in db.sql(3).lower()


@pytest.mark.asyncio
async def test_wrong_summary_threshold_scope_and_subject_join(frozen_now):
    db = FakeDb(
        [
            Result(scalar=1),
            Result(scalar=0),
            Result(rows=[content_row(200)]),
            Result(rows=[]),
        ]
    )

    await srs.get_wrong_questions_summary(db, user_id=7, subject_id=3, min_wrong_count=2)

    assert db.sql(0).count("wrong_count >=") == 1
    assert db.params(0)["wrong_count_1"] == 2
    assert db.params(1)["wrong_count_2"] == 2
    assert db.params(1)["wrong_count_1"] == 3
    assert "join questions" in db.sql(0).lower()
    assert "questions.subject_id = " in db.sql(0)
    assert "questions.subject_id = " in db.sql(2)
    assert db.params(2)["wrong_count_1"] == 2
    assert db.params(2)["param_1"] == 20


@pytest.mark.asyncio
async def test_wrong_summary_propagates_limit_and_floor(frozen_now):
    db = FakeDb([Result(scalar=1), Result(scalar=0), Result(rows=[])])

    await srs.get_wrong_questions_summary(db, user_id=7, limit=5, min_wrong_count=4)

    assert len(db.statements) == 3
    assert db.params(0)["wrong_count_1"] == 4
    assert db.params(1)["wrong_count_1"] == 3
    assert db.params(1)["wrong_count_2"] == 4
    assert db.params(2)["wrong_count_1"] == 4
    assert db.params(2)["param_1"] == 5


@pytest.mark.asyncio
async def test_wrong_summary_detail_query_always_joins_questions(frozen_now):
    db = FakeDb(
        [
            Result(scalar=1),
            Result(scalar=0),
            Result(rows=[content_row(200)]),
            Result(rows=[]),
        ]
    )

    await srs.get_wrong_questions_summary(db, user_id=7)

    # Counts only join for subject scoping; the detail reader always joins so the
    # projected content is never missing.
    assert "join questions" not in db.sql(0).lower()
    assert "join questions" in db.sql(2).lower()
    assert "questions.subject_id" not in db.sql(2)


@pytest.mark.asyncio
async def test_wrong_summary_skips_knowledge_points_without_rows(frozen_now):
    db = FakeDb([Result(scalar=0), Result(scalar=0), Result(rows=[])])

    payload = await srs.get_wrong_questions_summary(db, user_id=7, limit=5)

    assert payload == {
        "wrong_question_count": 0,
        "repeated_wrong_question_count": 0,
        "items": [],
    }
    assert len(db.statements) == 3


@pytest.mark.asyncio
async def test_wrong_summary_keeps_the_first_knowledge_point(frozen_now):
    db = FakeDb(
        [
            Result(scalar=1),
            Result(scalar=0),
            Result(rows=[content_row(200)]),
            Result(rows=[kp_row(200, 21, "先"), kp_row(200, 22, "后")]),
        ]
    )

    payload = await srs.get_wrong_questions_summary(db, user_id=7)

    assert payload["items"][0]["knowledge_point_id"] == 21
    assert payload["items"][0]["knowledge_point_name"] == "先"


@pytest.mark.asyncio
async def test_wrong_summary_status_precedence(frozen_now):
    rows = [
        content_row(200, wrong_count=3, correct_count=5),
        content_row(201, wrong_count=2, correct_count=0),
        content_row(202, wrong_count=2, correct_count=4),
    ]
    db = FakeDb([Result(scalar=3), Result(scalar=1), Result(rows=rows), Result(rows=[])])

    payload = await srs.get_wrong_questions_summary(db, user_id=7)

    assert [item["status"] for item in payload["items"]] == [
        "repeated_wrong",
        "not_mastered",
        "needs_review",
    ]
