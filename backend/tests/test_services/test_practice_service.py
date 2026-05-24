"""Stage 11 刷题系统 — 单元测试（mock DB session）。"""
import asyncio
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.practice_record import PracticeRecord
from app.models.question import Question


# --- helpers ---

def _make_mock_db():
    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.execute = AsyncMock()
    return db


def _make_execute_result(**methods):
    mock_result = MagicMock()
    for method, value in methods.items():
        if method == "scalars":
            mock_scalars = MagicMock()
            mock_scalars.all.return_value = value
            mock_result.scalars.return_value = mock_scalars
        elif method == "all":
            mock_result.all.return_value = value
        elif method == "one":
            mock_result.one.return_value = value
        else:
            getattr(mock_result, method).return_value = value
    return mock_result


def _make_question(id=1, subject="math2", question_type="single_choice",
                   answer="A", analysis="求导得 2x", knowledge_points=None,
                   is_active=True):
    q = MagicMock(spec=Question)
    q.id = id
    q.subject = subject
    q.question_type = question_type
    q.content = {"stem": "f(x)=x^2, f'(x)=?"}
    q.options = {"A": "2x", "B": "x", "C": "x^2", "D": "2"}
    q.answer = answer
    q.analysis = analysis
    q.knowledge_points = knowledge_points or ["导数"]
    q.difficulty = 2
    q.is_active = is_active
    return q


def _run(coro):
    return asyncio.run(coro)


# --- get_practice_questions ---

class TestGetPracticeQuestions:
    def test_random_mode(self):
        from app.services.practice_service import get_practice_questions

        db = _make_mock_db()
        q1, q2 = _make_question(1), _make_question(2)
        db.execute.return_value = _make_execute_result(scalars=[q1, q2])

        result = _run(get_practice_questions(db, user_id=1, subject="math2", count=5, mode="random"))
        assert len(result) == 2
        assert result[0].id == 1

    def test_sequential_mode(self):
        from app.services.practice_service import get_practice_questions

        db = _make_mock_db()
        q1, q2 = _make_question(1), _make_question(2)
        db.execute.return_value = _make_execute_result(scalars=[q1, q2])

        result = _run(get_practice_questions(db, user_id=1, subject="math2", count=5, mode="sequential"))
        assert len(result) == 2

    def test_filter_by_knowledge_point(self):
        from app.services.practice_service import get_practice_questions

        db = _make_mock_db()
        q1 = _make_question(1, knowledge_points=["导数", "极限"])
        db.execute.return_value = _make_execute_result(scalars=[q1])

        result = _run(get_practice_questions(
            db, user_id=1, subject="math2", count=5, knowledge_points=["导数"]
        ))
        assert len(result) == 1

    def test_exclude_answered(self):
        from app.services.practice_service import get_practice_questions

        db = _make_mock_db()
        q2 = _make_question(2)
        db.execute.return_value = _make_execute_result(scalars=[q2])

        result = _run(get_practice_questions(
            db, user_id=1, subject="math2", count=5, exclude_answered=True
        ))
        assert len(result) == 1

    def test_empty_result(self):
        from app.services.practice_service import get_practice_questions

        db = _make_mock_db()
        db.execute.return_value = _make_execute_result(scalars=[])

        result = _run(get_practice_questions(db, user_id=1, subject="math2", count=5))
        assert result == []


# --- submit_answer ---

