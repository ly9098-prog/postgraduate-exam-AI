"""Review API 测试 — schedule-submit, batch-submit, grade-submit。

覆盖 3 个备用复习接口的完整链路。
"""
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from app.api.v1 import review
from app.main import app
from app.models.review_scheduler import ReviewSchedule
from app.models.user import User

client = TestClient(app)


# ── Fixtures ──


def _make_user(user_id=1):
    user = MagicMock(spec=User)
    user.id = user_id
    return user


def _make_schedule(schedule_id=1, user_id=1, question_id=1, interval=1, ease_factor=2.5, repetitions=0):
    schedule = MagicMock(spec=ReviewSchedule)
    schedule.id = schedule_id
    schedule.user_id = user_id
    schedule.question_id = question_id
    schedule.interval = interval
    schedule.ease_factor = ease_factor
    schedule.repetitions = repetitions
    schedule.next_review_at = datetime.now(UTC)
    schedule.last_reviewed_at = None
    schedule.mastered = False
    schedule.subject_id = 1
    return schedule


def _make_db_with_mocks():
    db = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _override_auth_and_db(user_id=1):
    user = _make_user(user_id)
    db = _make_db_with_mocks()

    app.dependency_overrides[review.get_current_user] = lambda: user
    app.dependency_overrides[review.get_db] = lambda: db

    return user, db


def _clear_overrides():
    app.dependency_overrides.clear()


# ── /review/schedule-submit ──


