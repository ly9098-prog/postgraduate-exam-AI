from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.admin import QuestionVersion, Subject
from app.models.question import Question
from app.schemas.guest import GuestAnswerSubmit
from app.services import guest_practice
from app.services.guest_evaluation import evaluate_guest_answers
from app.services.guest_practice import (
    GuestSubjectUnavailableError,
    decode_guest_batch_token,
    load_guest_questions,
    load_guest_subject_tree,
)


@pytest_asyncio.fixture
async def database(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        for model in (Subject, Question, QuestionVersion):
            await connection.run_sync(model.__table__.create)
    monkeypatch.setattr(
        guest_practice, "resolve_subject_id_to_code",
        AsyncMock(return_value=("ds", "数据结构")),
    )
    monkeypatch.setattr(
        guest_practice, "resolve_practice_subject_scope",
        AsyncMock(return_value=(False, [1])),
    )
    monkeypatch.setattr(
        guest_practice, "load_revision_kp_names", AsyncMock(return_value={}),
    )
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add(Subject(id=1, code="ds", name="数据结构", path="1"))
        session.add(Subject(id=2, code="os", name="操作系统", path="2"))
        await session.commit()
        yield session
    await engine.dispose()


async def add_question(database, question_id, **overrides):
    attributes = {
        "subject_id": 1, "question_type": "single_choice", "content": {"text": "测试题"},
        "answer": "A", "is_active": True, "review_status": "approved",
    }
    attributes.update(overrides)
    question = Question(id=question_id, **attributes)
    database.add(question)
    if question_id != 99:
        database.add(QuestionVersion(
            id=question_id * 10, question_id=question_id, version=1,
            subject_id=attributes["subject_id"],
            question_type=attributes["question_type"], content={"text": "不可变题干"},
            options={"A": "甲", "B": "乙"}, answer="A", analysis="原始解析",
            difficulty=3, is_active=True, raw_content="管理原文", source_file="/private/path",
        ))
    await database.commit()
    return question


@pytest.mark.asyncio
async def test_candidate_query_respects_requested_count_and_published_question_scope(database):
    for question_id in range(1, 9):
        await add_question(database, question_id)
    await add_question(database, 90, review_status="pending")
    await add_question(database, 91, is_active=False)
    await add_question(database, 92, subject_id=2)
    await add_question(database, 99)
    result = await load_guest_questions(database, 1, count=5)
    assert result.total == 5
    assert len({question.id for question in result.questions}) == 5
    assert all(question.id in range(1, 9) for question in result.questions)
    batch = decode_guest_batch_token(result.batch_token)
    assert set(batch.question_ids) == {question.id for question in result.questions}
    for question in result.questions:
        assert batch.revisions[question.id] == question.question_version_id
        assert not {"answer", "analysis", "raw_content", "source_file"} & question.model_dump().keys()
    assert not database.new and not database.dirty


@pytest.mark.asyncio
async def test_candidate_query_uses_requested_guest_random_count(database):
    for question_id in range(1, 16):
        await add_question(database, question_id)
    result = await load_guest_questions(database, 1, count=10)
    assert result.total == 10
    batch = decode_guest_batch_token(result.batch_token)
    assert batch.requested_count == 10
    assert len(batch.question_ids) == 10
    assert not database.new and not database.dirty


@pytest.mark.asyncio
async def test_guest_question_count_rejects_nonstandard_values(database):
    with pytest.raises(guest_practice.GuestPracticeError):
        await load_guest_questions(database, 1, count=7)


@pytest.mark.asyncio
async def test_few_questions_and_immutable_grading_after_version_change(database):
    question = await add_question(database, 1)
    preview = await load_guest_questions(database, 1)
    assert preview.total == 1
    database.add(QuestionVersion(
        id=11, question_id=1, version=2, subject_id=1, question_type="single_choice",
        content={"text": "改版后题干"}, answer="B", difficulty=3, is_active=True,
    ))
    question.answer = "B"
    await database.commit()
    result = await evaluate_guest_answers(
        database, batch=decode_guest_batch_token(preview.batch_token),
        answers=[GuestAnswerSubmit(question_id=1, user_answer="A")],
    )
    assert result.objective_correct == 1
    assert result.items[0].correct_answer == "A"
    newer = await load_guest_questions(database, 1)
    assert newer.questions[0].question_version_id == 11
    assert not database.new and not database.dirty
    assert len((await database.execute(select(Question))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_empty_and_inactive_latest_revision_are_not_previewable(database):
    with pytest.raises(GuestSubjectUnavailableError):
        await load_guest_questions(database, 1)
    await add_question(database, 1)
    database.add(QuestionVersion(
        id=11, question_id=1, version=2, subject_id=1, question_type="single_choice",
        content={"text": "撤下版本"}, answer="A", difficulty=3, is_active=False,
    ))
    await database.commit()
    with pytest.raises(GuestSubjectUnavailableError):
        await load_guest_questions(database, 1)


@pytest.mark.asyncio
async def test_subject_tree_keeps_eligible_leaf_and_ancestors_only(database, monkeypatch):
    await add_question(database, 1)
    monkeypatch.setattr(guest_practice, "get_practice_subject_tree", AsyncMock(return_value=[
        {"subject_id": 10, "children": [
            {"subject_id": 1, "children": []},
            {"subject_id": 2, "children": []},
        ]},
    ]))
    tree = await load_guest_subject_tree(database)
    assert len(tree) == 1
    assert [node["subject_id"] for node in tree[0]["children"]] == [1]
    assert tree[0]["children"][0]["trial_question_count"] == 1