class TestSubmitAnswer:
    def test_correct_answer(self):
        from app.services.practice_service import submit_answer

        db = _make_mock_db()
        q = _make_question(1, answer="A")
        db.execute.return_value = _make_execute_result(scalar_one_or_none=q)

        result = _run(submit_answer(db, user_id=1, question_id=1, user_answer="A"))
        assert result["is_correct"] is True
        assert result["correct_answer"] == "A"
        assert result["is_wrong_added"] is False

    def test_wrong_answer(self):
        from app.services.practice_service import submit_answer

        db = _make_mock_db()
        q = _make_question(1, answer="A")
        # First execute: get question, second: record_wrong query, third: behavior query
        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=q),
            _make_execute_result(scalar_one_or_none=None),  # no existing wrong question
            _make_execute_result(scalar_one_or_none=None),  # no existing behavior
        ]

        result = _run(submit_answer(db, user_id=1, question_id=1, user_answer="B"))
        assert result["is_correct"] is False
        assert result["correct_answer"] == "A"
        assert result["is_wrong_added"] is True

    def test_case_insensitive(self):
        from app.services.practice_service import submit_answer

        db = _make_mock_db()
        q = _make_question(1, answer="A")
        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=q),
            _make_execute_result(scalar_one_or_none=None),
            _make_execute_result(scalar_one_or_none=None),
        ]

        result = _run(submit_answer(db, user_id=1, question_id=1, user_answer="a"))
        assert result["is_correct"] is True

    def test_whitespace_trimmed(self):
        from app.services.practice_service import submit_answer

        db = _make_mock_db()
        q = _make_question(1, answer="A")
        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=q),
            _make_execute_result(scalar_one_or_none=None),
            _make_execute_result(scalar_one_or_none=None),
        ]

        result = _run(submit_answer(db, user_id=1, question_id=1, user_answer="  A  "))
        assert result["is_correct"] is True

    def test_question_not_found(self):
        from app.services.practice_service import submit_answer

        db = _make_mock_db()
        db.execute.return_value = _make_execute_result(scalar_one_or_none=None)

        with pytest.raises(ValueError, match="题目不存在"):
            _run(submit_answer(db, user_id=1, question_id=999, user_answer="A"))

    def test_inactive_question_ignored(self):
        from app.services.practice_service import submit_answer

        db = _make_mock_db()
        db.execute.return_value = _make_execute_result(scalar_one_or_none=None)

        with pytest.raises(ValueError, match="题目不存在"):
            _run(submit_answer(db, user_id=1, question_id=1, user_answer="A"))

    def test_used_time_optional(self):
        from app.services.practice_service import submit_answer

        db = _make_mock_db()
        q = _make_question(1, answer="A")
        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=q),
            _make_execute_result(scalar_one_or_none=None),
            _make_execute_result(scalar_one_or_none=None),
        ]

        result = _run(submit_answer(db, user_id=1, question_id=1, user_answer="A"))
        assert result["is_correct"] is True

    def test_creates_practice_record(self):
        from app.services.practice_service import submit_answer

        db = _make_mock_db()
        q = _make_question(1, answer="A")
        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=q),
            _make_execute_result(scalar_one_or_none=None),
            _make_execute_result(scalar_one_or_none=None),
        ]

        result = _run(submit_answer(db, user_id=1, question_id=1, user_answer="A"))
        db.add.assert_called()
        db.commit.assert_called()
        assert "record_id" in result


# --- batch_submit_answers ---

class TestBatchSubmit:
    def test_batch_submit(self):
        from app.services.practice_service import batch_submit_answers

        db = _make_mock_db()
        q1, q2 = _make_question(1, answer="A"), _make_question(2, answer="B")

        db.execute.side_effect = [
            # Batch question load
            _make_execute_result(scalars=[q1, q2]),
            # submit_answer q1 (correct → 1 execute: get question)
            _make_execute_result(scalar_one_or_none=q1),
            # submit_answer q2 (wrong → 2 executes: get question + record_wrong)
            _make_execute_result(scalar_one_or_none=q2),
            _make_execute_result(scalar_one_or_none=None),
        ]

        result = _run(batch_submit_answers(db, user_id=1, answers=[
            {"question_id": 1, "user_answer": "A"},
            {"question_id": 2, "user_answer": "C"},
        ]))
        assert result["total_correct"] == 1
        assert result["total_wrong"] == 1
        assert len(result["results"]) == 2

    def test_batch_missing_question(self):
        from app.services.practice_service import batch_submit_answers

        db = _make_mock_db()
        q1 = _make_question(1, answer="A")
        db.execute.return_value = _make_execute_result(scalars=[q1])

        with pytest.raises(ValueError, match="题目不存在"):
            _run(batch_submit_answers(db, user_id=1, answers=[
                {"question_id": 1, "user_answer": "A"},
                {"question_id": 999, "user_answer": "B"},
            ]))


# --- get_practice_stats ---

