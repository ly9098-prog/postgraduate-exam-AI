"""Transactional persistence contract for evaluated practice batches."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.services.practice.batch_persistence import persist_practice_batch_records


class Db:
    def __init__(self):
        self.added = []
        self.flushed = 0
        self.next_record_id = iter((78, 79))

    def add(self, obj):
        obj.id = next(self.next_record_id)
        self.added.append(obj)

    async def flush(self):
        self.flushed += 1


def question(question_id: int):
    return SimpleNamespace(
        id=question_id,
        question_version_id=900000 + question_id,
        subject_id=3,
        question_type="single_choice",
    )


@pytest.mark.asyncio
async def test_records_are_flushed_before_wrong_book_side_effects():
    db = Db()
    wrong = SimpleNamespace(id=77)
    wrong_calls = []
    diagnosis_calls = []
    outbox_calls = []

    async def record_wrong(*args, **kwargs):
        wrong_calls.append((args, kwargs))
        return wrong

    async def create_outbox(*args, **kwargs):
        outbox_calls.append((args, kwargs))

    async def persist_wrong_answer(*args, **kwargs):
        diagnosis_calls.append(kwargs)
        return {"diagnosis": "serialized"}

    result = await persist_practice_batch_records(
        db,
        user_id=8,
        evaluated_answers=[
            (question(1), False, "B", 4),
            (question(2), True, "A", 5),
        ],
        answer_request_ids={1: "request-1", 2: None},
        mode="random",
        now=datetime(2026, 10, 26, tzinfo=UTC),
        record_wrong=record_wrong,
        create_outbox=create_outbox,
        persist_wrong_answer=persist_wrong_answer,
    )

    assert len(result.records) == 2
    assert result.prewarm_wrong_questions == [wrong]
    assert result.wrong_question_ids == {1: 77}
    assert db.flushed == 1
    assert db.added[0].user_id == 8
    assert db.added[0].projection_state == "pending"
    assert wrong_calls[0][1]["commit"] is False
    assert diagnosis_calls[0]["wrong"].id == 77
    assert result.records[0][0]._error_diagnosis_payload == {"diagnosis": "serialized"}
    assert outbox_calls[0][1] == {
        "practice_record_id": 78,
        "request_id": "request-1",
    }
    assert outbox_calls[1][1] == {"practice_record_id": 79, "request_id": None}


@pytest.mark.asyncio
async def test_correct_only_batch_skips_wrong_book_and_diagnosis(monkeypatch):
    db = Db()
    outbox_calls = []

    async def record_wrong(*args, **kwargs):
        raise AssertionError("wrong-book path must not run")

    async def persist_wrong_answer(**kwargs):
        raise AssertionError("diagnosis path must not run")

    async def create_outbox(*args, **kwargs):
        outbox_calls.append(kwargs)

    result = await persist_practice_batch_records(
        db,
        user_id=8,
        evaluated_answers=[(question(2), True, "A", None)],
        answer_request_ids={2: None},
        mode="sequential",
        now=datetime(2026, 10, 26, tzinfo=UTC),
        record_wrong=record_wrong,
        create_outbox=create_outbox,
        persist_wrong_answer=persist_wrong_answer,
    )

    assert result.prewarm_wrong_questions == []
    assert result.wrong_question_ids == {}
    assert len(outbox_calls) == 1