class TestScheduleSubmitAPI:
    def setup_method(self):
        self.user, self.db = _override_auth_and_db()

    def teardown_method(self):
        _clear_overrides()

    def test_schedule_submit_success(self, monkeypatch):
        """提交单题复习结果成功。"""
        _make_schedule()
        mock_result = {
            "schedule_id": 1,
            "question_id": 1,
            "rating": 4,
            "interval_after": 6,
            "ease_factor_after": 2.6,
            "next_review_at": datetime.now(UTC) + timedelta(days=6),
            "is_correct": True,
        }
        monkeypatch.setattr(review.review_scheduler, "submit_review", AsyncMock(return_value=mock_result))

        resp = client.post("/api/v1/review/schedule-submit", json={
            "schedule_id": 1,
            "question_id": 1,
            "rating": 4,
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["schedule_id"] == 1
        assert data["rating"] == 4
        assert data["interval_after"] == 6

    def test_schedule_submit_rating_0_valid(self, monkeypatch):
        """rating=0 合法。"""
        mock_result = {
            "schedule_id": 1,
            "question_id": 1,
            "rating": 0,
            "interval_after": 1,
            "ease_factor_after": 2.0,
            "next_review_at": datetime.now(UTC) + timedelta(days=1),
            "is_correct": False,
        }
        monkeypatch.setattr(review.review_scheduler, "submit_review", AsyncMock(return_value=mock_result))

        resp = client.post("/api/v1/review/schedule-submit", json={
            "schedule_id": 1,
            "question_id": 1,
            "rating": 0,
        })

        assert resp.status_code == 200
        assert resp.json()["rating"] == 0

    def test_schedule_submit_rating_5_valid(self, monkeypatch):
        """rating=5 合法。"""
        mock_result = {
            "schedule_id": 1,
            "question_id": 1,
            "rating": 5,
            "interval_after": 10,
            "ease_factor_after": 2.7,
            "next_review_at": datetime.now(UTC) + timedelta(days=10),
            "is_correct": True,
        }
        monkeypatch.setattr(review.review_scheduler, "submit_review", AsyncMock(return_value=mock_result))

        resp = client.post("/api/v1/review/schedule-submit", json={
            "schedule_id": 1,
            "question_id": 1,
            "rating": 5,
        })

        assert resp.status_code == 200
        assert resp.json()["rating"] == 5

    def test_schedule_submit_invalid_rating_too_high(self):
        """rating=6 非法，返回 422。"""
        resp = client.post("/api/v1/review/schedule-submit", json={
            "schedule_id": 1,
            "question_id": 1,
            "rating": 6,
        })

        assert resp.status_code == 422

    def test_schedule_submit_invalid_rating_negative(self):
        """rating=-1 非法，返回 422。"""
        resp = client.post("/api/v1/review/schedule-submit", json={
            "schedule_id": 1,
            "question_id": 1,
            "rating": -1,
        })

        assert resp.status_code == 422

    def test_schedule_submit_value_error_returns_400(self, monkeypatch):
        """ValueError 返回 400。"""
        monkeypatch.setattr(
            review.review_scheduler,
            "submit_review",
            AsyncMock(side_effect=ValueError("Invalid schedule_id"))
        )

        resp = client.post("/api/v1/review/schedule-submit", json={
            "schedule_id": 999,
            "question_id": 1,
            "rating": 4,
        })

        assert resp.status_code == 400
        assert "Invalid schedule_id" in resp.json()["detail"]


# ── /review/batch-submit ──


class TestBatchSubmitAPI:
    def setup_method(self):
        self.user, self.db = _override_auth_and_db()

    def teardown_method(self):
        _clear_overrides()

    def test_batch_submit_success(self, monkeypatch):
        """批量提交多个 schedule_id 成功。"""
        mock_result = {
            "results": [
                {"schedule_id": 1, "question_id": 1, "next_review_at": datetime.now(UTC).isoformat(), "is_correct": True},
                {"schedule_id": 2, "question_id": 2, "next_review_at": datetime.now(UTC).isoformat(), "is_correct": False},
            ],
            "total": 2,
        }
        monkeypatch.setattr(review.review_scheduler, "batch_submit_review", AsyncMock(return_value=mock_result))

        resp = client.post("/api/v1/review/batch-submit", json={
            "reviews": [
                {"schedule_id": 1, "question_id": 1, "rating": 4},
                {"schedule_id": 2, "question_id": 2, "rating": 1},
            ]
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["results"]) == 2

    def test_batch_submit_empty_list_returns_400(self):
        """空列表返回 400。"""
        resp = client.post("/api/v1/review/batch-submit", json={"reviews": []})

        assert resp.status_code == 400
        assert "复习列表不能为空" in resp.json()["detail"]

    def test_batch_submit_partial_failure(self, monkeypatch):
        """部分失败时返回错误信息。"""
        monkeypatch.setattr(
            review.review_scheduler,
            "batch_submit_review",
            AsyncMock(side_effect=ValueError("Schedule 999 not found"))
        )

        resp = client.post("/api/v1/review/batch-submit", json={
            "reviews": [
                {"schedule_id": 999, "question_id": 1, "rating": 4},
            ]
        })

        assert resp.status_code == 400
        assert "Schedule 999 not found" in resp.json()["detail"]


# ── /review/grade-submit ──


class TestGradeSubmitAPI:
    def setup_method(self):
        self.user, self.db = _override_auth_and_db()

    def teardown_method(self):
        _clear_overrides()

    def test_grade_submit_correct_answer(self, monkeypatch):
        """答对时默认 rating=4。"""
        mock_question = MagicMock()
        mock_question.id = 1
        mock_question.answer = "A"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_question
        self.db.execute = AsyncMock(return_value=mock_result)

        mock_review_result = {
            "schedule_id": 1,
            "question_id": 1,
            "rating": 4,
            "interval_after": 6,
            "ease_factor_after": 2.6,
            "next_review_at": datetime.now(UTC) + timedelta(days=6),
        }
        monkeypatch.setattr(review.review_scheduler, "submit_review", AsyncMock(return_value=mock_review_result))

        resp = client.post("/api/v1/review/grade-submit", json={
            "schedule_id": 1,
            "question_id": 1,
            "user_answer": "A",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["is_correct"] is True
        assert data["rating"] == 4

    def test_grade_submit_wrong_answer(self, monkeypatch):
        """答错时默认 rating=1。"""
        mock_question = MagicMock()
        mock_question.id = 1
        mock_question.answer = "A"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_question
        self.db.execute = AsyncMock(return_value=mock_result)

        mock_review_result = {
            "schedule_id": 1,
            "question_id": 1,
            "rating": 1,
            "interval_after": 1,
            "ease_factor_after": 2.0,
            "next_review_at": datetime.now(UTC) + timedelta(days=1),
        }
        monkeypatch.setattr(review.review_scheduler, "submit_review", AsyncMock(return_value=mock_review_result))

        resp = client.post("/api/v1/review/grade-submit", json={
            "schedule_id": 1,
            "question_id": 1,
            "user_answer": "B",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["is_correct"] is False
        assert data["rating"] == 1

    def test_grade_submit_question_not_found(self):
        """题目不存在返回 404。"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        self.db.execute = AsyncMock(return_value=mock_result)

        resp = client.post("/api/v1/review/grade-submit", json={
            "schedule_id": 1,
            "question_id": 999,
            "user_answer": "A",
        })

        assert resp.status_code == 404
        assert "题目不存在" in resp.json()["detail"]

    def test_grade_submit_not_use_5_or_0(self, monkeypatch):
        """验证不会再使用 5/0 作为自动批改默认值。"""
        mock_question = MagicMock()
        mock_question.id = 1
        mock_question.answer = "A"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_question
        self.db.execute = AsyncMock(return_value=mock_result)

        mock_review_result = {
            "schedule_id": 1,
            "question_id": 1,
            "rating": 4,
            "interval_after": 6,
            "ease_factor_after": 2.6,
            "next_review_at": datetime.now(UTC) + timedelta(days=6),
        }
        submit_mock = AsyncMock(return_value=mock_review_result)
        monkeypatch.setattr(review.review_scheduler, "submit_review", submit_mock)

        resp = client.post("/api/v1/review/grade-submit", json={
            "schedule_id": 1,
            "question_id": 1,
            "user_answer": "A",
        })

        assert resp.status_code == 200
        assert resp.json()["rating"] == 4
        assert resp.json()["rating"] != 5
        assert resp.json()["rating"] != 0

        # 验证调用 submit_review 时传入的 rating 是 4
        call_args = submit_mock.call_args
        assert call_args.kwargs["rating"] == 4
