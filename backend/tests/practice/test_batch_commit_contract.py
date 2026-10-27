"""Fixed contracts for claimed practice-batch transaction orchestration."""

from __future__ import annotations

import asyncio

import pytest

from app.services.practice.batch_commit import persist_claimed_practice_batch
from tests.practice.batch_commit_contract_support import Persisted, overrides


@pytest.mark.asyncio
async def test_exact_ordering_kwargs_identity_and_response_assignment():
    events = []
    db = object()
    persisted = Persisted([("record",)], ["wrong"], {1: 71})
    overrides_ = overrides(events)

    async def persist_records(_db, **kwargs):
        events.append(("records", _db, kwargs))
        return persisted

    async def load_revision_kp_names(_db, revision_ids):
        events.append(("kps", _db, list(revision_ids)))
        return {11: ["kp"]}

    def build_response_by_question(**kwargs):
        events.append(("by-question", list(kwargs.items())))
        return {1: {"question_id": 1}}

    def build_response(**kwargs):
        events.append(("response", list(kwargs.items())))
        return {"payload": True}

    def build_cleanup(**kwargs):
        events.append(("cleanup", kwargs))
        return "cleanup-statement"

    async def execute(statement):
        events.append(("execute", statement))

    async def commit():
        events.append(("commit",))

    async def rollback():
        events.append(("rollback",))

    overrides_.update(
        persist_records=persist_records,
        load_revision_kp_names=load_revision_kp_names,
        build_response_by_question=build_response_by_question,
        build_response=build_response,
        build_cleanup=build_cleanup,
        execute=execute,
        commit=commit,
        rollback=rollback,
    )
    result = await persist_claimed_practice_batch(db, **overrides_)

    assert result.response_payload == {"payload": True}
    assert result.prewarm_wrong_questions is persisted.prewarm_wrong_questions
    assert [event[0] for event in events] == [
        "records",
        "kps",
        "by-question",
        "response",
        "response-set",
        "cleanup",
        "execute",
        "commit",
    ]
    assert events[0][2] == {"user_id": 8}
    assert events[2][1] == [
        ("records", persisted.records),
        ("skipped_questions", []),
        ("revision_kps", {11: ["kp"]}),
        ("wrong_question_ids", {1: 71}),
    ]
    assert [key for key, _ in events[3][1]] == [
        "response_by_question",
        "issued_order",
        "total_correct",
        "total_wrong",
        "skipped_questions",
        "knowledge_context",
        "entry_context",
        "persisted_knowledge_session",
    ]
    assert events[3][1][1] == ("issued_order", [1, 2])
    assert events[3][1][2:6] == [
        ("total_correct", 1),
        ("total_wrong", 1),
        ("skipped_questions", []),
        ("knowledge_context", {"root": 1}),
    ]
    assert events[3][1][6] == ("entry_context", {"source": "test"})
    assert events[3][1][-1][1] is overrides_["persisted_knowledge_session"]
    assert events[5][1] == {
        "user_id": 8,
        "batch_payload": {"rid": "submit-1"},
        "all_question_ids": [1, 2],
    }
    assert overrides_["session_obj"].submission_response is result.response_payload
    assert events[-1] == ("commit",)


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup", [None, False, 0, ""])
async def test_cleanup_none_skips_execute_while_other_falsy_statements_execute(cleanup):
    events = []
    overrides_ = overrides(events)

    async def persist_records(_db, **kwargs):
        return Persisted([], [], {})

    async def load_revision_kp_names(_db, revision_ids):
        return {}

    async def execute(statement):
        events.append(("execute", statement))

    async def commit():
        events.append(("commit",))

    overrides_.update(
        persist_records=persist_records,
        load_revision_kp_names=load_revision_kp_names,
        build_response_by_question=lambda **kwargs: {},
        build_cleanup=lambda **kwargs: cleanup,
        execute=execute,
        commit=commit,
    )
    await persist_claimed_practice_batch(None, **overrides_)

    if cleanup is None:
        assert events == [("response-set", {"response": True}), ("commit",)]
    else:
        assert events == [
            ("response-set", {"response": True}),
            ("execute", cleanup),
            ("commit",),
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stage,failure",
    [
        ("records", RuntimeError("records")),
        ("kps", RuntimeError("kps")),
        ("by-question", RuntimeError("by-question")),
        ("response", RuntimeError("response")),
        ("cleanup", RuntimeError("cleanup")),
        ("execute", asyncio.CancelledError("execute")),
        ("commit", KeyboardInterrupt("commit")),
    ],
)
async def test_any_stage_failure_rolls_back_and_stops_later_ports(stage, failure):
    events = []
    overrides_ = overrides(events)

    async def persist_records(_db, **kwargs):
        events.append("records")
        if stage == "records":
            raise failure
        return Persisted([], [], {})

    async def load_revision_kp_names(_db, revision_ids):
        events.append("kps")
        if stage == "kps":
            raise failure
        return {}

    def build_response_by_question(**kwargs):
        events.append("by-question")
        if stage == "by-question":
            raise failure
        return {}

    def build_response(**kwargs):
        events.append("response")
        if stage == "response":
            raise failure
        return {}

    def build_cleanup(**kwargs):
        events.append("cleanup")
        if stage == "cleanup":
            raise failure
        return "cleanup"

    async def execute(statement):
        events.append("execute")
        if stage == "execute":
            raise failure

    async def commit():
        events.append("commit")
        if stage == "commit":
            raise failure

    async def rollback():
        events.append("rollback")

    overrides_.update(
        persist_records=persist_records,
        load_revision_kp_names=load_revision_kp_names,
        build_response_by_question=build_response_by_question,
        build_response=build_response,
        build_cleanup=build_cleanup,
        execute=execute,
        commit=commit,
        rollback=rollback,
    )
    with pytest.raises(type(failure)) as caught:
        await persist_claimed_practice_batch(None, **overrides_)
    assert caught.value is failure
    expected = {
        "records": ["records"],
        "kps": ["records", "kps"],
        "by-question": ["records", "kps", "by-question"],
        "response": ["records", "kps", "by-question", "response"],
        "cleanup": [
            "records",
            "kps",
            "by-question",
            "response",
            ("response-set", {}),
            "cleanup",
        ],
        "execute": [
            "records",
            "kps",
            "by-question",
            "response",
            ("response-set", {}),
            "cleanup",
            "execute",
        ],
        "commit": [
            "records",
            "kps",
            "by-question",
            "response",
            ("response-set", {}),
            "cleanup",
            "execute",
            "commit",
        ],
    }[stage]
    expected.append("rollback")
    assert events == expected


@pytest.mark.asyncio
async def test_rollback_failure_replaces_the_original_exception():
    events = []
    original = RuntimeError("persist")
    rollback_failure = RuntimeError("rollback")
    overrides_ = overrides(events)

    async def persist_records(_db, **kwargs):
        raise original

    async def rollback():
        events.append("rollback")
        raise rollback_failure

    overrides_.update(persist_records=persist_records, rollback=rollback)
    with pytest.raises(RuntimeError) as caught:
        await persist_claimed_practice_batch(None, **overrides_)
    assert caught.value is rollback_failure
    assert events == ["rollback"]
