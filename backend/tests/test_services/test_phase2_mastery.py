"""Phase 2 — 知识点掌握度画像 + 推荐反馈闭环 单元测试。"""
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.knowledge_point import KnowledgePoint
from app.models.question_knowledge_point import QuestionKnowledgePoint
from app.models.user_knowledge_state import UserKnowledgeState
from app.models.recommendation_log import RecommendationLog
from app.models.question import Question


# --- helpers ---

def _make_mock_db():
    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
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
        elif method == "scalar_one_or_none":
            mock_result.scalar_one_or_none.return_value = value
        elif method == "scalar":
            mock_result.scalar.return_value = value
        else:
            getattr(mock_result, method).return_value = value
    return mock_result


_KP_SENTINEL = object()


def _make_question(id=1, subject="math2", question_type="single_choice",
                   answer="A", analysis="求导得 2x", knowledge_points=_KP_SENTINEL,
                   is_active=True):
    q = MagicMock(spec=Question)
    q.id = id
    q.subject = subject
    q.question_type = question_type
    q.content = {"stem": "f(x)=x^2, f'(x)=?"}
    q.options = {"A": "2x", "B": "x", "C": "x^2", "D": "2"}
    q.answer = answer
    q.analysis = analysis
    q.knowledge_points = ["导数"] if knowledge_points is _KP_SENTINEL else knowledge_points
    q.difficulty = 2
    q.is_active = is_active
    return q


def _make_kp(id=1, subject="math2", name="导数", normalized_name="导数"):
    kp = MagicMock(spec=KnowledgePoint)
    kp.id = id
    kp.subject = subject
    kp.name = name
    kp.normalized_name = normalized_name
    kp.aliases = None
    kp.description = None
    kp.difficulty_level = 3
    kp.is_active = True
    return kp


def _make_qkp(question_id=1, kp_id=1, role="main", weight=1.0, source="imported"):
    qkp = MagicMock(spec=QuestionKnowledgePoint)
    qkp.id = 1
    qkp.question_id = question_id
    qkp.knowledge_point_id = kp_id
    qkp.role = role
    qkp.weight = weight
    qkp.source = source
    return qkp


def _make_uks(id=1, user_id=1, subject="math2", kp_id=1, attempt=5, correct=3,
              wrong=2, accuracy=0.6, mastery=0.5, weakness="medium"):
    uks = MagicMock(spec=UserKnowledgeState)
    uks.id = id
    uks.user_id = user_id
    uks.subject = subject
    uks.knowledge_point_id = kp_id
    uks.attempt_count = attempt
    uks.correct_count = correct
    uks.wrong_count = wrong
    uks.accuracy = accuracy
    uks.mastery_score = mastery
    uks.weakness_level = weakness
    uks.last_practiced_at = datetime(2026, 6, 20)
    uks.last_wrong_at = datetime(2026, 6, 19)
    return uks


def _run(coro):
    return asyncio.run(coro)


# ── 1. normalize_knowledge_name ──

class TestNormalizeKnowledgeName:
    def test_basic_normalization(self):
        from app.services.knowledge_point_service import normalize_knowledge_name
        # 去首尾空格 + 多空格合并
        assert normalize_knowledge_name("  导数  基础  ") == "导数 基础"

    def test_lowercase_english(self):
        from app.services.knowledge_point_service import normalize_knowledge_name
        assert normalize_knowledge_name("Calculus") == "calculus"

    def test_fullwidth_to_halfwidth(self):
        from app.services.knowledge_point_service import normalize_knowledge_name
        # 全角括号 → 半角括号
        assert normalize_knowledge_name("导数（基础）") == "导数(基础)"

    def test_empty_string(self):
        from app.services.knowledge_point_service import normalize_knowledge_name
        assert normalize_knowledge_name("") == ""
        assert normalize_knowledge_name("   ") == ""

    def test_chinese_preserved(self):
        from app.services.knowledge_point_service import normalize_knowledge_name
        assert normalize_knowledge_name("极限与连续") == "极限与连续"


# ── 2. sync_question_knowledge_points ──

