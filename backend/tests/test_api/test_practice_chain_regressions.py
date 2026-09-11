"""Regression coverage for immutable practice-batch issuance guards."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, Response

from app.api.v1 import practice as practice_router


class _User:
    id = 7


class _DB:
    pass


def _question(question_id: int):
    question = SimpleNamespace(
        id=question_id,
        subject_id=2,
        question_type="single_choice",
        content={"stem": "stem"},
        options={"A": "A", "B": "B"},
        difficulty=2,
        subject_ref=SimpleNamespace(code="ds", name="数据结构"),
    )
    return question


def _revision(question_id: int, revision_id: int):
    return SimpleNamespace(
        question_id=question_id,
        question_version_id=revision_id,
        version=1,
        subject_id=2,
        subject_ref=SimpleNamespace(code="ds", name="数据结构"),
        question_type="single_choice",
        content={"text": "stem"},
        options={"A": "A", "B": "B"},
        difficulty=2,
        image_url=None,
        answer="A",
        analysis=None,
        is_active=True,
    )


def _patch_issue_pipeline(monkeypatch, question_ids, *, filter_fn=None):
    revisions = {qid: qid + 100 for qid in question_ids}
    monkeypatch.setattr(
        practice_router.svc,
        "load_latest_question_revision_ids",
        AsyncMock(return_value=revisions),
    )
    monkeypatch.setattr(
        practice_router.svc,
        "filter_questions_to_revision_scope",
        AsyncMock(
            side_effect=filter_fn
            or (lambda db, questions, scope, revision_ids=None: questions)
        ),
    )
    monkeypatch.setattr(
        practice_router,
        "load_revision_views",
        AsyncMock(return_value={rid: _revision(qid, rid) for qid, rid in revisions.items()}),
    )
    monkeypatch.setattr(
        practice_router,
        "load_revision_kp_names",
        AsyncMock(return_value={rid: [] for rid in revisions.values()}),
    )
    monkeypatch.setattr(
        practice_router.svc,
        "create_practice_batch_token",
        lambda **kwargs: ("signed-token", revisions, "submission-request"),
    )
    monkeypatch.setattr(
        "app.services.practice.knowledge_session_summary.build_issue_knowledge_context",
        AsyncMock(return_value=None),
    )


async def _call(
    monkeypatch,
    *,
    mode,
    count,
    questions,
    targeted=None,
    due=None,
    fallback=None,
    filter_fn=None,
):
    monkeypatch.setattr(
        practice_router.svc,
        "resolve_subject_id_to_code",
        AsyncMock(return_value=("ds", "数据结构")),
    )
    monkeypatch.setattr(
        practice_router.svc,
        "resolve_practice_subject_scope",
        AsyncMock(return_value=(False, [2])),
    )
    if targeted is not None:
        monkeypatch.setattr(
            practice_router.svc,
            "get_targeted_practice_questions",
            AsyncMock(return_value=questions),
        )
    else:
        monkeypatch.setattr(
            practice_router.svc,
            "get_smart_practice_questions",
            AsyncMock(return_value=(questions, {int(q.id): {"recommend_reason": "smart"} for q in questions})),
        )
        monkeypatch.setattr(
            "app.services.question_review_service.get_due_question_ids",
            AsyncMock(side_effect=[due or set(), due or set()]),
        )
        monkeypatch.setattr(
            practice_router.svc,
            "get_practice_questions",
            AsyncMock(return_value=fallback or []),
        )

    selected_ids = targeted or [int(q.id) for q in questions]
    _patch_issue_pipeline(
        monkeypatch,
        selected_ids if targeted is not None else [1, 3],
        filter_fn=filter_fn,
    )
    return await practice_router.get_practice_questions(
        response=Response(),
        subject_id=2,
        include_children=False,
        count=count,
        mode=mode,
        knowledge_point=None,
        knowledge_point_id=None,
        include_descendants=False,
        exclude_answered=False,
        no_repeat_days=None,
        use_leitner=targeted is None,
        source_question_id=None,
        question_ids=(",".join(str(qid) for qid in targeted) if targeted is not None else None),
        smart_strategy="scored",
        plan_token=None,
        x_trace_id=None,
        db=_DB(),
        current_user=_User(),
    )


@pytest.mark.asyncio
async def test_targeted_question_ids_are_not_truncated(monkeypatch):
    response = await _call(
        monkeypatch,
        mode="random",
        count=1,
        questions=[_question(11), _question(12), _question(13)],
        targeted=[11, 12, 13],
    )

    assert response.total == 3
    assert [question.id for question in response.questions] == [11, 12, 13]


@pytest.mark.asyncio
async def test_smart_leitner_guard_filters_and_fills(monkeypatch):
    response = await _call(
        monkeypatch,
        mode="smart",
        count=2,
        questions=[_question(1), _question(2)],
        due={1, 3},
        fallback=[_question(3)],
    )

    assert [question.id for question in response.questions] == [1, 3]


@pytest.mark.asyncio
async def test_targeted_batch_rejects_revision_scope_shrink(monkeypatch):
    def drop_last(_db, questions, _scope, revision_ids=None):
        return questions[:1]

    with pytest.raises(HTTPException) as exc_info:
        await _call(
            monkeypatch,
            mode="random",
            count=1,
            questions=[_question(11), _question(12)],
            targeted=[11, 12],
            filter_fn=drop_last,
        )

    assert exc_info.value.status_code == 409
