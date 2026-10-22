"""Phase 2 — 知识点掌握度画像 + 推荐反馈闭环 单元测试。"""
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure all ORM models are registered so Subject's string relationships
# (practice_records, answer_behaviors, review_schedules, ...) resolve at
# mapper configuration time (see app/models/admin.py Subject).
from app.models.answer_behavior import AnswerBehavior  # noqa: F401
from app.models.import_batch_job import ImportBatchJob  # noqa: F401
from app.models.knowledge_edge import KnowledgeEdge  # noqa: F401
from app.models.knowledge_point import KnowledgePoint
from app.models.pomodoro import PomodoroSession  # noqa: F401
from app.models.practice_record import PracticeRecord  # noqa: F401
from app.models.question import Question
from app.models.question_knowledge_point import QuestionKnowledgePoint
from app.models.recommendation_log import RecommendationLog
from app.models.recommendation_metrics_daily import (
    RecommendationMetricsDaily,  # noqa: F401
)
from app.models.review_scheduler import ReviewSchedule  # noqa: F401
from app.models.tag import Tag  # noqa: F401
from app.models.user_knowledge_state import UserKnowledgeState

# --- helpers ---

def _make_mock_db():
    db = MagicMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.execute = AsyncMock()
    db.rollback = AsyncMock()
    db.scalar = AsyncMock(return_value=0)
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


def _make_question(id=1, subject_id=1, question_type="single_choice",
                   answer="A", analysis="求导得 2x", knowledge_points=None,
                   is_active=True):
    q = MagicMock(spec=Question)
    q.id = id
    q.subject_id = subject_id
    q.question_type = question_type
    q.content = {"stem": "f(x)=x^2, f'(x)=?"}
    q.options = {"A": "2x", "B": "x", "C": "x^2", "D": "2"}
    q.answer = answer
    q.analysis = analysis
    q.difficulty = 2
    q.is_active = is_active
    return q


def _make_kp(id=1, subject_id=1, name="导数", normalized_name="导数"):
    kp = MagicMock(spec=KnowledgePoint)
    kp.id = id
    kp.subject_id = subject_id
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