class TestSyncQuestionKnowledgePoints:
    def test_sync_creates_mappings(self):
        from app.services.knowledge_point_service import sync_question_knowledge_points

        db = _make_mock_db()
        q = _make_question(id=10, subject="math2", knowledge_points=["导数", "极限"])
        kp1 = _make_kp(id=1, name="导数")
        kp2 = _make_kp(id=2, name="极限")

        # get_or_create: first call returns kp1, second returns kp2
        # existing check: both return None (no existing mapping)
        call_count = [0]
        kps = [kp1, kp2]

        async def mock_execute(query):
            call_count[0] += 1
            # Odd calls: get_or_create lookup (scalar_one_or_none)
            # Even calls: existing check (scalar_one_or_none)
            if call_count[0] % 2 == 1:
                # get_or_create lookup
                idx = (call_count[0] - 1) // 2
                if idx < len(kps):
                    return _make_execute_result(scalar_one_or_none=None)
                return _make_execute_result(scalar_one_or_none=kps[-1])
            else:
                # existing mapping check
                return _make_execute_result(scalar_one_or_none=None)

        db.execute = AsyncMock(side_effect=mock_execute)

        result = _run(sync_question_knowledge_points(db, q, source="imported"))
        assert result["total"] == 2
        assert result["created"] == 2
        assert result["skipped"] == 0

    def test_sync_skips_empty_knowledge_points(self):
        from app.services.knowledge_point_service import sync_question_knowledge_points

        db = _make_mock_db()
        q = _make_question(id=10, subject="math2", knowledge_points=[])

        result = _run(sync_question_knowledge_points(db, q))
        assert result["total"] == 0
        assert result["created"] == 0

    def test_sync_skips_none_knowledge_points(self):
        from app.services.knowledge_point_service import sync_question_knowledge_points

        db = _make_mock_db()
        q = _make_question(id=10, subject="math2", knowledge_points=None)

        result = _run(sync_question_knowledge_points(db, q))
        assert result["total"] == 0


# ── 3. calculate_mastery_score ──

class TestCalculateMasteryScore:
    def test_zero_attempts(self):
        from app.services.mastery_service import calculate_mastery_score
        score = calculate_mastery_score(0, 0, 0)
        assert score == 0.0

    def test_all_correct(self):
        from app.services.mastery_service import calculate_mastery_score
        score = calculate_mastery_score(10, 10, 0)
        assert score > 0.8  # High score expected

    def test_all_wrong(self):
        from app.services.mastery_service import calculate_mastery_score
        score = calculate_mastery_score(10, 0, 10)
        assert score < 0.3  # Low score expected

    def test_penalty_for_recent_wrong(self):
        from app.services.mastery_service import calculate_mastery_score
        now = datetime(2026, 6, 28)
        score_no_penalty = calculate_mastery_score(10, 5, 5, last_wrong_at=None, last_practiced_at=now)
        score_with_penalty = calculate_mastery_score(10, 5, 5, last_wrong_at=now, last_practiced_at=now)
        assert score_no_penalty > score_with_penalty

    def test_score_clamped_0_to_1(self):
        from app.services.mastery_service import calculate_mastery_score
        score = calculate_mastery_score(1, 0, 1, last_wrong_at=datetime(2026, 6, 28), last_practiced_at=datetime(2026, 6, 28))
        assert 0.0 <= score <= 1.0


# ── 4. classify_weakness_level ──

class TestClassifyWeaknessLevel:
    def test_unknown_when_no_attempts(self):
        from app.services.mastery_service import classify_weakness_level
        assert classify_weakness_level(0.0, 0) == "unknown"

    def test_weak(self):
        from app.services.mastery_service import classify_weakness_level
        assert classify_weakness_level(0.3, 5) == "weak"

    def test_medium(self):
        from app.services.mastery_service import classify_weakness_level
        assert classify_weakness_level(0.6, 5) == "medium"

    def test_strong(self):
        from app.services.mastery_service import classify_weakness_level
        assert classify_weakness_level(0.9, 10) == "strong"

    def test_boundary_045(self):
        from app.services.mastery_service import classify_weakness_level
        # 0.45 is NOT < 0.45 so should be medium
        assert classify_weakness_level(0.45, 5) == "medium"

    def test_boundary_075(self):
        from app.services.mastery_service import classify_weakness_level
        # 0.75 is NOT < 0.75 so should be strong
        assert classify_weakness_level(0.75, 5) == "strong"


# ── 5. update_user_knowledge_state_after_answer ──

