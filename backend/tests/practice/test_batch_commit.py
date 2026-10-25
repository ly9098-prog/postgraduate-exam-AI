"""Contract for transactional practice-batch commit orchestration."""

from __future__ import annotations

import pytest

from app.services.practice.batch_commit import persist_claimed_practice_batch


class SessionObj:
    def __init__(self):
        self.submission_response = None


class Persisted:
    records = []
    prewarm_wrong_questions = ["wrong"]
    wrong_question_ids = {}


def base_overrides():
    return {
        "session_obj": SessionObj(),
        "persist_records": None,
        "load_revision_kp_names": None,
        "build_response_by_question": None,
        "build_response": lambda **kwargs: {"response": True},
        "persisted_knowledge_session": lambda _context: None,
        "build_cleanup": lambda **kwargs: "cleanup",
        "execute": None,
        "commit": None,
        "rollback": None,
        "persist_records_kwargs": {},
        "issued_revisions": {1: 11},
        "issued_order": [1],
        "skipped_questions": [],
        "total_correct": 1,
        "total_wrong": 0,
        "knowledge_context": None,
        "entry_context": None,
        "user_id": 2,
        "batch_payload": {},
        "all_question_ids": [1],
    }


@pytest.mark.asyncio
async def test_commit_persists_response_cleanup_and_returns_prewarm_items():
    calls = []
    overrides = base_overrides()

    async def persist_records(_db, **kwargs):
        calls.append(("records", kwargs))
        return Persisted

    async def load_revision_kp_names(_db, revision_ids):
        calls.append(("kps", list(revision_ids)))
        return {11: ["kp"]}

    def build_response_by_question(**kwargs):
        calls.append(("by_question", kwargs))
        return {1: {"question_id": 1}}

    async def execute(statement):
        calls.append(("execute", statement))

    async def commit():
        calls.append(("commit",))

    async def rollback():
        calls.append(("rollback",))

    overrides.update(
        persist_records=persist_records,
        load_revision_kp_names=load_revision_kp_names,
        build_response_by_question=build_response_by_question,
        execute=execute,
        commit=commit,
        rollback=rollback,
        persist_records_kwargs={"user_id": 2},
    )
    result = await persist_claimed_practice_batch(None, **overrides)

    assert result.response_payload == {"response": True}
    assert result.prewarm_wrong_questions == ["wrong"]
    assert overrides["session_obj"].submission_response == {"response": True}
    assert [call[0] for call in calls] == [
        "records",
        "kps",
        "by_question",
        "execute",
        "commit",
    ]


@pytest.mark.asyncio
async def test_any_commit_failure_rolls_back_whole_claimed_transaction():
    calls = []
    overrides = base_overrides()

    async def persist_records(_db, **kwargs):
        return Persisted

    async def load_revision_kp_names(_db, revision_ids):
        return {}

    async def execute(statement):
        calls.append("execute")
        raise RuntimeError("projection failure")

    async def rollback():
        calls.append("rollback")

    async def commit():
        calls.append("commit")

    overrides.update(
        persist_records=persist_records,
        load_revision_kp_names=load_revision_kp_names,
        build_response_by_question=lambda **kwargs: {},
        execute=execute,
        rollback=rollback,
        commit=commit,
    )
    with pytest.raises(RuntimeError, match="projection failure"):
        await persist_claimed_practice_batch(None, **overrides)
    assert calls == ["execute", "rollback"]
