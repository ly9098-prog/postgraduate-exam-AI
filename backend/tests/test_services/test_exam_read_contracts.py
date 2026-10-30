"""Original exam read-entry projection, helper lookup and clock contracts."""

from datetime import datetime
from types import SimpleNamespace as Row
from unittest.mock import AsyncMock

import pytest

from app.services import exam_service as service
from tests.test_services.test_exam_attempt_semantics import _make_database, _seed


@pytest.mark.asyncio
async def test_attempt_question_projection_keeps_helper_order_and_answer_privacy(
    monkeypatch,
):
    now = datetime(2026, 1, 1)
    attempt = Row(id=2, paper_id=3, status="in_progress", started_at=now)
    paper = Row(
        id=3, title="paper", paper_type="mock_choice", year=2026, duration_sec=60
    )
    answer = Row(
        question_id=5,
        question_version_id=6,
        selected_answer="A",
        marked_for_review=True,
        used_time=9,
        answered_at=now,
    )
    item = Row(id=4, position=1, score=2, section_subject_id=7, question_version_id=6)
    revision = Row(
        id=6,
        question_id=5,
        question_type="single_choice",
        content={"private": 1},
        options={"A": "text"},
        image_url=None,
    )
    subject = Row(code="os", name="OS")
    monkeypatch.setattr(
        service, "_get_attempt_for_user", AsyncMock(return_value=attempt)
    )
    monkeypatch.setattr(
        service, "_load_paper_with_summary", AsyncMock(return_value=(paper, 1, 2))
    )
    monkeypatch.setattr(
        service,
        "_load_attempt_rows",
        AsyncMock(return_value=[(answer, item, revision, subject)]),
    )
    monkeypatch.setattr(service, "_elapsed_seconds", lambda _: 10)
    seen = []

    def money(value):
        seen.append(("money", value))
        return 2.5

    def content(value):
        seen.append(("content", value))
        monkeypatch.setattr(service, "_student_options", lambda _: {"new": True})
        return {"safe": True}

    monkeypatch.setattr(service, "_money", money)
    monkeypatch.setattr(service, "_student_content", content)
    result = await service.get_attempt_view(Row(), 2, 1)
    assert result["remaining_sec"] == 50
    question = result["questions"][0]
    assert list(question) == [
        "item_id",
        "question_id",
        "question_version_id",
        "position",
        "score",
        "subject_id",
        "subject_code",
        "subject_name",
        "question_type",
        "content",
        "options",
        "image_url",
    ]
    assert question["content"] == {"safe": True}
    assert question["options"] == {"new": True}
    assert result["answers"][0]["selected_answer"] == "A"
    assert seen == [("money", 2), ("content", revision.content)]


@pytest.mark.asyncio
async def test_paper_list_display_expiry_is_read_only_and_skips_abandoned(monkeypatch):
    paper = Row(
        id=1,
        title="paper",
        paper_type="mock_choice",
        year=None,
        source=None,
        duration_sec=60,
        version=1,
    )
    abandoned = Row(id=8, paper_id=1, status="abandoned")
    current = Row(
        id=7, paper_id=1, status="in_progress", started_at=datetime(2026, 1, 1)
    )
    terminal = Row(id=6, paper_id=1, status="submitted", score=3)
    db = Row(
        execute=AsyncMock(
            side_effect=[
                Row(all=lambda: [(paper, 2, 5)]),
                Row(scalars=lambda: Row(all=lambda: [abandoned, current, terminal])),
            ]
        )
    )
    monkeypatch.setattr(service, "_elapsed_seconds", lambda _: 60)
    result = await service.list_published_papers(db, 1)
    assert result[0]["latest_attempt_id"] == 7
    assert result[0]["latest_attempt_status"] == "expired"
    assert result[0]["best_choice_score"] == 3
    assert current.status == "in_progress"


@pytest.mark.asyncio
async def test_result_weak_points_keep_count_order_and_wrong_result_links(
    tmp_path, monkeypatch
):
    from app.services import ai_prewarm_worker

    engine, factory = await _make_database(tmp_path)
    try:
        await _seed(factory)
        enqueue = AsyncMock()
        monkeypatch.setattr(ai_prewarm_worker, "enqueue_prewarm", enqueue)
        monkeypatch.setattr(
            service,
            "load_revision_kp_names",
            AsyncMock(
                return_value={1: ["first", "shared"], 2: ["higher-score", "shared"]}
            ),
        )
        async with factory() as db:
            attempt = await service.start_attempt(db, 1, 1, "projection-wrong-1")
        async with factory() as db:
            result = await service.submit_attempt(
                db,
                attempt["id"],
                1,
                final_answers=[
                    {"item_id": 1, "selected_answer": "B"},
                    {"item_id": 2, "selected_answer": "A"},
                ],
            )
        assert result["weak_knowledge_points"] == [
            {"name": "shared", "miss_count": 2, "lost_score": 5},
            {"name": "first", "miss_count": 1, "lost_score": 2},
            {"name": "higher-score", "miss_count": 1, "lost_score": 3},
        ]
        assert result["choice_score"] == 0
        assert result["wrong_count"] == 2
        assert enqueue.await_count == 2
        assert all(
            q["wrong_question_id"] and q["error_diagnosis"] for q in result["questions"]
        )
        assert list(result["questions"][0]) == [
            "item_id",
            "question_id",
            "question_version_id",
            "position",
            "subject_id",
            "subject_code",
            "subject_name",
            "score",
            "earned_score",
            "selected_answer",
            "correct_answer",
            "is_correct",
            "status",
            "marked_for_review",
            "used_time",
            "content",
            "options",
            "analysis",
            "image_url",
            "knowledge_points",
            "wrong_question_id",
            "error_diagnosis",
        ]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_snapshot_encoding_failure_does_not_commit_the_exam(
    tmp_path, monkeypatch
):
    from sqlalchemy import func, select

    from app.models.exam import ExamAttempt
    from app.models.practice_record import PracticeRecord
    from app.models.task_outbox import TaskOutbox

    engine, factory = await _make_database(tmp_path)
    try:
        await _seed(factory)
        async with factory() as db:
            attempt = await service.start_attempt(db, 1, 1, "projection-failure-1")

        def fail(_result):
            raise RuntimeError("synthetic encoding failure")

        monkeypatch.setattr(service, "jsonable_encoder", fail)
        async with factory() as db:
            with pytest.raises(RuntimeError, match="synthetic encoding failure"):
                await service.submit_attempt(
                    db,
                    attempt["id"],
                    1,
                    final_answers=[{"item_id": 1, "selected_answer": "A"}],
                )
        async with factory() as db:
            persisted = await db.get(ExamAttempt, attempt["id"])
            assert persisted.status == "in_progress"
            assert persisted.result_snapshot is None
            assert await db.scalar(select(func.count(PracticeRecord.id))) == 0
            assert await db.scalar(select(func.count(TaskOutbox.id))) == 0
    finally:
        await engine.dispose()