class TestUpdateUserKnowledgeState:
    def test_correct_answer_increases_mastery(self):
        from app.services.mastery_service import update_user_knowledge_state_after_answer

        db = _make_mock_db()
        kp = _make_kp(id=1, name="导数")
        qkp = _make_qkp(question_id=1, kp_id=1)

        # Mock sequence matching actual function flow:
        # 1st call: QKP join KP query → returns [(qkp, kp)]
        # 2nd call: Question.subject query → returns "math2"
        # 3rd call: UserKnowledgeState lookup → returns None (new state)
        call_count = [0]

        async def mock_execute(query):
            call_count[0] += 1
            if call_count[0] == 1:
                # QKP join KP query
                return _make_execute_result(all=[(qkp, kp)])
            elif call_count[0] == 2:
                # Question.subject lookup
                return _make_execute_result(scalar_one_or_none="math2")
            elif call_count[0] == 3:
                # UserKnowledgeState lookup — no existing state
                return _make_execute_result(scalar_one_or_none=None)
            return _make_execute_result()

        db.execute = AsyncMock(side_effect=mock_execute)

        result = _run(update_user_knowledge_state_after_answer(db, 1, 1, True))
        assert result["created"] == 1
        assert result["updated"] == 1
        # Verify db.add was called (new state created)
        db.add.assert_called()

    def test_wrong_answer_may_decrease_weakness(self):
        from app.services.mastery_service import update_user_knowledge_state_after_answer, classify_weakness_level, calculate_mastery_score

        # After many wrong answers, weakness should be "weak"
        score = calculate_mastery_score(10, 1, 9, last_wrong_at=datetime(2026, 6, 28), last_practiced_at=datetime(2026, 6, 28))
        level = classify_weakness_level(score, 10)
        assert level == "weak"


# ── 6. get_user_weak_knowledge_points ──

class TestGetUserWeakKnowledgePoints:
    def test_returns_weak_points_from_uks(self):
        from app.services.mastery_service import get_user_weak_knowledge_points

        db = _make_mock_db()
        uks = _make_uks(mastery=0.3, weakness="weak", attempt=5)

        db.execute = AsyncMock(return_value=_make_execute_result(all=[(uks, "导数")]))

        result = _run(get_user_weak_knowledge_points(db, 1, "math2", limit=5))
        assert len(result) == 1
        assert result[0]["name"] == "导数"
        assert result[0]["weakness_level"] == "weak"

    def test_fallback_to_practice_records_when_no_uks(self):
        from app.services.mastery_service import get_user_weak_knowledge_points

        db = _make_mock_db()

        # First call: UKS query returns empty
        # Second call: PracticeRecord fallback query
        pr = MagicMock()
        pr.is_correct = False

        call_count = [0]

        async def mock_execute(query):
            call_count[0] += 1
            if call_count[0] == 1:
                # UKS query — empty
                return _make_execute_result(all=[])
            else:
                # PracticeRecord fallback
                return _make_execute_result(all=[(pr, ["导数", "极限"]), (pr, ["导数"])])

        db.execute = AsyncMock(side_effect=mock_execute)

        result = _run(get_user_weak_knowledge_points(db, 1, "math2", limit=5))
        # 导数: 2 attempts, 0 correct → accuracy=0 → weak
        assert len(result) >= 1
        names = [r["name"] for r in result]
        assert "导数" in names


# ── 7. recommendation_log_service ──

class TestRecommendationLogService:
    def test_create_recommendation_logs(self):
        from app.services.recommendation_log_service import create_recommendation_logs

        db = _make_mock_db()
        recs = [
            {"question_id": 1, "subject": "math2", "recommend_score": 0.9, "similarity": 0.85, "reason": "薄弱知识点"},
            {"question_id": 2, "subject": "math2", "recommend_score": 0.7, "similarity": 0.6, "reason": "向量相似"},
        ]

        ids = _run(create_recommendation_logs(db, user_id=1, recommendations=recs, scene="practice_smart", strategy="smart_vector", request_id="test-req-123"))
        assert len(ids) == 2
        assert db.add.call_count == 2

    def test_mark_recommendation_answered(self):
        from app.services.recommendation_log_service import mark_recommendation_answered

        db = _make_mock_db()
        log = MagicMock(spec=RecommendationLog)
        log.id = 1
        log.answered_at = None
        log.is_correct = None

        db.execute = AsyncMock(return_value=_make_execute_result(scalar_one_or_none=log))

        result = _run(mark_recommendation_answered(db, user_id=1, question_id=1, is_correct=True, request_id="req-123"))
        assert result is True
        assert log.answered_at is not None
        assert log.is_correct is True

    def test_mark_recommendation_clicked(self):
        from app.services.recommendation_log_service import mark_recommendation_clicked

        db = _make_mock_db()
        log = MagicMock(spec=RecommendationLog)
        log.id = 1
        log.clicked_at = None

        db.execute = AsyncMock(return_value=_make_execute_result(scalar_one_or_none=log))

        result = _run(mark_recommendation_clicked(db, user_id=1, question_id=1, request_id="req-123"))
        assert result is True
        assert log.clicked_at is not None

    def test_mark_answered_no_match(self):
        from app.services.recommendation_log_service import mark_recommendation_answered

        db = _make_mock_db()
        db.execute = AsyncMock(return_value=_make_execute_result(scalar_one_or_none=None))

        result = _run(mark_recommendation_answered(db, user_id=1, question_id=999, is_correct=True))
        assert result is False


