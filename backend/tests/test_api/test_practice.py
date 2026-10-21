"""API 集成测试：刷题接口（父级科目聚合刷题与均衡抽题）。

使用 FastAPI TestClient 覆盖 API 路由层。
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import practice as practice_router
from app.core.database import get_db
from app.core.security import get_current_user
from app.main import app
from app.models.question import Question
from app.services.practice import issued_response


@pytest.fixture
def issue_question(monkeypatch):
    """Supply immutable revision reads without bypassing real batch signing."""
    revisions = {}

    def make(*args, **kwargs):
        question = _make_question(*args, **kwargs)
        revision_id = question.id + 100
        revisions[revision_id] = SimpleNamespace(
            question_id=question.id,
            question_version_id=revision_id,
            version=1,
            subject_id=question.subject_id,
            subject_ref=question.subject_ref,
            question_type=question.question_type,
            content={"text": "不可变版本题干"},
            options=question.options,
            difficulty=question.difficulty,
            image_url=None,
        )
        return question

    monkeypatch.setattr(
        practice_router.svc,
        "load_latest_question_revision_ids",
        AsyncMock(side_effect=lambda db, ids: {qid: qid + 100 for qid in ids}),
    )
    monkeypatch.setattr(
        practice_router.svc,
        "filter_questions_to_revision_scope",
        AsyncMock(side_effect=lambda db, qs, scope, revision_ids: qs),
    )
    monkeypatch.setattr(
        practice_router.svc,
        "get_practice_questions",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        issued_response,
        "load_revision_views",
        AsyncMock(side_effect=lambda db, ids: {rid: revisions[rid] for rid in ids}),
    )
    monkeypatch.setattr(
        issued_response, "load_revision_kp_names", AsyncMock(return_value={})
    )
    monkeypatch.setattr(
        "app.services.question_review_service.get_due_question_ids",
        AsyncMock(side_effect=lambda db, uid, ids: set(ids)),
    )
    monkeypatch.setattr(
        "app.services.recommendation_log_service.retain_recommendation_logs_for_questions",
        AsyncMock(),
    )
    return make


client = TestClient(app)


@pytest.mark.parametrize(
    "filters",
    [
        {"knowledge_point": "导数", "knowledge_point_id": 4},
        {"include_descendants": True},
        {"knowledge_point_id": 4, "include_descendants": True, "mode": "smart"},
        {"question_ids": "1,1"},
        {"question_ids": "0"},
        {"question_ids": "invalid"},
        {"question_ids": "1", "mode": "smart"},
        {"question_ids": "1", "source_question_id": 2},
    ],
)
def test_invalid_request_filters_fail_before_candidate_query(
    monkeypatch, issue_question, filters
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
    _setup_deps({})
    try:
        response = client.get(
            "/api/v1/practice/questions",
            params={"subject_id": 2, "mode": "random", **filters},
        )
    finally:
        _cleanup_deps()
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "HTTP_400"
    practice_router.svc.get_practice_questions.assert_not_awaited()


class _MockDB:
    """模拟 DB session。"""

    def __init__(self):
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.refresh = AsyncMock()
        self.flush = AsyncMock()
        self.add = MagicMock()
        self.execute = AsyncMock()
        self.get = AsyncMock()


async def _override_db():
    yield _MockDB()


def _mock_user(user_id=1):
    user = MagicMock()
    user.id = user_id
    return user


async def _override_user():
    return _mock_user()


def _make_question(id_val, subject_id, subject_code="ds", subject_name="数据结构"):
    q = MagicMock(spec=Question)
    q.id = id_val
    q.subject_id = subject_id
    q.question_type = "single_choice"
    q.content = {"stem": "测试题干"}
    q.options = {"A": "选项A", "B": "选项B", "C": "选项C", "D": "选项D"}
    q.difficulty = 2
    q.subject_ref = MagicMock()
    q.subject_ref.code = subject_code
    q.subject_ref.name = subject_name
    return q


# ── 通用工具 ──


def _setup_deps(overrides: dict):
    """设置依赖覆盖，返回 cleanup 函数。"""
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    for key, value in overrides.items():
        app.dependency_overrides[key] = value


def _cleanup_deps():
    app.dependency_overrides.clear()


# ── 1. 父级科目 + sequential → 400 ──


class TestSequentialModeRestriction:
    """顺序练习模式限制测试。"""

    def test_parent_sequential_include_children_true_returns_400(
        self, monkeypatch, issue_question
    ):
        """父级 + sequential + include_children=true → 400。"""
        monkeypatch.setattr(
            practice_router.svc,
            "resolve_subject_id_to_code",
            AsyncMock(return_value=("cs", "计算机")),
        )
        monkeypatch.setattr(
            practice_router.svc,
            "resolve_practice_subject_scope",
            AsyncMock(return_value=(True, [1, 2, 3, 4, 5])),
        )

        _setup_deps({})
        try:
            resp = client.get(
                "/api/v1/practice/questions",
                params={
                    "subject_id": 1,
                    "include_children": True,
                    "mode": "sequential",
                    "count": 5,
                },
            )
        finally:
            _cleanup_deps()

        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "HTTP_400"

    def test_parent_sequential_include_children_false_returns_400(
        self, monkeypatch, issue_question
    ):
        """父级 + sequential + include_children=false → 400。"""
        monkeypatch.setattr(
            practice_router.svc,
            "resolve_subject_id_to_code",
            AsyncMock(return_value=("cs", "计算机")),
        )
        monkeypatch.setattr(
            practice_router.svc,
            "resolve_practice_subject_scope",
            AsyncMock(return_value=(True, [1])),  # has children but scope is self
        )

        _setup_deps({})
        try:
            resp = client.get(
                "/api/v1/practice/questions",
                params={
                    "subject_id": 1,
                    "include_children": False,
                    "mode": "sequential",
                    "count": 5,
                },
            )
        finally:
            _cleanup_deps()

        assert resp.status_code == 400

    def test_leaf_sequential_returns_200(self, monkeypatch, issue_question):
        """叶子科目 + sequential → 正常返回 200。"""
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
        monkeypatch.setattr(
            practice_router.svc,
            "get_sequential_practice_questions",
            AsyncMock(return_value=([issue_question(1, 2, "ds", "数据结构")], None)),
        )

        _setup_deps({})
        try:
            resp = client.get(
                "/api/v1/practice/questions",
                params={
                    "subject_id": 2,
                    "include_children": False,
                    "mode": "sequential",
                    "count": 5,
                },
            )
        finally:
            _cleanup_deps()

        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "sequential"
        assert len(data["questions"]) == 1


# ── 2. 作用域语义测试 ──


class TestIncludeChildrenScope:
    """include_children 参数语义测试。"""

    def test_include_children_false_exact_only(self, monkeypatch, issue_question):
        """父级 + random + include_children=false → 只返回父级自身题目。"""
        monkeypatch.setattr(
            practice_router.svc,
            "resolve_subject_id_to_code",
            AsyncMock(return_value=("cs", "计算机")),
        )
        monkeypatch.setattr(
            practice_router.svc,
            "resolve_practice_subject_scope",
            AsyncMock(return_value=(True, [1])),
        )
        monkeypatch.setattr(
            practice_router.svc,
            "get_practice_questions",
            AsyncMock(return_value=[issue_question(10, 1, "cs", "计算机")]),
        )

        _setup_deps({})
        try:
            resp = client.get(
                "/api/v1/practice/questions",
                params={
                    "subject_id": 1,
                    "include_children": False,
                    "mode": "random",
                    "count": 5,
                },
            )
        finally:
            _cleanup_deps()

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["questions"]) == 1
        assert data["questions"][0]["subject_code"] == "cs"

    def test_include_children_true_includes_descendants(
        self, monkeypatch, issue_question
    ):
        """父级 + random + include_children=true → 包含后代题目。"""
        monkeypatch.setattr(
            practice_router.svc,
            "resolve_subject_id_to_code",
            AsyncMock(return_value=("cs", "计算机")),
        )
        mock_scope_ids = [1, 2, 3, 4, 5]
        monkeypatch.setattr(
            practice_router.svc,
            "resolve_practice_subject_scope",
            AsyncMock(return_value=(True, mock_scope_ids)),
        )
        questions = [
            issue_question(1, 2, "ds", "数据结构"),
            issue_question(2, 3, "co", "组成原理"),
        ]
        monkeypatch.setattr(
            practice_router.svc,
            "get_aggregated_random_questions",
            AsyncMock(return_value=questions),
        )

        _setup_deps({})
        try:
            resp = client.get(
                "/api/v1/practice/questions",
                params={
                    "subject_id": 1,
                    "include_children": True,
                    "mode": "random",
                    "count": 5,
                },
            )
        finally:
            _cleanup_deps()

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["questions"]) == 2
        codes = {q["subject_code"] for q in data["questions"]}
        assert "ds" in codes
        assert "co" in codes


# ── 3. Smart 模式和 metadata 兼容性 ──


class TestSmartModeMetadata:
    """Smart 模式 API 响应和 metadata 兼容性测试。"""

    def test_smart_single_subject_metadata_in_response(
        self, monkeypatch, issue_question
    ):
        """smart 模式返回字段完整，metadata 不丢失。"""
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

        question = issue_question(1, 2, "ds", "数据结构")
        monkeypatch.setattr(
            practice_router.svc,
            "get_smart_practice_questions",
            AsyncMock(
                return_value=(
                    [question],
                    {
                        1: {
                            "recommend_reason": "薄弱知识点推荐",
                            "recommend_score": 0.85,
                            "strategy": "smart_vector",
                            "similarity": 0.75,
                        }
                    },
                )
            ),
        )

        _setup_deps({})
        try:
            resp = client.get(
                "/api/v1/practice/questions",
                params={
                    "subject_id": 2,
                    "include_children": False,
                    "mode": "smart",
                    "count": 5,
                },
            )
        finally:
            _cleanup_deps()

        assert resp.status_code == 200
        data = resp.json()
        q = data["questions"][0]
        assert q["recommend_reason"] == "薄弱知识点推荐"
        assert q["recommend_score"] == 0.85
        assert q["strategy"] == "smart_vector"
        assert q["similarity"] == 0.75
        assert data["trace_id"] is not None

    def test_smart_aggregation_scope_routes_correctly(
        self, monkeypatch, issue_question
    ):
        """聚合 smart 路由到 get_aggregated_smart_questions。"""
        monkeypatch.setattr(
            practice_router.svc,
            "resolve_subject_id_to_code",
            AsyncMock(return_value=("cs", "计算机")),
        )
        monkeypatch.setattr(
            practice_router.svc,
            "resolve_practice_subject_scope",
            AsyncMock(return_value=(True, [1, 2])),
        )
        monkeypatch.setattr(
            practice_router.svc,
            "get_aggregated_smart_questions",
            AsyncMock(
                return_value=(
                    [issue_question(1, 2, "ds", "数据结构")],
                    {1: {"recommend_reason": "聚合推荐"}},
                )
            ),
        )

        _setup_deps({})
        try:
            resp = client.get(
                "/api/v1/practice/questions",
                params={
                    "subject_id": 1,
                    "include_children": True,
                    "mode": "smart",
                    "count": 5,
                },
            )
        finally:
            _cleanup_deps()

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["questions"]) == 1
        assert data["questions"][0]["recommend_reason"] == "聚合推荐"


# ── 4. 参数透传验证 ──


class TestParameterPassthrough:
    """验证过滤参数完整透传到服务层。"""

    def test_exclude_answered_passed(self, monkeypatch, issue_question):
        """exclude_answered 被正确传递。"""
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

        mock_fn = AsyncMock(return_value=[])
        monkeypatch.setattr(
            practice_router.svc,
            "get_practice_questions",
            mock_fn,
        )

        _setup_deps({})
        try:
            client.get(
                "/api/v1/practice/questions",
                params={
                    "subject_id": 2,
                    "include_children": False,
                    "mode": "random",
                    "count": 5,
                    "exclude_answered": True,
                    "no_repeat_days": 3,
                    "use_leitner": True,
                },
            )
        finally:
            _cleanup_deps()

        _, kwargs = mock_fn.call_args
        assert kwargs.get("exclude_answered") is True
        assert kwargs.get("no_repeat_days") == 3
        assert kwargs.get("use_leitner") is True

    def test_knowledge_points_passed(self, monkeypatch, issue_question):
        """knowledge_point 被正确解析和传递。"""
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

        mock_fn = AsyncMock(return_value=[])
        monkeypatch.setattr(
            practice_router.svc,
            "get_practice_questions",
            mock_fn,
        )

        _setup_deps({})
        try:
            client.get(
                "/api/v1/practice/questions",
                params={
                    "subject_id": 2,
                    "include_children": False,
                    "mode": "random",
                    "count": 5,
                    "knowledge_point": "导数,极限",
                },
            )
        finally:
            _cleanup_deps()

        _, kwargs = mock_fn.call_args
        assert kwargs.get("knowledge_points") == ["导数", "极限"]

    def test_smart_strategy_passed(self, monkeypatch, issue_question):
        """smart_strategy 被正确传递。"""
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

        mock_fn = AsyncMock(return_value=([], {}))
        monkeypatch.setattr(
            practice_router.svc,
            "get_smart_practice_questions",
            mock_fn,
        )

        _setup_deps({})
        try:
            client.get(
                "/api/v1/practice/questions",
                params={
                    "subject_id": 2,
                    "include_children": False,
                    "mode": "smart",
                    "count": 5,
                    "smart_strategy": "scored",
                },
            )
        finally:
            _cleanup_deps()

        _, kwargs = mock_fn.call_args
        assert kwargs.get("smart_strategy") == "scored"


# ── 5. 响应兼容性 ──


class TestResponseCompatibility:
    """响应结构兼容性测试。"""

    def test_response_structure_unchanged(self, monkeypatch, issue_question):
        """响应字段结构不变。"""
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

        q = issue_question(1, 2, "ds", "数据结构")
        monkeypatch.setattr(
            practice_router.svc,
            "get_practice_questions",
            AsyncMock(return_value=[q]),
        )

        _setup_deps({})
        try:
            resp = client.get(
                "/api/v1/practice/questions",
                params={
                    "subject_id": 2,
                    "include_children": False,
                    "mode": "random",
                    "count": 5,
                },
            )
        finally:
            _cleanup_deps()

        assert resp.status_code == 200
        data = resp.json()
        # 顶层字段
        assert "questions" in data
        assert "total" in data
        assert "mode" in data
        assert "trace_id" in data
        # 题目字段
        q0 = data["questions"][0]
        assert "id" in q0
        assert "subject_id" in q0
        assert "subject_code" in q0
        assert "subject_name" in q0
        assert "question_type" in q0
        assert "content" in q0
        assert "options" in q0
        assert "knowledge_points" in q0
        assert "difficulty" in q0
        assert "trace_id" in q0
        assert q0["question_version_id"] == 101
        assert q0["content"]["text"] == "不可变版本题干"
        assert "answer" not in q0
        payload = practice_router.svc._decode_practice_batch_token(data["batch_token"])
        assert payload["questions"] == [[1, 101]]


class TestBatchSubmitErrorMapping:
    """The route must preserve the service-level submission error contract."""

    def _submit(self, monkeypatch, exc: Exception):
        monkeypatch.setattr(
            practice_router.svc,
            "batch_submit_answers",
            AsyncMock(side_effect=exc),
        )
        _setup_deps({})
        try:
            return client.post(
                "/api/v1/practice/batch-submit",
                json={
                    "batch_token": "signed-token-1234567890",
                    "answers": [
                        {
                            "question_id": 1,
                            "user_answer": "A",
                            "used_time": 1,
                        }
                    ],
                    "skipped_question_ids": [],
                    "session": {
                        "request_id": "request-1",
                        "subject_id": 2,
                        "mode": "sequential",
                        "started_at": "2026-10-21T00:00:00Z",
                        "finished_at": "2026-10-21T00:00:02Z",
                        "duration_sec": 2,
                        "question_count": 1,
                        "answered_count": 1,
                    },
                },
            )
        finally:
            _cleanup_deps()

    def test_invalid_batch_token_is_400(self, monkeypatch):
        response = self._submit(
            monkeypatch,
            practice_router.svc.PracticeBatchTokenError("invalid"),
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "PRACTICE_BATCH_INVALID"

    def test_submission_conflict_is_409(self, monkeypatch):
        response = self._submit(
            monkeypatch,
            practice_router.svc.PracticeSubmissionConflictError("conflict"),
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "PRACTICE_SUBMISSION_CONFLICT"

    def test_payload_value_error_is_400(self, monkeypatch):
        response = self._submit(monkeypatch, ValueError("invalid payload"))
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "PRACTICE_PAYLOAD_INVALID"
