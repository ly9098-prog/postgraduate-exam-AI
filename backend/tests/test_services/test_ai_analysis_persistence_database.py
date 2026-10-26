"""Real isolated SQLite durability; no provider, Redis or production data."""

import pytest
from sqlalchemy import select

from app.models.ai_chat import AiChat
from app.models.wrong_question import WrongQuestion
from tests.test_services.analysis_persistence_support import (
    business_expectation,
    execute,
    harness,
)
from tests.test_services.test_ai_analysis_compatibility import (
    _make_database,
    _make_question,
    _make_version,
    _seed_subject_user,
)


class CommitBoundary:
    def __init__(self, db, fail_second):
        self.db = db
        self.fail_second = fail_second
        self.commits = 0

    async def commit(self):
        self.commits += 1
        if self.fail_second and self.commits == 2:
            raise RuntimeError("synthetic second commit failure")
        await self.db.commit()

    def add(self, value):
        self.db.add(value)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["repair", "valid"])
@pytest.mark.parametrize("fail_second", [False, True])
async def test_analysis_is_durable_before_chat_commit(
    monkeypatch, tmp_path, kind, fail_second
):
    engine, sessions = await _make_database(tmp_path)
    try:
        subject_id, user_id = await _seed_subject_user(sessions)
        async with sessions() as db:
            wrong, wrong_id = await seed_wrong_question(db, subject_id, user_id)
            h = harness(monkeypatch)
            h.args.update(wrong_question=wrong, user_id=user_id)
            h.db = CommitBoundary(db, fail_second)
            expected_business, _ = business_expectation(h, kind)
            if fail_second:
                with pytest.raises(
                    RuntimeError, match="synthetic second commit failure"
                ):
                    await execute(h, kind)
                await db.rollback()
            else:
                await execute(h, kind)
            assert h.db.commits == 2
        async with sessions() as db:
            persisted = await db.get(WrongQuestion, wrong_id)
            chats = list(
                await db.scalars(select(AiChat).where(AiChat.user_id == user_id))
            )
            if kind == "valid":
                expected_business["mistake_diagnosis"] = "merged"
            assert {
                k: v for k, v in persisted.ai_analysis.items() if k != "_meta"
            } == expected_business
            assert len(chats) == (0 if fail_second else 1)
            if chats:
                assert chats[0].ai_response == "provider-content"
                assert chats[0].context_snapshot["visual_input_count"] == 2
                assert chats[0].tokens_used == 31
    finally:
        await engine.dispose()


async def seed_wrong_question(db, subject_id, user_id):
    question = _make_question(subject_id)
    db.add(question)
    await db.flush()
    version = _make_version(question.id, 1)
    db.add(version)
    await db.flush()
    wrong = WrongQuestion(
        user_id=user_id,
        question_id=question.id,
        question_version_id=version.id,
        wrong_answer="A",
    )
    db.add(wrong)
    await db.commit()
    wrong_id = wrong.id
    return wrong, wrong_id