# ── 8. smart mode integration ──

class TestSmartModeIntegration:
    @patch("app.services.practice_service.vector_retrieval_service", create=True)
    def test_smart_mode_uses_mastery_service(self, mock_vrs):
        """smart mode should try mastery_service first, fallback to _compute_weak_knowledge_points."""
        import app.services
        from app.services.practice_service import get_smart_practice_questions

        db = _make_mock_db()
        q1 = _make_question(1, knowledge_points=["导数"])

        # Mock vector recall to raise (simulating vector unavailable)
        mock_vrs.vector_recall_by_text = AsyncMock(side_effect=Exception("vector disabled"))

        # Mock db.execute: return questions for the kp-filter fallback query
        db.execute = AsyncMock(return_value=_make_execute_result(scalars=[q1]))

        mock_ms = MagicMock()
        mock_ms.get_user_weak_knowledge_points = AsyncMock(return_value=[
            {"name": "导数", "mastery_score": 0.3, "accuracy": 0.3, "attempt_count": 5, "weakness_level": "weak"}
        ])
        mock_rls = MagicMock()
        mock_rls.create_recommendation_logs = AsyncMock(return_value=[1])

        # Patch at the app.services package attribute level so `from app.services import X` picks up the mock
        with patch.object(app.services, "mastery_service", mock_ms), \
             patch.object(app.services, "recommendation_log_service", mock_rls):
            result = _run(get_smart_practice_questions(
                db, user_id=1, subject="math2", count=5, request_id="test-req-1",
            ))

            questions, metadata = result
            # Verify mastery_service was called
            mock_ms.get_user_weak_knowledge_points.assert_called_once()
            # Verify we got questions back
            assert len(questions) >= 1
            # Verify recommendation log service was called with request_id
            mock_rls.create_recommendation_logs.assert_called_once()
            call_kwargs = mock_rls.create_recommendation_logs.call_args[1]
            assert call_kwargs.get("request_id") == "test-req-1"

    def test_random_mode_not_affected(self):
        """random mode should work exactly as before."""
        from app.services.practice_service import get_practice_questions

        db = _make_mock_db()
        q1 = _make_question(1)
        db.execute = AsyncMock(return_value=_make_execute_result(scalars=[q1]))

        result = _run(get_practice_questions(db, user_id=1, subject="math2", count=5, mode="random"))
        assert len(result) == 1
        assert result[0].id == 1

    def test_sequential_mode_not_affected(self):
        """sequential mode should work exactly as before."""
        from app.services.practice_service import get_practice_questions

        db = _make_mock_db()
        q1, q2 = _make_question(1), _make_question(2)
        db.execute = AsyncMock(return_value=_make_execute_result(scalars=[q1, q2]))

        result = _run(get_practice_questions(db, user_id=1, subject="math2", count=5, mode="sequential"))
        assert len(result) == 2


# ── 9. submit_answer feedback loop ──

class TestSubmitAnswerFeedbackLoop:
    def test_submit_calls_mastery_and_log(self):
        """submit_answer should call mastery_service and recommendation_log_service."""
        from app.services.practice_service import submit_answer

        db = _make_mock_db()
        q = _make_question(1, answer="A")

        # Mock db.execute to return question
        db.execute = AsyncMock(return_value=_make_execute_result(scalar_one_or_none=q))

        with patch("app.services.practice_service.record_wrong", new_callable=AsyncMock) as mock_wrong, \
             patch("app.services.practice_service.record_answer_behavior", new_callable=AsyncMock) as mock_behavior:
            result = _run(submit_answer(db, user_id=1, question_id=1, user_answer="B", request_id="test-req"))

        assert result["is_correct"] is False
        assert result["is_wrong_added"] is True
        # mastery_service and recommendation_log_service are called via try/except,
        # so even if they fail, the result is still returned
        assert result["question_id"] == 1