def _make_uks(id=1, user_id=1, subject_id=1, kp_id=1, attempt=5, correct=3,
              wrong=2, accuracy=0.6, mastery=0.5, weakness="medium"):
    uks = MagicMock(spec=UserKnowledgeState)
    uks.id = id
    uks.user_id = user_id
    uks.subject_id = subject_id
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
        q = _make_question(id=10, subject_id=1)

        async def mock_execute(query):
            text = str(query)
            if "FROM question_knowledge_points" in text:
                r = MagicMock()
                r.all.return_value = []
                return r
            # get_or_create lookup → 未存在 → 新建
            r = MagicMock()
            r.scalar_one_or_none.return_value = None
            return r

        db.execute = AsyncMock(side_effect=mock_execute)

        with patch("app.services.question_revision_service.lock_question_for_revision", new=AsyncMock(return_value=q)), \
             patch("app.services.knowledge_point_service.resolve_knowledge_points", new=AsyncMock(return_value=[_make_kp(1), _make_kp(2)])):
            result = _run(sync_question_knowledge_points(db, q, ["导数", "极限"], source="imported"))
        assert result["total"] == 2
        assert result["created"] == 2
        assert result["deleted"] == 0

    def test_sync_replace_clears_and_exact(self):
        from app.services.knowledge_point_service import sync_question_knowledge_points

        db = _make_mock_db()
        q = _make_question(id=10, subject_id=1)

        def _mapping(kp_id, position):
            m = MagicMock(spec=QuestionKnowledgePoint)
            m.knowledge_point_id = kp_id
            m.position = position
            return m

        async def mock_execute(query):
            text = str(query)
            if "FROM question_knowledge_points" in text:
                return _make_execute_result(scalars=[_mapping(1, 0), _mapping(2, 1)])
            # get_or_create("极限") → 已存在 kp id=2
            r = MagicMock()
            kp2 = _make_kp(id=2, name="极限")
            r.scalar_one_or_none.return_value = kp2
            return r

        db.execute = AsyncMock(side_effect=mock_execute)

        def _sync(names, points):
            with patch("app.services.question_revision_service.lock_question_for_revision", new=AsyncMock(return_value=q)), \
                 patch("app.services.knowledge_point_service.resolve_knowledge_points", new=AsyncMock(return_value=points)):
                return _run(sync_question_knowledge_points(db, q, names, source="admin", replace=True))

        # replace=[极限] → 删除 kp1（id=1 不在目标 {2}），保留/更新 kp2
        result = _sync(["极限"], [_make_kp(2, name="极限")])
        assert result["deleted"] == 1
        assert result["total"] == 1

        # replace=[] → 清空全部
        result = _sync([], [])
        assert result["deleted"] == 2
        assert result["created"] == 0

    def test_sync_none_is_noop(self):
        from app.services.knowledge_point_service import sync_question_knowledge_points

        db = _make_mock_db()
        q = _make_question(id=10, subject_id=1)
        result = _run(sync_question_knowledge_points(db, q, None, source="imported"))
        assert result["total"] == 0
        assert result["changed"] is False

    def test_sync_empty_additive_noop(self):
        from app.services.knowledge_point_service import sync_question_knowledge_points

        db = _make_mock_db()
        q = _make_question(id=10, subject_id=1)

        async def mock_execute(query):
            text = str(query)
            if "FROM question_knowledge_points" in text:
                r = MagicMock()
                r.all.return_value = []
                return r
            r = MagicMock()
            r.scalar_one_or_none.return_value = None
            return r

        db.execute = AsyncMock(side_effect=mock_execute)
        with patch("app.services.question_revision_service.lock_question_for_revision", new=AsyncMock(return_value=q)), \
             patch("app.services.knowledge_point_service.resolve_knowledge_points", new=AsyncMock(return_value=[])):
            result = _run(sync_question_knowledge_points(db, q, [], source="imported", replace=False))
        assert result["total"] == 0
        assert result["created"] == 0

    def test_sync_dedups_by_normalized(self):
        from app.services.knowledge_point_service import sync_question_knowledge_points

        db = _make_mock_db()
        q = _make_question(id=10, subject_id=1)

        async def mock_execute(query):
            text = str(query)
            if "FROM question_knowledge_points" in text:
                r = MagicMock()
                r.all.return_value = []
                return r
            r = MagicMock()
            r.scalar_one_or_none.return_value = None
            return r

        db.execute = AsyncMock(side_effect=mock_execute)
        with patch("app.services.question_revision_service.lock_question_for_revision", new=AsyncMock(return_value=q)), \
             patch("app.services.knowledge_point_service.resolve_knowledge_points", new=AsyncMock(return_value=[_make_kp(1), _make_kp(2)])):
            # 同一知识点以不同空白形式出现 → 去重为 1
            result = _run(sync_question_knowledge_points(
                db, q, ["  导数  ", "导数", "极限"], source="imported"))
        assert result["total"] == 2
        assert result["created"] == 2


# ── 3/4. V3 mastery primitives ──