class TestPracticeStats:
    def test_stats_with_data(self):
        from app.services.practice_service import get_practice_stats

        db = _make_mock_db()
        today_str = date.today().isoformat()
        db.execute.side_effect = [
            # Total count + correct (base query)
            _make_execute_result(one=(10, 7)),
            # By subject
            _make_execute_result(scalars=[]),
            # Daily stats
            _make_execute_result(scalars=[]),
            # Streak query
            _make_execute_result(scalars=[]),
        ]

        result = _run(get_practice_stats(db, user_id=1, days=7))
        assert result["total_answered"] == 10
        assert result["total_correct"] == 7
        assert result["accuracy"] == 0.7
        assert result["current_streak"] == 0

    def test_stats_empty(self):
        from app.services.practice_service import get_practice_stats

        db = _make_mock_db()
        db.execute.side_effect = [
            _make_execute_result(one=(0, 0)),
            _make_execute_result(scalars=[]),
            _make_execute_result(scalars=[]),
            _make_execute_result(scalars=[]),
        ]

        result = _run(get_practice_stats(db, user_id=1))
        assert result["total_answered"] == 0
        assert result["total_correct"] == 0
        assert result["accuracy"] == 0.0

    def test_stats_by_subject(self):
        from app.services.practice_service import get_practice_stats

        db = _make_mock_db()
        db.execute.side_effect = [
            _make_execute_result(one=(5, 4)),
            _make_execute_result(all=[("math2", 5, 4)]),
            _make_execute_result(all=[]),
            _make_execute_result(scalars=[]),
        ]

        result = _run(get_practice_stats(db, user_id=1))
        assert "math2" in result["by_subject"]
        assert result["by_subject"]["math2"]["answered"] == 5
        assert result["by_subject"]["math2"]["accuracy"] == 0.8


# --- streak calculation ---

class TestStreak:
    def test_no_records(self):
        from app.services.practice_service import _calc_streak

        db = _make_mock_db()
        db.execute.return_value = _make_execute_result(all=[])

        streak = _run(_calc_streak(db, user_id=1))
        assert streak == 0

    def test_consecutive_days(self):
        from app.services.practice_service import _calc_streak

        db = _make_mock_db()
        today = date.today()
        dates = [(today,), (today - timedelta(days=1),)]
        db.execute.return_value = _make_execute_result(all=dates)

        streak = _run(_calc_streak(db, user_id=1))
        assert streak == 2

    def test_gap_resets_streak(self):
        from app.services.practice_service import _calc_streak

        db = _make_mock_db()
        today = date.today()
        dates = [(today - timedelta(days=2),)]
        db.execute.return_value = _make_execute_result(all=dates)

        streak = _run(_calc_streak(db, user_id=1))
        assert streak == 0


# --- get_wrong_questions ---

class TestGetWrongQuestions:
    def test_with_questions(self):
        from app.services.practice_service import get_wrong_questions

        db = _make_mock_db()

        wq = MagicMock()
        wq.id = 1
        wq.question_id = 10
        wq.wrong_answer = "B"
        wq.review_count = 2
        wq.mastered = False
        wq.last_review_at = datetime.utcnow()

        q = _make_question(10, answer="A")
        db.execute.side_effect = [
            _make_execute_result(scalar=5),       # list_wrong: count query
            _make_execute_result(scalars=[wq]),   # list_wrong: items query
            _make_execute_result(scalars=[q]),    # question lookup
        ]

        result = _run(get_wrong_questions(db, user_id=1))
        assert result["total"] == 5
        assert len(result["items"]) == 1
        assert result["items"][0]["question"]["id"] == 10
        assert result["items"][0]["question"]["answer"] == "A"


# --- review_wrong_question ---

class TestReviewWrongQuestion:
    def test_review_correct(self):
        from app.services.practice_service import review_wrong_question
        from app.models.wrong_question import WrongQuestion

        db = _make_mock_db()
        q = _make_question(1, answer="A")

        wq = MagicMock()
        wq.user_id = 1
        wq.question_id = 1
        wq.efactor = 2.5
        wq.interval = 1
        wq.repetitions = 1
        wq.review_count = 2
        wq.quality = 3
        wq.mastered = False

        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=q),   # submit_answer: get question
            _make_execute_result(scalar_one_or_none=wq),   # review: get wrong_question
        ]

        result = _run(review_wrong_question(db, user_id=1, question_id=1, user_answer="A"))
        assert result["is_correct"] is True
        assert "sm2" in result
        assert result["sm2"]["efactor"] > 2.5  # quality 5 should increase efactor

    def test_review_wrong_again(self):
        from app.services.practice_service import review_wrong_question
        from app.models.wrong_question import WrongQuestion

        db = _make_mock_db()
        q = _make_question(1, answer="A")

        wq = MagicMock()
        wq.user_id = 1
        wq.question_id = 1
        wq.efactor = 2.5
        wq.interval = 1
        wq.repetitions = 0
        wq.review_count = 2
        wq.quality = 3
        wq.mastered = False

        db.execute.side_effect = [
            _make_execute_result(scalar_one_or_none=q),     # submit: get question
            _make_execute_result(scalar_one_or_none=None),  # submit: record_wrong lookup
            _make_execute_result(scalar_one_or_none=wq),    # review: get wrong_question
        ]

        result = _run(review_wrong_question(db, user_id=1, question_id=1, user_answer="B"))
        assert result["is_correct"] is False
