"""Fixed contracts for evaluated practice-batch side-effect persistence."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.services.practice.batch_persistence import persist_practice_batch_records


class FlushDb:
    def __init__(self, events=None, failure=None):
        self.added = []
        self.events = events if events is not None else []
        self.failure = failure
        self.next_id = iter(range(70, 100))

    def add(self, record):
        record.id = next(self.next_id)
        self.added.append(record)
        self.events.append(("add", record.question_id))

    async def flush(self):
        self.events.append(("flush",))
        if self.failure is not None:
            raise self.failure


def question(
    question_id="1", version="901", subject="3", question_type="single_choice"
):
    return SimpleNamespace(
        id=question_id,
        question_version_id=version,
        subject_id=subject,
        question_type=question_type,
    )


async def run(db, **overrides):
    values = {
        "user_id": 8,
        "evaluated_answers": [],
        "answer_request_ids": {},
        "mode": "random",
        "now": datetime(2026, 10, 28, tzinfo=UTC),
        "record_wrong": None,
        "create_outbox": None,
        "persist_wrong_answer": None,
    }
    values.update(overrides)
    return await persist_practice_batch_records(db, **values)


@pytest.mark.asyncio
async def test_staging_preserves_constructor_order_coercion_and_single_flush():
    events = []
    reads = []
    db = FlushDb(events)

    class Question:
        @property
        def id(self):
            reads.append("id")
            return "9"

        @property
        def question_version_id(self):
            reads.append("version")
            return "909"

        @property
        def subject_id(self):
            reads.append("subject")
            return "3"

        @property
        def question_type(self):
            reads.append("type")
            return "multiple_choice"

    result = await run(
        db,
        evaluated_answers=[
            (Question(), True, " A ", None),
            (question("2"), True, "B", 4),
        ],
        create_outbox=lambda *args, **kwargs: asyncio.sleep(0),
    )

    assert reads == ["id", "version", "subject", "type", "id"]
    assert [record.question_id for record in db.added] == [9, 2]
    assert [record.question_version_id for record in db.added] == [909, 901]
    assert [record.user_answer for record in db.added] == [" A ", "B"]
    assert [record.projection_state for record in db.added] == ["pending", "pending"]
    assert [record.mode for record in db.added] == ["random", "random"]
    assert result.records[0][0] is db.added[0]
    assert result.prewarm_wrong_questions == []
    assert result.wrong_question_ids == {}
    assert events == [("add", 9), ("add", 2), ("flush",)]


@pytest.mark.asyncio
async def test_wrong_side_effects_interleave_before_each_outbox():
    events = []
    db = FlushDb(events)
    wrong_ids = iter((71, 72))

    async def record_wrong(_db, user_id, question_id, answer, **kwargs):
        events.append(("wrong", user_id, question_id, answer, dict(kwargs)))
        return SimpleNamespace(id=next(wrong_ids))

    async def persist_wrong_answer(_db, **kwargs):
        events.append(("diagnosis", kwargs["record"].question_id, kwargs["wrong"].id))
        return {"question": kwargs["question"].id}

    async def create_outbox(_db, **kwargs):
        events.append(("outbox", kwargs))

    result = await run(
        db,
        evaluated_answers=[
            (question("1"), False, "B", 4),
            (question("2"), False, "C", 5),
        ],
        answer_request_ids={1: "r1", 2: "r2"},
        record_wrong=record_wrong,
        persist_wrong_answer=persist_wrong_answer,
        create_outbox=create_outbox,
    )

    assert [event[0] for event in events] == [
        "add",
        "add",
        "flush",
        "wrong",
        "diagnosis",
        "outbox",
        "wrong",
        "diagnosis",
        "outbox",
    ]
    assert events[3][-1] == {"question_version_id": 901, "commit": False}
    assert events[5][1] == {"practice_record_id": 70, "request_id": "r1"}
    assert events[8][1] == {"practice_record_id": 71, "request_id": "r2"}
    assert result.prewarm_wrong_questions[0].id == 71
    assert result.wrong_question_ids == {1: 71, 2: 72}
    assert db.added[0]._error_diagnosis_payload == {"question": "1"}


@pytest.mark.asyncio
async def test_correct_only_skips_wrong_ports_and_reads_request_after_flush():
    events = []
    db = FlushDb(events)

    class Requests(dict):
        def get(self, key, default=None):
            events.append(("request", key, default))
            return super().get(key, default)

    async def create_outbox(_db, **kwargs):
        events.append(("outbox", kwargs))

    result = await run(
        db,
        evaluated_answers=[(question("3"), True, "A", 0)],
        answer_request_ids=Requests({3: "r3"}),
        create_outbox=create_outbox,
        record_wrong=lambda *args, **kwargs: pytest.fail("wrong path"),
        persist_wrong_answer=lambda *args, **kwargs: pytest.fail("diagnosis path"),
    )

    assert result.prewarm_wrong_questions == []
    assert events == [
        ("add", 3),
        ("flush",),
        ("request", 3, None),
        ("outbox", {"practice_record_id": 70, "request_id": "r3"}),
    ]


@pytest.mark.asyncio
async def test_empty_batch_skips_flush_and_all_side_effect_ports():
    db = FlushDb()
    result = await run(
        db,
        record_wrong=lambda *args, **kwargs: pytest.fail("wrong"),
        create_outbox=lambda *args, **kwargs: pytest.fail("outbox"),
        persist_wrong_answer=lambda *args, **kwargs: pytest.fail("diagnosis"),
    )

    assert db.added == []
    assert result.records == []
    assert db.events == []


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["flush", "wrong", "diagnosis", "outbox"])
async def test_failures_stop_later_records_and_preserve_identity(stage):
    failure = (
        asyncio.CancelledError("stop") if stage == "outbox" else RuntimeError(stage)
    )
    events = []
    db = FlushDb(events, failure if stage == "flush" else None)

    async def record_wrong(*args, **kwargs):
        events.append("wrong")
        if stage == "wrong":
            raise failure
        return SimpleNamespace(id=71)

    async def persist_wrong_answer(*args, **kwargs):
        events.append("diagnosis")
        if stage == "diagnosis":
            raise failure
        return {}

    async def create_outbox(*args, **kwargs):
        events.append("outbox")
        if stage == "outbox":
            raise failure

    answers = [(question("1"), False, "B", 1), (question("2"), False, "C", 2)]
    with pytest.raises(type(failure)) as caught:
        await run(
            db,
            evaluated_answers=answers,
            record_wrong=record_wrong,
            persist_wrong_answer=persist_wrong_answer,
            create_outbox=create_outbox,
        )
    assert caught.value is failure
    expected_wrong = 0 if stage == "flush" else 1
    expected_diagnosis = 1 if stage in {"diagnosis", "outbox"} else 0
    assert events.count("wrong") == expected_wrong
    assert events.count("diagnosis") == expected_diagnosis


@pytest.mark.asyncio
async def test_int_coercion_failures_keep_the_original_exception_before_side_effects():
    db = FlushDb()
    failure = ValueError("bad id")

    class BadId:
        @property
        def id(self):
            raise failure

    with pytest.raises(ValueError) as caught:
        await run(
            db,
            evaluated_answers=[(BadId(), True, "A", 0)],
            record_wrong=lambda *args, **kwargs: pytest.fail("wrong"),
            create_outbox=lambda *args, **kwargs: pytest.fail("outbox"),
            persist_wrong_answer=lambda *args, **kwargs: pytest.fail("diagnosis"),
        )
    assert caught.value is failure
    assert db.added == [] and db.events == []
