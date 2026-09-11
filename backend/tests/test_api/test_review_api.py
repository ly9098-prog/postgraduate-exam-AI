"""Current review grading API contract tests."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from app.api.v1 import review
from app.main import app
from app.models.user import User

client = TestClient(app)


def _override_auth_and_db():
    user = MagicMock(spec=User)
    user.id = 1
    db = MagicMock()
    app.dependency_overrides[review.get_current_user] = lambda: user
    app.dependency_overrides[review.get_db] = lambda: db
    return db


def _clear_overrides():
    app.dependency_overrides.clear()


def _review_item(**overrides):
    item = {
        "schedule_id": 7,
        "question_id": 11,
        "question_version_id": 23,
        "occurrence_seq": 2,
        "request_id": "review-request-123",
        "user_answer": "A",
    }
    item.update(overrides)
    return item


def _grade_result(**overrides):
    result = {
        **_review_item(),
        "success": True,
        "error": None,
        "error_code": None,
        "retryable": False,
        "refresh_required": False,
        "is_correct": True,
        "correct_answer": "A",
        "rating": 4,
        "interval_after": 6,
        "ease_factor_after": 2.5,
        "next_review_at": datetime.now(UTC),
        "mastery_percent": 65,
        "mastered": False,
    }
    result.update(overrides)
    return result


class TestGradeBatchAPI:
    def setup_method(self):
        self.db = _override_auth_and_db()

    def teardown_method(self):
        _clear_overrides()

    def test_success(self, monkeypatch):
        service = AsyncMock(return_value={
            "results": [_grade_result()],
            "total": 1,
            "correct_count": 1,
            "wrong_count": 0,
        })
        monkeypatch.setattr(review.review_scheduler, "grade_batch_review", service)
        response = client.post("/api/v1/review/grade-batch", json={"reviews": [_review_item()]})

        assert response.status_code == 200
        body = response.json()
        assert body["results"][0]["question_version_id"] == 23
        assert body["results"][0]["occurrence_seq"] == 2
        assert body["results"][0]["request_id"] == "review-request-123"
        service.assert_awaited_once()

    def test_rejects_missing_immutable_identity(self):
        item = _review_item()
        item.pop("question_version_id")
        item.pop("occurrence_seq")
        item.pop("request_id")
        response = client.post("/api/v1/review/grade-batch", json={"reviews": [item]})
        assert response.status_code == 422

    def test_rejects_empty_batch(self):
        response = client.post("/api/v1/review/grade-batch", json={"reviews": []})
        assert response.status_code == 422

    def test_service_value_error_returns_400(self, monkeypatch):
        monkeypatch.setattr(
            review.review_scheduler,
            "grade_batch_review",
            AsyncMock(side_effect=ValueError("复习题版本已更新，请刷新后重试")),
        )
        response = client.post("/api/v1/review/grade-batch", json={"reviews": [_review_item()]})
        assert response.status_code == 400
        assert response.json()["error"]["message"] == "请求参数有误，请检查后重试"
