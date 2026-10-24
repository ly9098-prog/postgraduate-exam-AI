"""Real-SQLite exam attempt semantics regressions.

These tests intentionally use the service layer with real ORM rows. They keep
the scope to state/idempotency/atomic submit boundaries that are awkward to
prove with endpoint mocks; full API/OpenAPI/device coverage remains separate.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register all relationship targets before create_all
from app.core.database import Base
from app.models.admin import QuestionVersion, Subject
from app.models.error_diagnosis import WrongQuestionErrorDiagnosis
from app.models.exam import ExamAnswer, ExamAttempt, ExamPaper, ExamPaperQuestion
from app.models.practice_record import PracticeRecord
from app.models.question import Question
from app.models.task_outbox import TaskOutbox
from app.models.user import User
from app.models.wrong_question import WrongQuestion
from app.services import exam_service


async def _make_database(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'exam-attempt.db'}",
        connect_args={"timeout": 30},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed(session_factory) -> tuple[int, int, int]:
    """Create one published paper with one correct and one wrong item."""
    async with session_factory() as db:
        db.add_all(
            [
                User(id=1, openid="exam-user"),
                Subject(
                    id=1,
                    code="os",
                    name="操作系统",
                    level=1,
                    path="os",
                    is_active=True,
                ),
                Question(
                    id=1,
                    subject_id=1,
                    question_type="single_choice",
                    content={"text": "correct"},
                    options={"A": "A", "B": "B"},
                    answer="A",
                    current_version_id=1,
                ),
                Question(
                    id=2,
                    subject_id=1,
                    question_type="single_choice",
                    content={"text": "wrong"},
                    options={"A": "A", "B": "B"},
                    answer="B",
                    current_version_id=2,
                ),
                QuestionVersion(
                    id=1,
                    question_id=1,
                    version=1,
                    subject_id=1,
                    question_type="single_choice",
                    content={"text": "correct"},
                    options={"A": "A", "B": "B"},
                    answer="A",
                    difficulty=3,
                    is_active=True,
                ),
                QuestionVersion(
                    id=2,
                    question_id=2,
                    version=1,
                    subject_id=1,
                    question_type="single_choice",
                    content={"text": "wrong"},
                    options={"A": "A", "B": "B"},
                    answer="B",
                    difficulty=3,
                    is_active=True,
                ),
                ExamPaper(
                    id=1,
                    title="408 选择题套卷",
                    paper_type="past_exam_choice",
                    duration_sec=600,
                    version=1,
                    status="published",
                    is_active=True,
                ),
            ]
        )
        await db.flush()
        db.add_all(
            [
                ExamPaperQuestion(
                    id=1,
                    paper_id=1,
                    question_id=1,
                    question_version_id=1,
                    position=1,
                    score=2,
                    section_subject_id=1,
                ),
                ExamPaperQuestion(
                    id=2,
                    paper_id=1,
                    question_id=2,
                    question_version_id=2,
                    position=2,
                    score=3,
                    section_subject_id=1,
                ),
            ]
        )
        await db.commit()
    return 1, 1, 2


@pytest.mark.asyncio
async def test_start_submit_replay_and_atomic_downstream_records(tmp_path):
    engine, session_factory = await _make_database(tmp_path)
    await _seed(session_factory)
    try:
        async with session_factory() as db:
            view = await exam_service.start_attempt(db, 1, 1, "request-0001")
            item_ids = [question["item_id"] for question in view["questions"]]
            assert item_ids == [1, 2]
            assert all(question["question_version_id"] in (1, 2) for question in view["questions"])

        async with session_factory() as db:
            result = await exam_service.submit_attempt(
                db,
                view["id"],
                1,
                final_answers=[
                    {"item_id": 1, "selected_answer": "a", "marked_for_review": True, "used_time": 20},
                    {"item_id": 2, "selected_answer": "A", "marked_for_review": False, "used_time": 30},
                ],
            )

        assert result["attempt_status"] == "submitted"
        assert result["answered_count"] == 2
        assert result["correct_count"] == 1
        assert result["choice_score"] == 2
        assert result["total_choice_score"] == 5
        assert result["subject_breakdown"][0]["subject_code"] == "os"

        async with session_factory() as db:
            replay = await exam_service.submit_attempt(db, view["id"], 1, final_answers=[])
            assert replay == result

        async with session_factory() as db:
            same_request = await exam_service.start_attempt(db, 1, 1, "request-0001")
            assert same_request["id"] == view["id"]

        async with session_factory() as db:
            attempt = await db.get(ExamAttempt, view["id"])
            assert attempt.status == "submitted"
            assert attempt.result_snapshot == result

            answers = list(
                (await db.execute(select(ExamAnswer).order_by(ExamAnswer.id))).scalars()
            )
            assert [answer.selected_answer for answer in answers] == ["A", "A"]
            assert [answer.is_correct for answer in answers] == [True, False]
            assert [answer.answer_revision for answer in answers] == [1, 1]

            practice_count = await db.scalar(select(func.count(PracticeRecord.id)))
            wrong_count = await db.scalar(select(func.count(WrongQuestion.id)))
            diagnosis_count = await db.scalar(
                select(func.count(WrongQuestionErrorDiagnosis.id)).where(
                    WrongQuestionErrorDiagnosis.source_context == "exam"
                )
            )
            outbox_count = await db.scalar(
                select(func.count(TaskOutbox.id)).where(
                    TaskOutbox.task_type == "answer_projection"
                )
            )
            assert practice_count == 2
            assert wrong_count == 1
            assert diagnosis_count == 1
            assert outbox_count == 2
    finally:
        await engine.dispose()