class TestMasteryPrimitives:
    def test_zero_attempts_delta_is_correct_bonus(self):
        from app.services.mastery_service import compute_mastery_delta
        assert compute_mastery_delta(True) == 6.0
        assert compute_mastery_delta(False) == -12.0

    def test_difficulty_adjusts_delta(self):
        from app.services.mastery_service import compute_mastery_delta
        assert compute_mastery_delta(True, difficulty=4) == 9.0
        assert compute_mastery_delta(False, difficulty=2) == -16.0

    def test_consecutive_wrong_penalty(self):
        from app.services.mastery_service import compute_mastery_delta
        assert compute_mastery_delta(False, recent_wrong_count=2) == -15.0

    def test_score_clamped_0_to_100(self):
        from app.services.mastery_service import clamp_mastery_score
        assert clamp_mastery_score(-5) == 0.0
        assert clamp_mastery_score(120) == 100.0

    def test_confidence_caps_at_one(self):
        from app.services.mastery_service import compute_confidence
        assert compute_confidence(0) == 0.0
        assert compute_confidence(10) == 1.0

    def test_low_confidence_label_does_not_overjudge(self):
        from app.services.mastery_service import get_mastery_label
        assert get_mastery_label(30.0, 0.1) == "possible_weak"
        assert get_mastery_label(90.0, 0.1) == "possible_mastered"
        assert get_mastery_label(55.0, 0.1) == "observing"

    def test_confirmed_labels_follow_v3_thresholds(self):
        from app.services.mastery_service import get_mastery_label
        assert get_mastery_label(30.0, 0.5) == "weak"
        assert get_mastery_label(55.0, 0.5) == "normal"
        assert get_mastery_label(80.0, 0.5) == "good"
        assert get_mastery_label(90.0, 0.5) == "mastered"


# ── 5. update_user_knowledge_state_after_answer ──

class TestUpdateUserKnowledgeState:
    def test_correct_answer_increases_mastery(self):
        from app.services.mastery_service import (
            update_user_knowledge_state_after_answer,
        )

        db = _make_mock_db()
        kp = _make_kp(id=1, name="导数")
        qkp = _make_qkp(question_id=1, kp_id=1)

        # Mock sequence matching actual function flow:
        # 1st call: QKP join KP query → returns [(qkp, kp)]
        # 2nd call: Question.difficulty query → returns 2
        # 3rd call: UserKnowledgeState lookup → returns None (new state)
        call_count = [0]

        async def mock_execute(query):
            call_count[0] += 1
            if call_count[0] == 1:
                # QKP join KP query
                return _make_execute_result(all=[(qkp, kp)])
            elif call_count[0] == 2:
                # Question.difficulty query → scalar difficulty
                return _make_execute_result(scalar_one_or_none=2)
            elif call_count[0] == 3:
                # UserKnowledgeState lookup — no existing state
                return _make_execute_result(scalar_one_or_none=None)
            return _make_execute_result()

        db.execute = AsyncMock(side_effect=mock_execute)

        db.scalar = AsyncMock(return_value=2)
        result = _run(update_user_knowledge_state_after_answer(db, 1, 1, True, 11))
        assert result["created"] == 1
        assert result["updated"] == 1
        # Verify db.add was called (new state created)
        db.add.assert_called()

# ── 6. get_user_weak_knowledge_points ──

