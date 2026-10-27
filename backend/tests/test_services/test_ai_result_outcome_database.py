"""Terminal dispatch uses actual outcome/persistence callbacks on isolated SQLite."""

import pytest
from sqlalchemy import select

from app.models.ai_chat import AiChat
from app.models.wrong_question import WrongQuestion
from app.services.ai.analysis_result_review import resolve_analysis_outcome
from tests.test_services.analysis_persistence_support import harness
from tests.test_services.test_ai_analysis_compatibility import (
    _make_database,
    _seed_subject_user,
)
from tests.test_services.test_ai_analysis_persistence_database import (
    CommitBoundary,
    seed_wrong_question,
)
from tests.test_services.test_ai_result_outcome_callbacks import arguments


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["repair", "valid"])
@pytest.mark.parametrize("image_count", [0, 2])
@pytest.mark.parametrize("fail_second", [False, True])
async def test_terminal_dispatch_preserves_durability_and_visual_counts(
    monkeypatch, tmp_path, kind, image_count, fail_second
):
    engine, sessions = await _make_database(tmp_path)
    try:
        subject_id, user_id = await _seed_subject_user(sessions)
        async with sessions() as db:
            wrong, wrong_id = await seed_wrong_question(db, subject_id, user_id)
            h = harness(monkeypatch)
            h.args.update(wrong_question=wrong, user_id=user_id)
            h.db = CommitBoundary(db, fail_second)
            images = ["synthetic-image"] * image_count
            review, kwargs = arguments(h, kind, images)
            if fail_second:
                with pytest.raises(RuntimeError, match="synthetic second commit failure"):
                    await resolve_analysis_outcome(h.db, review, **kwargs)
                await db.rollback()
            else:
                response = await resolve_analysis_outcome(h.db, review, **kwargs)
                assert response["visual_input_count"] == image_count
                assert response["content"] is (h.safe if kind == "repair" else h.parsed)
            assert h.db.commits == 2
        async with sessions() as db:
            await assert_terminal_state(db, wrong_id, user_id, kind, image_count, fail_second)
    finally:
        await engine.dispose()


async def assert_terminal_state(db, wrong_id, user_id, kind, image_count, fail_second):
    persisted = await db.get(WrongQuestion, wrong_id)
    chats = list(await db.scalars(select(AiChat).where(AiChat.user_id == user_id)))
    assert persisted.ai_analysis["_meta"]["visual_input_count"] == image_count
    assert persisted.ai_analysis["_meta"]["input_mode"] == ("vision" if image_count else "text")
    assert persisted.ai_analysis["_meta"]["grounding_guard"] == (
        "repaired" if kind == "repair" else "passed"
    )
    assert persisted.ai_analysis["mistake_diagnosis"] == ("safe" if kind == "repair" else "merged")
    assert len(chats) == (0 if fail_second else 1)
    if chats:
        assert chats[0].context_snapshot["visual_input_count"] == image_count
        assert chats[0].tokens_used == 31
