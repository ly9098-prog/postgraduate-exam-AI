"""Final guards, immutable responses and request transaction ordering."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException, Response
from pydantic import ValidationError

from app.api.v1 import practice as route
from app.services import recommendation_log_service
from app.services.practice import (
    batch_issuance,
    final_candidates,
    issued_response,
    question_issuance,
    request_observability,
)
from app.services.practice.candidate_selection import (
    PracticeCandidateRequest,
    PracticeCandidates,
)


@pytest.fixture
def request_data():
    return PracticeCandidateRequest(
        user_id=7,
        subject_id=2,
        subject_code="ds",
        subject_ids=[2],
        count=2,
        mode="sequential",
        knowledge_points=None,
        knowledge_point_ids=None,
        include_descendants=False,
        exclude_answered=False,
        no_repeat_days=None,
        use_leitner=False,
        source_question_id=None,
        targeted_question_ids=[],
        start_request_id="retry",
        smart_strategy="scored",
    )


def question(qid, subject=2):
    return SimpleNamespace(id=qid, subject_id=subject, content={"text": "mutable"})


def revision(qid):
    return SimpleNamespace(
        question_id=qid,
        question_version_id=qid + 100,
        version=3,
        subject_id=2,
        subject_ref=SimpleNamespace(code="ds", name="数据结构"),
        question_type="single_choice",
        content={"text": "immutable"},
        options={"A": "one"},
        difficulty=2,
        image_url=None,
        answer="secret",
        analysis="secret analysis",
    )


@pytest.fixture
def pipeline(monkeypatch):
    events = []
    rows = [question(1), question(2)]
    revisions = {101: revision(1), 102: revision(2)}

    def step(name, result):
        async def run(*args, **kwargs):
            events.append(name)
            return result(*args, **kwargs) if callable(result) else result

        return AsyncMock(side_effect=run)

    latest = step("latest", {1: 101, 2: 102})
    guard = step("guard", lambda db, qs, scope, revision_ids: qs)
    views = step("views", revisions)
    kps = step("kps", {101: ["immutable kp"]})
    knowledge = step("knowledge", None)
    monkeypatch.setattr(route.svc, "load_latest_question_revision_ids", latest)
    monkeypatch.setattr(route.svc, "filter_questions_to_revision_scope", guard)
    monkeypatch.setattr(issued_response, "load_revision_views", views)
    monkeypatch.setattr(issued_response, "load_revision_kp_names", kps)
    monkeypatch.setattr(batch_issuance, "build_issue_knowledge_context", knowledge)
    monkeypatch.setattr(
        "app.services.practice.knowledge_session_summary.build_issue_knowledge_context",
        knowledge,
    )
    monkeypatch.setattr(
        route.svc,
        "resolve_subject_id_to_code",
        AsyncMock(return_value=("ds", "数据结构")),
    )
    monkeypatch.setattr(
        route.svc,
        "resolve_practice_subject_scope",
        AsyncMock(return_value=(False, [2])),
    )
    monkeypatch.setattr(
        route.svc, "get_sequential_practice_questions", step("select", (rows, None))
    )
    monkeypatch.setattr(route.svc, "get_practice_questions", step("select", rows))

    def sign(**kwargs):
        events.append("sign")
        return (
            "signed-token",
            {int(q.id): int(q.id) + 100 for q in kwargs["questions"]},
            "submit-id",
        )

    signer = Mock(side_effect=sign)
    monkeypatch.setattr(route.svc, "create_practice_batch_token", signer)
    monkeypatch.setattr(
        request_observability, "debug_log", Mock(side_effect=lambda *a: events.append("debug"))
    )
    monkeypatch.setattr(
        request_observability,
        "save_debug_snapshot",
        Mock(side_effect=lambda *a: events.append("snapshot")),
    )
    retain = step("retain", None)
    monkeypatch.setattr(
        recommendation_log_service, "retain_recommendation_logs_for_questions", retain
    )
    db = SimpleNamespace(execute=step("cleanup", None), commit=step("commit", None))
    return SimpleNamespace(
        rows=rows,
        revisions=revisions,
        events=events,
        latest=latest,
        guard=guard,
        views=views,
        kps=kps,
        knowledge=knowledge,
        signer=signer,
        db=db,
        retain=retain,
    )


async def call_route(pipeline, **overrides):
    kwargs = dict(
        response=Response(),
        subject_id=2,
        include_children=False,
        count=2,
        mode="sequential",
        knowledge_point=None,
        knowledge_point_id=None,
        include_descendants=False,
        exclude_answered=False,
        no_repeat_days=None,
        use_leitner=False,
        source_question_id=None,
        question_ids=None,
        start_request_id="retry",
        smart_strategy="scored",
        plan_token=None,
        x_trace_id="test",
        db=pipeline.db,
        current_user=SimpleNamespace(id=7),
    )
    kwargs.update(overrides)
    return await route.get_practice_questions(**kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["random", "sequential"])
async def test_commit_follows_complete_immutable_response(pipeline, mode):
    response = await call_route(pipeline, mode=mode)
    assert [q.content for q in response.questions] == [
        {"text": "immutable", "stem": "immutable"}
    ] * 2
    assert response.questions[0].knowledge_points == ["immutable kp"]
    assert "secret" not in response.model_dump_json()
    expected = [
        "select",
        "latest",
        "guard",
        "knowledge",
        "sign",
        "views",
        "kps",
        "debug",
        "snapshot",
    ]
    if mode == "sequential":
        expected += ["cleanup", "commit"]
        statement = pipeline.db.execute.call_args.args[0].compile()
        assert statement.params["user_id_1"] == 7
        assert statement.params["subject_id_1"] == 2
        assert statement.params["start_request_id_1"] == "retry"
        assert set(statement.params["question_id_1"]) == {1, 2}
    else:
        pipeline.db.execute.assert_not_awaited()
        pipeline.db.commit.assert_not_awaited()
    assert pipeline.events == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        "latest",
        "guard",
        "knowledge",
        "sign",
        "views",
        "kps",
        "debug",
        "snapshot",
        "cleanup",
        "commit",
    ],
)
async def test_failure_never_commits_early(pipeline, failure):
    target = {
        "latest": pipeline.latest,
        "guard": pipeline.guard,
        "knowledge": pipeline.knowledge,
        "sign": pipeline.signer,
        "views": pipeline.views,
        "kps": pipeline.kps,
        "debug": request_observability.debug_log,
        "snapshot": request_observability.save_debug_snapshot,
        "cleanup": pipeline.db.execute,
        "commit": pipeline.db.commit,
    }[failure]
    target.side_effect = RuntimeError(failure)
    with pytest.raises(RuntimeError, match=failure):
        await call_route(pipeline)
    if failure != "commit":
        pipeline.db.commit.assert_not_awaited()
    if failure not in {"cleanup", "commit"}:
        pipeline.db.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["missing", "wrong_question", "invalid_schema"])
async def test_revision_failure_stops_reservation_commit(pipeline, kind):
    if kind == "missing":
        pipeline.revisions.pop(102)
    elif kind == "wrong_question":
        pipeline.revisions[102].question_id = 99
    else:
        pipeline.revisions[102].difficulty = "not-a-number"
    with pytest.raises(
        ValidationError if kind == "invalid_schema" else HTTPException
    ) as caught:
        await call_route(pipeline)
    if kind != "invalid_schema":
        assert caught.value.status_code == 500
        assert caught.value.detail == "题目版本数据不完整，请稍后重试"
    pipeline.db.execute.assert_not_awaited()
    pipeline.db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_targeted_shrink_rejects_before_signing(monkeypatch, pipeline):
    pipeline.guard.side_effect = lambda db, qs, scope, revision_ids: qs[:1]
    monkeypatch.setattr(
        route.svc,
        "get_targeted_practice_questions",
        AsyncMock(return_value=pipeline.rows),
    )
    with pytest.raises(HTTPException) as caught:
        await call_route(pipeline, mode="random", question_ids="1,2")
    assert caught.value.status_code == 409
    assert caught.value.detail.endswith("[2]")
    pipeline.signer.assert_not_called()
    pipeline.db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_final_guard_deduplicates_and_retains_only_exposures(
    request_data, pipeline
):
    rows = [question(1), question(1), question(8, 9), question(2), question(3)]
    result = await final_candidates.prepare_final_candidates(
        pipeline.db,
        request_data,
        rows,
        mode="smart",
        metadata={1: {"strategy": "smart"}, 8: {}, "2": {}},
        request_id="rec",
    )
    assert [q.id for q in result.questions] == [1, 2]
    assert set(result.metadata) == {1, "2"}
    assert result.revision_ids == {1: 101, 2: 102}
    pipeline.retain.assert_awaited_once_with(
        pipeline.db, user_id=7, request_id="rec", question_ids={1, 2}
    )
    assert pipeline.events == ["latest", "guard", "retain"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,request_id,expected",
    [
        ("random", "rec", 0),
        ("smart", None, 0),
        ("smart", "rec", 1),
        ("similar", "rec", 1),
    ],
)
async def test_exposure_alignment_is_best_effort(
    request_data, pipeline, mode, request_id, expected
):
    pipeline.retain.side_effect = RuntimeError("logging unavailable")
    result = await final_candidates.prepare_final_candidates(
        pipeline.db,
        request_data,
        [],
        mode=mode,
        metadata={},
        request_id=request_id,
    )
    assert result.questions == []
    assert pipeline.retain.await_count == expected
    pipeline.db.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", [None, {"plan_id": "today"}])
async def test_plan_attribution_uses_actual_request(monkeypatch, pipeline, entry):
    validate = Mock(return_value=entry)
    monkeypatch.setattr(batch_issuance, "validate_plan_task_token", validate)
    monkeypatch.setattr(
        "app.services.study_hub_plan_token.validate_plan_task_token", validate
    )
    response = await call_route(pipeline, plan_token="plan")
    assert response.total == 2
    validate.assert_called_once_with(
        "plan",
        user_id=7,
        subject_id=2,
        mode="sequential",
        count=2,
        knowledge_point_id=None,
        include_descendants=False,
        question_ids=None,
    )
    assert pipeline.signer.call_args.kwargs["entry_context"] == entry


def test_submission_id_is_canonical_and_scope_bound():
    make = batch_issuance.sequential_submission_request_id
    assert make("retry", 2, {"a": 1, "b": "树"}) == make(
        "retry", 2, {"b": "树", "a": 1}
    )
    assert make("retry", 2, {}) != make("retry", 3, {})
    assert make("retry", 2, {}) != make("retry", 2, {"a": 1})
    assert make("retry", 2, {}) != make("other", 2, {})


@pytest.mark.asyncio
async def test_cleanup_uses_final_signed_set(pipeline):
    pipeline.guard.side_effect = lambda db, qs, scope, revision_ids: qs[:1]
    response = await call_route(pipeline)
    assert response.total == 1
    assert set(
        pipeline.db.execute.call_args.args[0].compile().params["question_id_1"]
    ) == {1}
    assert [q.id for q in pipeline.signer.call_args.kwargs["questions"]] == [1]
    pipeline.db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_empty_sequential_batch_releases_all_unused_claims(pipeline):
    pipeline.guard.side_effect = lambda *args, **kwargs: []
    response = await call_route(pipeline)
    assert response.total == 0
    assert not pipeline.db.execute.call_args.args[0].compile().params["question_id_1"]
    assert pipeline.events[-4:] == ["debug", "snapshot", "cleanup", "commit"]


@pytest.mark.asyncio
async def test_scope_logging_failure_precedes_signing_and_commit(pipeline, monkeypatch):
    monkeypatch.setattr(
        question_issuance, "log_practice_scope", Mock(side_effect=RuntimeError("scope log")),
    )
    with pytest.raises(RuntimeError, match="scope log"):
        await call_route(pipeline)
    pipeline.signer.assert_not_called()
    pipeline.db.execute.assert_not_awaited()
    pipeline.db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_similar_fallback_uses_effective_mode_without_commit(pipeline):
    response = await call_route(pipeline, mode="similar", source_question_id=None)
    assert response.mode == "random"
    assert pipeline.signer.call_args.kwargs["mode"] == "random"
    pipeline.db.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("chapter", [False, True])
async def test_signed_context_and_public_scope_stay_aligned(
    request_data, pipeline, chapter
):
    scope = {
        "root_id": 9,
        "root_name": "树",
        "include_descendants": chapter,
        "knowledge_point_ids": [9, 10] if chapter else [9],
        "syllabus_version_id": 3,
    }
    baseline = {"baseline": {"9": 0.2}}
    pipeline.knowledge.side_effect = None
    pipeline.knowledge.return_value = baseline
    candidates = PracticeCandidates(
        pipeline.rows, "sequential", reservation_request_id="retry"
    )
    final = final_candidates.FinalPracticeCandidates(
        pipeline.rows, {1: 101, 2: 102}, {}
    )
    context = batch_issuance.PracticeIssueContext("trace", scope, 9, None, None)
    response = await batch_issuance.build_signed_practice_response(
        pipeline.db,
        request_data,
        candidates,
        final,
        context,
    )
    pipeline.knowledge.assert_awaited_once_with(
        pipeline.db,
        user_id=7,
        knowledge_scope=scope,
        questions=pipeline.rows,
        revision_ids=final.revision_ids,
        practice_subject_id=2,
    )
    assert pipeline.signer.call_args.kwargs["knowledge_context"] is baseline
    assert pipeline.signer.call_args.kwargs["submission_request_id"] == (
        batch_issuance.sequential_submission_request_id(
            "retry", 2, {"knowledge_scope": scope}
        )
    )
    assert response.knowledge_scope.root_knowledge_point_id == 9
    assert response.knowledge_scope.knowledge_point_count == len(
        scope["knowledge_point_ids"]
    )
    assert "baseline" not in response.model_dump_json()
    pipeline.db.commit.assert_not_awaited()