class TestGetUserWeakKnowledgePoints:
    def test_returns_weak_points_from_uks(self):
        from app.services.mastery_service import get_user_weak_knowledge_points

        db = _make_mock_db()
        uks = _make_uks(mastery=0.3, weakness="weak", attempt=5)

        db.execute = AsyncMock(return_value=_make_execute_result(all=[(uks, "导数")]))

        with patch("app.services.mastery_service.resolve_subject_ids",
                   new_callable=AsyncMock, return_value=[1]):
            result = _run(get_user_weak_knowledge_points(db, 1, 1, limit=5))
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
            elif call_count[0] == 2:
                # PracticeRecord fallback → (is_correct, kp_id, kp_name)
                return _make_execute_result(all=[(False, 1, "导数"), (False, 1, "导数")])
            else:
                # load_question_kps → (question_id, kp.name) rows
                r = MagicMock()
                r.all.return_value = [(1, "导数"), (1, "极限")]
                return r

        db.execute = AsyncMock(side_effect=mock_execute)

        with patch("app.services.mastery_service.resolve_subject_ids",
                   new_callable=AsyncMock, return_value=[1]):
            result = _run(get_user_weak_knowledge_points(db, 1, 1, limit=5))
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
            {"question_id": 1, "subject_id": 1, "recommend_score": 0.9, "similarity": 0.85, "reason": "薄弱知识点"},
            {"question_id": 2, "subject_id": 1, "recommend_score": 0.7, "similarity": 0.6, "reason": "向量相似"},
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
    @staticmethod
    def _side_effect_once(questions):
        first = _make_execute_result(scalars=questions)
        empty = _make_execute_result(scalars=[])
        called = [False]
        def _side_effect(*a, **kw):
            if not called[0]:
                called[0] = True
                return first
            return empty
        return _side_effect

    @patch("app.services.practice_service.vector_retrieval_service", create=True)
    def test_smart_mode_uses_mastery_service(self, mock_vrs):
        """smart mode should try mastery_service first, fallback to _compute_weak_knowledge_points."""
        from app.services.practice_service import get_smart_practice_questions

        db = _make_mock_db()
        q1 = _make_question(1, knowledge_points=["导数"])

        # Mock vector recall to raise (simulating vector unavailable)
        mock_vrs.vector_recall_by_text = AsyncMock(side_effect=Exception("vector disabled"))

        # Mock db.execute: return questions for the kp-filter fallback query
        db.execute = AsyncMock(return_value=_make_execute_result(scalars=[q1], scalar=0))

        mock_ms = MagicMock()
        mock_ms.get_user_weak_knowledge_points = AsyncMock(return_value=[
            {"name": "导数", "mastery_score": 0.3, "accuracy": 0.3, "attempt_count": 5, "weakness_level": "weak"}
        ])
        mock_rls = MagicMock()
        mock_rls.create_recommendation_logs_isolated = AsyncMock(return_value=[1])

        # Patch at the app.services package attribute level so `from app.services import X` picks up the mock
        with patch("app.services.mastery_service", mock_ms, create=True), \
             patch("app.services.recommendation_log_service", mock_rls, create=True), \
             patch("app.services.practice_service.resolve_subject_ids",
                   new_callable=AsyncMock, return_value=[1]), \
             patch("app.services.recommendation_experiment_service.resolve_strategy_for_user",
                   new_callable=AsyncMock, return_value={"source": "default"}):
            result = _run(get_smart_practice_questions(
                db, user_id=1, subject_code="math2", count=5, request_id="test-req-1",
            ))

            questions, metadata = result
            # Verify mastery_service was called
            mock_ms.get_user_weak_knowledge_points.assert_called_once()
            # Verify we got questions back
            assert len(questions) >= 1
            # Verify recommendation log service was called with request_id
            mock_rls.create_recommendation_logs_isolated.assert_called_once()
            call_kwargs = mock_rls.create_recommendation_logs_isolated.call_args[1]
            assert call_kwargs.get("request_id") == "test-req-1"

    def test_random_mode_not_affected(self):
        """random mode should work exactly as before."""
        from app.services.practice_service import get_practice_questions

        db = _make_mock_db()
        q1 = _make_question(1)
        db.execute.side_effect = self._side_effect_once([q1])

        with patch("app.services.practice_service.resolve_subject_ids",
                   new_callable=AsyncMock, return_value=[1]):
            result = _run(get_practice_questions(db, user_id=1, subject_code="math2", count=5, mode="random"))
        assert len(result) == 1
        assert result[0].id == 1

    def test_sequential_mode_not_affected(self):
        """sequential mode should work exactly as before."""
        import app.services.practice_service as practice_service
        from app.services.practice_service import get_practice_questions

        db = _make_mock_db()
        q1, q2 = _make_question(1), _make_question(2)

        with patch("app.services.practice_service.resolve_subject_ids",
                   new_callable=AsyncMock, return_value=[1]), patch.object(
            practice_service,
            "get_sequential_practice_questions",
            new=AsyncMock(return_value=([q1, q2], {"reserved": 2})),
        ):
            result = _run(get_practice_questions(db, user_id=1, subject_code="math2", count=5, mode="sequential"))
        assert len(result) == 2


# ── 9. answer projection feedback loop ──

# The legacy synchronous ``submit_answer`` entry point was replaced by signed
# batch submission plus answer projections; API-level feedback behavior is
# covered by practice batch and projection integration tests.
