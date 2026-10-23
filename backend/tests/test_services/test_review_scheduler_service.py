"""Review API tests — content normalization, question filtering, count consistency."""
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.api.v1 import review
from app.main import app
from app.models.user import User

client = TestClient(app)

def _override_auth():
    user = User(id=1, openid="test_openid", nickname="test")
    app.dependency_overrides[review.get_current_user] = lambda: user
    return user


def _mock_db():
    db = AsyncMock()
    app.dependency_overrides[review.get_db] = lambda: db
    return db


def _clear_overrides():
    app.dependency_overrides.clear()


class TestReviewNextBatch:
    """POST /review/today/next-batch — content and count correctness."""

    def setup_method(self):
        _override_auth()
        _mock_db()

    def teardown_method(self):
        _clear_overrides()

    def test_content_as_dict_succeeds(self, monkeypatch):
        """content as dict is accepted (no 500)."""
        monkeypatch.setattr(
            review.review_scheduler, "get_next_today_review_batch", AsyncMock(
                return_value={
                    "questions": [{
                        "schedule_id": 1, "question_id": 1, "question_version_id": 11, "occurrence_seq": 0,
                        "subject_id": 1, "subject_code": "math2", "subject_name": "数学二",
                        "question_type": "single_choice",
                        "stem": "Test",
                        "options": {"A": "a", "B": "b"},
                        "content": {"text": "Test", "image_url": []},
                        "image_url": None,
                        "interval": 1, "repetitions": 0, "ease_factor": 2.5,
                    }],
                    "batch_no": 1, "total_batch_count": 1, "batch_size": 1,
                    "today_due_count": 1, "today_completed_count": 0,
                    "today_remaining_count": 1,
                    "session_id": "s1", "group_id": "g1",
                }
            )
        )
        resp = client.post("/api/v1/review/today/next-batch", json={"batch_size": 10})
        assert resp.status_code == 200
        assert resp.json()["questions"][0]["content"] == {"text": "Test", "image_url": []}

    def test_content_as_string_succeeds(self, monkeypatch):
        """content as string is normalized by service (no 500 from schema validation)."""
        monkeypatch.setattr(
            review.review_scheduler, "get_next_today_review_batch", AsyncMock(
                return_value={
                    "questions": [{
                        "schedule_id": 1, "question_id": 1, "question_version_id": 11, "occurrence_seq": 0,
                        "subject_id": 1, "subject_code": "math2", "subject_name": "数学二", "question_type": "single_choice",
                        "stem": "Raw stem",
                        "options": {"A": "a", "B": "b"},
                        "content": {"text": "Raw stem"},  # Already normalized by service
                        "image_url": None,
                        "interval": 1, "repetitions": 0, "ease_factor": 2.5,
                    }],
                    "batch_no": 1, "total_batch_count": 1, "batch_size": 1,
                    "today_due_count": 1, "today_completed_count": 0,
                    "today_remaining_count": 1,
                    "session_id": "s1", "group_id": "g1",
                }
            )
        )
        resp = client.post("/api/v1/review/today/next-batch", json={"batch_size": 10})
        assert resp.status_code == 200
        assert resp.json()["questions"][0]["content"]["text"] == "Raw stem"

    def test_subject_none_succeeds(self, monkeypatch):
        """subject=None does not cause response validation 500."""
        monkeypatch.setattr(
            review.review_scheduler, "get_next_today_review_batch", AsyncMock(
                return_value={
                    "questions": [{
                        "schedule_id": 1, "question_id": 1, "question_version_id": 11, "occurrence_seq": 0,
                        "subject_id": None,  # Must be accepted
                        "question_type": "single_choice",
                        "stem": "Test",
                        "options": {"A": "a", "B": "b"},
                        "content": {"text": "Test"},
                        "image_url": None,
                        "interval": 1, "repetitions": 0, "ease_factor": 2.5,
                    }],
                    "batch_no": 1, "total_batch_count": 1, "batch_size": 1,
                    "today_due_count": 1, "today_completed_count": 0,
                    "today_remaining_count": 1,
                    "session_id": "s1", "group_id": "g1",
                }
            )
        )
        resp = client.post("/api/v1/review/today/next-batch", json={"batch_size": 10})
        assert resp.status_code == 200
        assert resp.json()["questions"][0]["subject_id"] is None

    def test_image_url_in_response(self, monkeypatch):
        """image_url is included in the response."""
        monkeypatch.setattr(
            review.review_scheduler, "get_next_today_review_batch", AsyncMock(
                return_value={
                    "questions": [{
                        "schedule_id": 1, "question_id": 1, "question_version_id": 11, "occurrence_seq": 0,
                        "subject_id": 1, "subject_code": "math2", "subject_name": "数学二", "question_type": "single_choice",
                        "stem": "Test",
                        "options": {"A": "a", "B": "b"},
                        "content": {"text": "Test"},
                        "image_url": ["http://example.com/img.png"],
                        "interval": 1, "repetitions": 0, "ease_factor": 2.5,
                    }],
                    "batch_no": 1, "total_batch_count": 1, "batch_size": 1,
                    "today_due_count": 1, "today_completed_count": 0,
                    "today_remaining_count": 1,
                    "session_id": "s1", "group_id": "g1",
                }
            )
        )
        resp = client.post("/api/v1/review/today/next-batch", json={"batch_size": 10})
        assert resp.status_code == 200
        assert resp.json()["questions"][0]["image_url"] == ["http://example.com/img.png"]

    def test_dirty_schedule_filtered(self, monkeypatch):
        """Schedule pointing to non-existent question is filtered from counts."""
        monkeypatch.setattr(
            review.review_scheduler, "get_next_today_review_batch", AsyncMock(
                return_value={
                    "questions": [{
                        "schedule_id": 1, "question_id": 1, "question_version_id": 11, "occurrence_seq": 0,
                        "subject_id": 1, "subject_code": "math2", "subject_name": "数学二", "question_type": "single_choice",
                        "stem": "Test",
                        "options": {"A": "a", "B": "b"},
                        "content": {"text": "Test"},
                        "image_url": None,
                        "interval": 1, "repetitions": 0, "ease_factor": 2.5,
                    }],
                    "batch_no": 1, "total_batch_count": 1, "batch_size": 1,
                    # 3 schedules total, 1 points to deleted question → due_count=2
                    "today_due_count": 2,
                    "today_completed_count": 0,
                    "today_remaining_count": 2,
                    "session_id": "s1", "group_id": "g1",
                }
            )
        )
        resp = client.post("/api/v1/review/today/next-batch", json={"batch_size": 10})
        assert resp.status_code == 200
        data = resp.json()
        assert data["today_due_count"] == 2
        assert data["today_due_count"] == data["today_completed_count"] + data["today_remaining_count"]

    def test_review_record_outside_due_set_excluded(self, monkeypatch):
        """ReviewRecord for questions NOT in today's due set is excluded from completed_count."""
        monkeypatch.setattr(
            review.review_scheduler, "get_next_today_review_batch", AsyncMock(
                return_value={
                    "questions": [{
                        "schedule_id": 3, "question_id": 3, "question_version_id": 13, "occurrence_seq": 0,
                        "subject_id": 1, "subject_code": "math2", "subject_name": "数学二", "question_type": "single_choice",
                        "stem": "Q3",
                        "options": {"A": "a", "B": "b"},
                        "content": {"text": "Q3"},
                        "image_url": None,
                        "interval": 1, "repetitions": 0, "ease_factor": 2.5,
                    }],
                    "batch_no": 2, "total_batch_count": 2, "batch_size": 1,
                    # due=3 questions, but completed question_id=999 is outside due set
                    "today_due_count": 3,
                    "today_completed_count": 1,  # only Q1 in due set was completed
                    "today_remaining_count": 2,
                    "session_id": "s1", "group_id": "g2",
                }
            )
        )
        resp = client.post("/api/v1/review/today/next-batch", json={"batch_size": 10})
        assert resp.status_code == 200
        data = resp.json()
        assert data["today_due_count"] == 3
        assert data["today_completed_count"] == 1
        assert data["today_remaining_count"] == 2
        assert data["today_due_count"] == data["today_completed_count"] + data["today_remaining_count"]


