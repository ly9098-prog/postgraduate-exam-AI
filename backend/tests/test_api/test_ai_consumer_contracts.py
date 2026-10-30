"""Five current AI contracts with isolated SQLite and synthetic model ports."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.ai.prewarm_revision import build_prewarm_revision
from app.api.v1.ai import router
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.admin import QuestionVersion, Subject
from app.models.ai_feedback_log import AiFeedbackLog
from app.models.exam import ExamAttempt, ExamPaper, ExamPaperQuestion
from app.models.practice_record import PracticeRecord
from app.models.question import Question
from app.models.user import User
from app.models.wrong_question import WrongQuestion
from app.services import ai_prewarm_worker, ai_service, ai_teacher_408_service
from tests.test_services.test_exam_attempt_semantics import _make_database

ANALYSIS = {
    "mistake_diagnosis": "diagnosis",
    "knowledge_patch": "knowledge",
    "review_task": "review",
    "_meta": {"generated_at": "2026-10-30T00:00:00+00:00"},
}


async def _seed(factory):
    async with factory() as db:
        db.add_all(
            [
                User(id=1, openid="ai-consumer-1"),
                User(id=2, openid="ai-consumer-2"),
                Subject(id=1, code="exam408", name="408", level=0, path="1"),
                Subject(
                    id=2,
                    code="operating_system",
                    name="OS",
                    parent_id=1,
                    level=1,
                    path="1/2",
                ),
                Question(
                    id=1,
                    subject_id=2,
                    question_type="single_choice",
                    content={"text": "current stem"},
                    options={"A": "one", "B": "two"},
                    answer="B",
                    current_version_id=3,
                ),
                ExamPaper(
                    id=1,
                    title="AI guard",
                    paper_type="past_exam_choice",
                    duration_sec=600,
                    version=1,
                    status="published",
                    is_active=True,
                ),
            ]
        )
        for version_id, version, answer in [(1, 1, "A"), (3, 2, "B")]:
            db.add(
                QuestionVersion(
                    id=version_id,
                    question_id=1,
                    version=version,
                    subject_id=2,
                    question_type="single_choice",
                    content={"text": "server frozen stem"},
                    options={"A": "one", "B": "two"},
                    answer=answer,
                    analysis="frozen explanation",
                    difficulty=3,
                    is_active=True,
                )
            )
        await db.flush()
        db.add_all(
            [
                WrongQuestion(
                    id=1,
                    user_id=1,
                    question_id=1,
                    question_version_id=1,
                    wrong_answer="B",
                    review_count=2,
                    ai_analysis=ANALYSIS,
                ),
                WrongQuestion(
                    id=2,
                    user_id=2,
                    question_id=1,
                    question_version_id=1,
                    wrong_answer="B",
                ),
                ExamPaperQuestion(
                    id=1,
                    paper_id=1,
                    question_id=1,
                    question_version_id=1,
                    position=1,
                    score=2,
                    section_subject_id=2,
                ),
                PracticeRecord(
                    user_id=2,
                    question_id=1,
                    question_version_id=1,
                    subject_id=2,
                    user_answer="B",
                    is_correct=False,
                ),
            ]
        )
        await db.commit()


@pytest_asyncio.fixture
async def ai_client(tmp_path, monkeypatch):
    engine, factory = await _make_database(tmp_path)
    try:
        await _seed(factory)
        app = FastAPI()
        app.include_router(router)

        async def database():
            async with factory() as db:
                yield db

        app.dependency_overrides[get_db] = database
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1)
        provider = AsyncMock(
            side_effect=AssertionError("external provider is forbidden")
        )
        monkeypatch.setattr(ai_teacher_408_service, "chat_with_db_model", provider)
        analyze = AsyncMock(
            side_effect=AssertionError("unexpected analysis generation")
        )
        enqueue = AsyncMock(side_effect=AssertionError("unexpected queue submission"))
        monkeypatch.setattr(ai_service, "analyze_error", analyze)
        monkeypatch.setattr(ai_prewarm_worker, "enqueue_prewarm", enqueue)
        quota = AsyncMock(return_value=False)
        monkeypatch.setattr(ai_teacher_408_service, "check_token_limit", quota)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield SimpleNamespace(
                client=client, factory=factory, provider=provider, quota=quota
            )
        provider.assert_not_awaited()
        analyze.assert_not_awaited()
        enqueue.assert_not_awaited()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_teacher_fixed_version_requires_owned_history(ai_client):
    state = ai_client
    payload = {"question_id": 1, "question_version_id": 1, "action": "explain_correct"}
    refused = await state.client.post("/api/v1/ai/408-teacher", json=payload)
    assert refused.status_code == 400 and "不属于当前用户" in refused.json()["detail"]
    state.quota.assert_not_awaited()
    async with state.factory() as db:
        db.add(
            PracticeRecord(
                user_id=1,
                question_id=1,
                question_version_id=1,
                subject_id=2,
                user_answer="B",
                is_correct=False,
                question_type="single_choice",
            )
        )
        await db.commit()
    accepted = await state.client.post("/api/v1/ai/408-teacher", json=payload)
    assert accepted.status_code == 200
    body = accepted.json()
    assert body["question_version_id"] == 1 and body["question_id"] == 1
    assert body["from_fallback"] is True and body["tokens_used"] == 0
    assert body["summary"] == "frozen explanation"
    assert body["sections"] == [] and body["practice_question"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["teacher", "generate", "status", "recover"])
async def test_active_exam_blocks_all_answer_bearing_ai_routes(ai_client, endpoint):
    state = ai_client
    async with state.factory() as db:
        db.add(
            ExamAttempt(
                paper_id=1,
                paper_version=1,
                user_id=1,
                status="in_progress",
                request_id="ai-block",
                duration_sec=600,
            )
        )
        await db.commit()
    if endpoint == "teacher":
        response = await state.client.post(
            "/api/v1/ai/408-teacher", json={"question_id": 1, "action": "core_concept"}
        )
    elif endpoint == "status":
        response = await state.client.get("/api/v1/ai/error-analysis/status/1")
    else:
        suffix = "/recover" if endpoint == "recover" else ""
        response = await state.client.post(
            f"/api/v1/ai/error-analysis{suffix}", json={"wrong_question_id": 1}
        )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "exam_in_progress_ai_blocked"
    state.quota.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["generate", "status", "recover"])
async def test_wrong_ai_routes_reject_other_users_rows(ai_client, endpoint):
    client = ai_client.client
    if endpoint == "status":
        response = await client.get("/api/v1/ai/error-analysis/status/2")
    else:
        suffix = "/recover" if endpoint == "recover" else ""
        response = await client.post(
            f"/api/v1/ai/error-analysis{suffix}", json={"wrong_question_id": 2}
        )
    assert response.status_code == 404
    assert response.json()["detail"] == "错题记录不存在"


@pytest.mark.asyncio
async def test_analysis_status_recovery_generation_and_feedback(ai_client, monkeypatch):
    state = ai_client
    generated = {
        "content": {k: v for k, v in ANALYSIS.items() if k != "_meta"},
        "tokens_used": 7,
        "model": "synthetic",
        "duration_ms": 3,
    }
    analyze = AsyncMock(return_value=generated)
    enqueue = AsyncMock(return_value=True)
    monkeypatch.setattr(ai_service, "analyze_error", analyze)
    monkeypatch.setattr(ai_prewarm_worker, "enqueue_prewarm", enqueue)
    status = await state.client.get("/api/v1/ai/error-analysis/status/1")
    assert status.status_code == 200 and status.json()["ready"] is True
    assert status.json()["generated_at"] == ANALYSIS["_meta"]["generated_at"]
    assert status.json()["content"]["mistake_diagnosis"] == "diagnosis"
    recover = await state.client.post(
        "/api/v1/ai/error-analysis/recover",
        json={"wrong_question_id": 1, "force_regenerate": True},
    )
    assert recover.status_code == 200 and recover.json() == {"queued": True}
    args = enqueue.await_args
    assert args.args == (1, 1)
    assert args.kwargs["recovery_mode"] is True
    assert args.kwargs["revision"] == build_prewarm_revision(
        review_count=2, wrong_answer="B"
    )
    assert args.kwargs["force_regenerate"] is True
    assert args.kwargs["baseline_generated_at"] == ANALYSIS["_meta"]["generated_at"]
    assert args.kwargs["max_retries_override"] == 6
    assert args.kwargs["task_id_override"].startswith("prewarm-recovery:1:")
    response = await state.client.post(
        "/api/v1/ai/error-analysis",
        json={"wrong_question_id": 1, "force_regenerate": True},
    )
    assert response.status_code == 200
    assert response.json()["session_type"] == "error_analysis"
    assert response.json()["model"] == "synthetic"
    assert analyze.await_args.args[1:] == (1, 1)
    assert analyze.await_args.kwargs == {"force_regenerate": True}
    feedback = await state.client.post(
        "/api/v1/ai/feedback",
        json={
            "source": "wrong_book",
            "feedback_type": "inaccurate",
            "question_id": 1,
            "detail": "test",
        },
    )
    assert feedback.status_code == 200
    async with state.factory() as db:
        row = await db.scalar(select(AiFeedbackLog))
        assert (row.user_id, row.question_id, row.detail) == (1, 1, "test")


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["free_prompt", ""])
async def test_teacher_schema_rejects_free_actions(ai_client, action):
    response = await ai_client.client.post(
        "/api/v1/ai/408-teacher", json={"question_id": 1, "action": action}
    )
    assert response.status_code == 422
    ai_client.quota.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("force", "baseline", "expected"),
    [(False, "client-old", None), (True, "client-old", "client-old"), (True, "", "")],
)
async def test_recovery_preserves_explicit_marker_and_force_policy(
    ai_client, monkeypatch, force, baseline, expected
):
    enqueue = AsyncMock(return_value=False)
    monkeypatch.setattr(ai_prewarm_worker, "enqueue_prewarm", enqueue)
    response = await ai_client.client.post(
        "/api/v1/ai/error-analysis/recover",
        json={
            "wrong_question_id": 1,
            "force_regenerate": force,
            "baseline_generated_at": baseline,
        },
    )
    assert response.status_code == 200 and response.json() == {"queued": False}
    assert enqueue.await_args.kwargs["force_regenerate"] is force
    assert enqueue.await_args.kwargs["baseline_generated_at"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("analysis", [None, {}])
async def test_status_without_persisted_analysis_stays_not_ready(ai_client, analysis):
    async with ai_client.factory() as db:
        row = await db.get(WrongQuestion, 1)
        row.ai_analysis = analysis
        await db.commit()
    response = await ai_client.client.get("/api/v1/ai/error-analysis/status/1")
    assert response.status_code == 200
    assert response.json() == {
        "ready": False,
        "content": None,
        "generated_at": None,
    }