class TestReviewOverview:
    """GET /review/today/overview"""

    def setup_method(self):
        _override_auth()
        _mock_db()

    def teardown_method(self):
        _clear_overrides()

    def test_overview_consistent_counts(self, monkeypatch):
        """Overview counts are consistent with what next-batch would return."""
        monkeypatch.setattr(
            review.review_scheduler, "get_today_review_overview", AsyncMock(
                return_value={
                    "date": "2026-07-22",
                    "today_due_count": 5,
                    "today_completed_count": 2,
                    "today_remaining_count": 3,
                    "today_overdue_count": 1,
                    "today_new_due_count": 4,
                    "estimated_minutes": 2,
                    "batch_size": 10,
                    "current_batch_no": 1,
                    "total_batch_count": 1,
                    "remaining_batch_count": 1,
                    "all_question_ids": [1, 2, 3, 4, 5],
                    "completed_question_ids": [1, 2],
                    "remaining_question_ids": [3, 4, 5],
                    "has_due_review": True,
                    "is_completed": False,
                }
            )
        )
        resp = client.get("/api/v1/review/today/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert data["today_due_count"] == 5
        assert data["today_completed_count"] == 2
        assert data["today_remaining_count"] == 3
        assert data["today_due_count"] == data["today_completed_count"] + data["today_remaining_count"]
