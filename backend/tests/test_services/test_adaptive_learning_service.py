"""V6 adaptive_learning_service 单元测试。

覆盖场景：
1. calculate_personalized_interval_days 纯函数
2. get_difficulty_factor / get_difficulty_label
3. update_user_interval_factor: 到期答错 → factor 下降
4. update_user_interval_factor: 到期答对 → factor 上升
5. update_user_interval_factor: 逾期答对 → factor 更大上升
6. interval_factor 不超过 [0.6, 1.6] 范围
7. update_question_difficulty_state: 答对 → 分数下降
8. update_question_difficulty_state: 答错 → 分数上升
9. update_question_difficulty_state: 耗时修正
10. feature flag 关闭时 update_adaptive_state_after_answer 不执行
"""
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.adaptive_learning_service import (
    _clamp,
    calculate_personalized_interval_days,
    get_difficulty_factor,
    get_difficulty_label,
    get_blocked_knowledge_points,
    can_recommend_advanced_knowledge,
    default_weights,
    get_recommend_weights,
    _adjust_weight,
    update_user_interval_factor,
    update_question_difficulty_state,
    update_adaptive_state_after_answer,
)


def _run(coro):
    return asyncio.run(coro)


# ── Mock helpers ─────────────────────────────────────────────────────


class MockRow:
    def __init__(self, **kwargs):
        self._d = kwargs

    def __getitem__(self, idx):
        return list(self._d.values())[idx]

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return self._d[name]
        except KeyError:
            raise AttributeError(name)


class MockProfile:
    """模拟 UserAdaptiveProfile ORM 对象，支持属性读写。"""
    def __init__(self, interval_factor=1.0, min_factor=0.6, max_factor=1.6,
                 target_recall=0.8, due_count=0, due_correct=0):
        self.interval_factor = interval_factor
        self.min_interval_factor = min_factor
        self.max_interval_factor = max_factor
        self.target_recall_rate = target_recall
        self.recent_due_count = due_count
        self.recent_due_correct_count = due_correct
        self.last_adjusted_at = None


class MockDifficulty:
    """模拟 UserQuestionDifficultyState ORM 对象。"""
    def __init__(self, score=50.0, label="normal", answer_count=0,
                 correct_count=0, wrong_count=0, avg_time=None,
                 fast_correct=0, slow_correct=0, slow_wrong=0, overdue_wrong=0):
        self.personal_difficulty_score = score
        self.difficulty_label = label
        self.answer_count = answer_count
        self.correct_count = correct_count
        self.wrong_count = wrong_count
        self.avg_answer_time_seconds = avg_time
        self.fast_correct_count = fast_correct
        self.slow_correct_count = slow_correct
        self.slow_wrong_count = slow_wrong
        self.overdue_wrong_count = overdue_wrong
        self.last_updated_at = None


def _mock_result(*, one_val=None, scalar_val=None, all_vals=None, scalar_one_or_none_val=None):
    m = MagicMock()
    if one_val is not None:
        m.one.return_value = one_val
    if scalar_val is not None:
        m.scalar_one.return_value = scalar_val
    if all_vals is not None:
        m.all.return_value = all_vals
    if scalar_one_or_none_val is not None:
        m.scalar_one_or_none.return_value = scalar_one_or_none_val
    return m


def _make_db(side_effects):
    db = MagicMock()
    db.execute = AsyncMock(side_effect=side_effects)
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


# ── 纯函数测试 ──────────────────────────────────────────────────────


class TestPureFunctions:
    def test_clamp(self):
        assert _clamp(0.5, 0.0, 1.0) == 0.5
        assert _clamp(-1.0, 0.0, 1.0) == 0.0
        assert _clamp(2.0, 0.0, 1.0) == 1.0

    def test_calculate_interval_default(self):
        """所有倍率为 1.0 时，返回基础间隔。"""
        assert calculate_personalized_interval_days(14) == 14

    def test_calculate_interval_with_factors(self):
        """14 * 0.9 * 0.95 * 0.75 = 8.9775 → 9"""
        result = calculate_personalized_interval_days(
            base_interval_days=14,
            user_interval_factor=0.9,
            knowledge_interval_factor=0.95,
            difficulty_factor=0.75,
        )
        assert result == 9

    def test_calculate_interval_clamped_min(self):
        """极小值被 clamp 到 min_days=1。"""
        assert calculate_personalized_interval_days(
            base_interval_days=1,
            user_interval_factor=0.6,
            knowledge_interval_factor=0.6,
            difficulty_factor=0.75,
        ) == 1  # 1 * 0.6 * 0.6 * 0.75 = 0.27 → clamped to 1

    def test_calculate_interval_clamped_max(self):
        """极大值被 clamp 到 max_days=180。"""
        assert calculate_personalized_interval_days(
            base_interval_days=60,
            user_interval_factor=1.6,
            knowledge_interval_factor=1.6,
            difficulty_factor=1.15,
            max_days=180,
        ) == 177  # 60 * 1.6 * 1.6 * 1.15 = 176.64 → 177

    def test_difficulty_factor(self):
        assert get_difficulty_factor("easy") == 1.15
        assert get_difficulty_factor("hard") == 0.75
        assert get_difficulty_factor("normal") == 1.0
        assert get_difficulty_factor("unknown") == 1.0

    def test_difficulty_label(self):
        assert get_difficulty_label(20) == "easy"
        assert get_difficulty_label(50) == "normal"
        assert get_difficulty_label(80) == "hard"
        assert get_difficulty_label(0) == "easy"
        assert get_difficulty_label(100) == "hard"


# ── V6.1: 用户间隔倍率更新 ──────────────────────────────────────────


class TestUpdateUserIntervalFactor:
    def test_due_wrong_decreases_factor(self):
        """场景 3：到期答错，interval_factor 下降 8%。"""
        profile = MockProfile(interval_factor=1.0)
        db = _make_db([
            _mock_result(scalar_one_or_none_val=profile),
        ])

        result = _run(update_user_interval_factor(
            db, user_id=1, is_due_review=True,
            is_correct=False, is_overdue_review=False,
        ))

        assert result == pytest.approx(0.92, abs=0.001)
        assert profile.interval_factor == pytest.approx(0.92, abs=0.001)

    def test_due_correct_increases_factor(self):
        """场景 2：到期答对，interval_factor 上升 4%。"""
        profile = MockProfile(interval_factor=1.0)
        db = _make_db([
            _mock_result(scalar_one_or_none_val=profile),
        ])

        result = _run(update_user_interval_factor(
            db, user_id=1, is_due_review=True,
            is_correct=True, is_overdue_review=False,
        ))

        assert result == pytest.approx(1.04, abs=0.001)

    def test_overdue_correct_increases_more(self):
        """场景 5：逾期答对，interval_factor 上升 8%（比正常答对更多）。"""
        profile = MockProfile(interval_factor=1.0)
        db = _make_db([
            _mock_result(scalar_one_or_none_val=profile),
        ])

        result = _run(update_user_interval_factor(
            db, user_id=1, is_due_review=True,
            is_correct=True, is_overdue_review=True,
        ))

        assert result == pytest.approx(1.08, abs=0.001)

    def test_factor_clamped_min(self):
        """场景 3 续：factor 不会低于 min_interval_factor=0.6。"""
        profile = MockProfile(interval_factor=0.62, min_factor=0.6)
        db = _make_db([
            _mock_result(scalar_one_or_none_val=profile),
        ])

        result = _run(update_user_interval_factor(
            db, user_id=1, is_due_review=True,
            is_correct=False, is_overdue_review=False,
        ))

        # 0.62 * 0.92 = 0.5704 → clamped to 0.6
        assert result == pytest.approx(0.6, abs=0.001)

    def test_factor_clamped_max(self):
        """factor 不会超过 max_interval_factor=1.6。"""
        profile = MockProfile(interval_factor=1.55, max_factor=1.6)
        db = _make_db([
            _mock_result(scalar_one_or_none_val=profile),
        ])

        result = _run(update_user_interval_factor(
            db, user_id=1, is_due_review=True,
            is_correct=True, is_overdue_review=True,
        ))

        # 1.55 * 1.08 = 1.674 → clamped to 1.6
        assert result == pytest.approx(1.6, abs=0.001)

    def test_not_due_review_no_change(self):
        """非到期复习不调整 factor。"""
        profile = MockProfile(interval_factor=1.0)
        db = _make_db([
            _mock_result(scalar_one_or_none_val=profile),
        ])

        result = _run(update_user_interval_factor(
            db, user_id=1, is_due_review=False,
            is_correct=False, is_overdue_review=False,
        ))

        assert result == pytest.approx(1.0, abs=0.001)
        assert profile.interval_factor == pytest.approx(1.0, abs=0.001)


# ── V6.2: 题目难度校准 ───────────────────────────────────────────────


class TestUpdateQuestionDifficulty:
    def test_correct_decreases_score(self):
        """场景 6：答对 → 分数下降 4。"""
        diff = MockDifficulty(score=50.0)
        db = _make_db([
            _mock_result(scalar_one_or_none_val=diff),
        ])

        result = _run(update_question_difficulty_state(
            db, user_id=1, question_id=1,
            is_correct=True, answer_time_seconds=60,
            expected_time_seconds=60, is_overdue_review=False,
        ))

        assert result.personal_difficulty_score == 46.0
        assert result.difficulty_label == "normal"
        assert result.answer_count == 1
        assert result.correct_count == 1

    def test_wrong_increases_score(self):
        """答错 → 分数上升 8。"""
        diff = MockDifficulty(score=50.0)
        db = _make_db([
            _mock_result(scalar_one_or_none_val=diff),
        ])

        result = _run(update_question_difficulty_state(
            db, user_id=1, question_id=1,
            is_correct=False, answer_time_seconds=60,
            expected_time_seconds=60, is_overdue_review=False,
        ))

        assert result.personal_difficulty_score == 58.0
        assert result.wrong_count == 1

    def test_slow_correct_extra_penalty(self):
        """答对但耗时 > 1.5x 期望 → 额外 +3。"""
        diff = MockDifficulty(score=50.0)
        db = _make_db([
            _mock_result(scalar_one_or_none_val=diff),
        ])

        result = _run(update_question_difficulty_state(
            db, user_id=1, question_id=1,
            is_correct=True, answer_time_seconds=120,
            expected_time_seconds=60, is_overdue_review=False,
        ))

        # -4 (correct) + 3 (slow) = -1
        assert result.personal_difficulty_score == 49.0
        assert result.slow_correct_count == 1

    def test_fast_correct_bonus(self):
        """快速答对（< 0.6x 期望）→ 额外 -3。"""
        diff = MockDifficulty(score=50.0)
        db = _make_db([
            _mock_result(scalar_one_or_none_val=diff),
        ])

        result = _run(update_question_difficulty_state(
            db, user_id=1, question_id=1,
            is_correct=True, answer_time_seconds=20,
            expected_time_seconds=60, is_overdue_review=False,
        ))

        # -4 (correct) - 3 (fast) = -7
        assert result.personal_difficulty_score == 43.0
        assert result.fast_correct_count == 1

    def test_overdue_wrong_extra_penalty(self):
        """逾期答错 → 额外 +5。"""
        diff = MockDifficulty(score=50.0)
        db = _make_db([
            _mock_result(scalar_one_or_none_val=diff),
        ])

        result = _run(update_question_difficulty_state(
            db, user_id=1, question_id=1,
            is_correct=False, answer_time_seconds=60,
            expected_time_seconds=60, is_overdue_review=True,
        ))

        # +8 (wrong) + 5 (overdue wrong) = +13
        assert result.personal_difficulty_score == 63.0
        assert result.overdue_wrong_count == 1

    def test_score_clamped(self):
        """分数不会超出 [0, 100] 范围。"""
        diff = MockDifficulty(score=2.0)
        db = _make_db([
            _mock_result(scalar_one_or_none_val=diff),
        ])

        result = _run(update_question_difficulty_state(
            db, user_id=1, question_id=1,
            is_correct=True, answer_time_seconds=10,
            expected_time_seconds=60, is_overdue_review=False,
        ))

        # 2.0 - 4 - 3 = -5 → clamped to 0
        assert result.personal_difficulty_score == 0.0
        assert result.difficulty_label == "easy"

    def test_label_transitions(self):
        """分数跨越阈值时标签正确更新。"""
        diff = MockDifficulty(score=72.0, label="hard")
        db = _make_db([
            _mock_result(scalar_one_or_none_val=diff),
        ])

        result = _run(update_question_difficulty_state(
            db, user_id=1, question_id=1,
            is_correct=True, answer_time_seconds=30,
            expected_time_seconds=60, is_overdue_review=False,
        ))

        # 72 - 4 - 3 = 65 → "normal"
        assert result.personal_difficulty_score == 65.0
        assert result.difficulty_label == "normal"


# ── Feature Flag 测试 ───────────────────────────────────────────────


class TestFeatureFlag:
    @patch("app.services.adaptive_learning_service.settings")
    def test_disabled_skips_all(self, mock_settings):
        """场景 9：ADAPTIVE_LEARNING_ENABLED=False 时不执行任何操作。"""
        mock_settings.ADAPTIVE_LEARNING_ENABLED = False

        db = _make_db([])
        now = datetime.utcnow()

        _run(update_adaptive_state_after_answer(
            db, user_id=1, question_id=1,
            is_correct=True, answer_time_seconds=60,
            answered_at=now,
        ))

        # 不应有任何 DB 查询
        db.execute.assert_not_called()


# ── V6.3: 知识点路径推荐 ─────────────────────────────────────────────


class TestCanRecommendAdvanced:
    def test_no_prerequisites_returns_true(self):
        """没有前置知识点时，可以推荐。"""
        assert can_recommend_advanced_knowledge([]) is True

    def test_weak_prerequisite_blocks(self):
        """前置知识点薄弱（mastery < 60, confidence >= 0.3）→ 不可推荐。"""
        prereqs = [{"mastery_score": 45.0, "confidence": 0.8}]
        assert can_recommend_advanced_knowledge(prereqs) is False

    def test_mastered_prerequisite_allows(self):
        """前置知识点已掌握（mastery >= 60）→ 可以推荐。"""
        prereqs = [{"mastery_score": 75.0, "confidence": 0.9}]
        assert can_recommend_advanced_knowledge(prereqs) is True

    def test_low_confidence_allows(self):
        """前置知识点数据不足（confidence < 0.3）→ 不阻塞。"""
        prereqs = [{"mastery_score": 30.0, "confidence": 0.1}]
        assert can_recommend_advanced_knowledge(prereqs) is True

    def test_mixed_prerequisites(self):
        """多个前置中任一薄弱 → 阻塞。"""
        prereqs = [
            {"mastery_score": 80.0, "confidence": 0.9},
            {"mastery_score": 40.0, "confidence": 0.5},
        ]
        assert can_recommend_advanced_knowledge(prereqs) is False


class TestGetBlockedKnowledgePoints:
    def test_empty_kp_ids(self):
        """空输入返回空字典。"""
        db = _make_db([])
        result = _run(get_blocked_knowledge_points(db, user_id=1, kp_ids=[], subject="math"))
        assert result == {}

    def test_no_prerequisite_edges(self):
        """没有前置边 → 返回空字典。"""
        db = _make_db([
            _mock_result(all_vals=[]),  # edges query returns empty
        ])
        result = _run(get_blocked_knowledge_points(
            db, user_id=1, kp_ids=[10, 20], subject="math",
        ))
        assert result == {}

    def test_blocked_prerequisite_detected(self):
        """前置知识点 mastery=35, confidence=0.8 → 被标记为薄弱。"""
        db = _make_db([
            # 1. edges query: KP 20 has prerequisite KP 10
            _mock_result(all_vals=[
                MockRow(target_knowledge_point_id=20, source_knowledge_point_id=10),
            ]),
            # 2. mastery query: KP 10 mastery=35, confidence=0.8
            _mock_result(all_vals=[
                MockRow(knowledge_point_id=10, mastery_score=35.0, confidence=0.8),
            ]),
            # 3. name query: KP 10 name="基础概念"
            _mock_result(all_vals=[
                MockRow(id=10, name="基础概念"),
            ]),
        ])

        result = _run(get_blocked_knowledge_points(
            db, user_id=1, kp_ids=[20], subject="math",
        ))

        assert 20 in result
        assert len(result[20]) == 1
        assert result[20][0]["knowledge_point_id"] == 10
        assert result[20][0]["name"] == "基础概念"
        assert result[20][0]["mastery_score"] == 35.0

    def test_mastered_prerequisite_not_blocked(self):
        """前置知识点 mastery=80, confidence=0.9 → 不阻塞。"""
        db = _make_db([
            _mock_result(all_vals=[
                MockRow(target_knowledge_point_id=20, source_knowledge_point_id=10),
            ]),
            _mock_result(all_vals=[
                MockRow(knowledge_point_id=10, mastery_score=80.0, confidence=0.9),
            ]),
            _mock_result(all_vals=[
                MockRow(id=10, name="基础概念"),
            ]),
        ])

        result = _run(get_blocked_knowledge_points(
            db, user_id=1, kp_ids=[20], subject="math",
        ))

        assert result == {}  # KP 20 不在 blocked 中


class TestSmartScorePathDimensions:
    """测试 calculate_smart_score 的 path_blocked 和 path_unlock 维度。"""

    def _make_question(self, q_id=1):
        q = MagicMock()
        q.id = q_id
        q.next_review_at = None
        q.last_answered_at = None
        q.wrong_count = 0
        q.answer_count = 1
        return q

    def test_path_blocked_reduces_score(self):
        """前置薄弱 → 分数降低 25。"""
        from app.services.practice_service import calculate_smart_score
        q = self._make_question()
        kp_ids = [20]
        kp_mastery = {20: (50.0, 0.5)}  # KP 20 本身 mastery=50
        blocked_kps = {20: [{"knowledge_point_id": 10, "name": "基础", "mastery_score": 35.0}]}

        score_blocked, reasons_blocked = calculate_smart_score(
            q, None, kp_ids, kp_mastery, set(), datetime.utcnow(),
            blocked_kps=blocked_kps,
        )
        score_no_block, reasons_no_block = calculate_smart_score(
            q, None, kp_ids, kp_mastery, set(), datetime.utcnow(),
            blocked_kps={},
        )

        assert score_blocked < score_no_block
        assert "weak_prerequisite" in reasons_blocked
        assert "weak_prerequisite" not in reasons_no_block

    def test_path_unlock_increases_score(self):
        """前置已掌握且当前 KP 薄弱 → 分数提升 15。"""
        from app.services.practice_service import calculate_smart_score
        q = self._make_question()
        kp_ids = [20]
        kp_mastery = {20: (45.0, 0.5)}  # KP 20 薄弱
        # blocked_kps 不包含 KP 20（前置已掌握）
        blocked_kps = {}  # 空 = 没有阻塞

        score, reasons = calculate_smart_score(
            q, None, kp_ids, kp_mastery, set(), datetime.utcnow(),
            blocked_kps=blocked_kps,
        )

        assert "path_unlock" in reasons

    def test_no_path_effect_without_blocked_kps(self):
        """blocked_kps=None 时路径维度不生效。"""
        from app.services.practice_service import calculate_smart_score
        q = self._make_question()
        kp_ids = [20]
        kp_mastery = {20: (45.0, 0.5)}

        score, reasons = calculate_smart_score(
            q, None, kp_ids, kp_mastery, set(), datetime.utcnow(),
            blocked_kps=None,
        )

        assert "weak_prerequisite" not in reasons
        assert "path_unlock" not in reasons


# ── V6.4: 推荐权重个性化 ─────────────────────────────────────────────


class TestDefaultWeights:
    def test_returns_all_ones(self):
        w = default_weights()
        assert w["due_weight"] == 1.0
        assert w["weakness_weight"] == 1.0
        assert w["wrong_weight"] == 1.0
        assert w["new_question_weight"] == 1.0
        assert w["diversity_weight"] == 1.0
        assert w["path_weight"] == 1.0

    def test_returns_copy(self):
        """修改返回值不影响内部默认。"""
        w = default_weights()
        w["due_weight"] = 999
        assert default_weights()["due_weight"] == 1.0


class TestAdjustWeight:
    def test_increase(self):
        assert _adjust_weight(1.0, 1) == pytest.approx(1.05, abs=0.001)

    def test_decrease(self):
        assert _adjust_weight(1.0, -1) == pytest.approx(0.95, abs=0.001)

    def test_clamped_max(self):
        assert _adjust_weight(1.29, 1) == pytest.approx(1.3, abs=0.001)

    def test_clamped_min(self):
        assert _adjust_weight(0.71, -1) == pytest.approx(0.7, abs=0.001)


class TestGetRecommendWeights:
    @patch("app.services.adaptive_learning_service.settings")
    def test_no_preference_returns_defaults(self, mock_settings):
        mock_settings.ADAPTIVE_LEARNING_ENABLED = True
        mock_settings.ADAPTIVE_WEIGHT_ENABLED = True

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db = MagicMock()
        db.execute = AsyncMock(return_value=mock_result)

        result = _run(get_recommend_weights(db, user_id=1))
        assert result == default_weights()

    @patch("app.services.adaptive_learning_service.settings")
    def test_disabled_returns_defaults(self, mock_settings):
        mock_settings.ADAPTIVE_LEARNING_ENABLED = False
        mock_settings.ADAPTIVE_WEIGHT_ENABLED = True

        db = _make_db([])
        result = _run(get_recommend_weights(db, user_id=1))
        assert result == default_weights()
        db.execute.assert_not_called()

    @patch("app.services.adaptive_learning_service.settings")
    def test_with_preference(self, mock_settings):
        mock_settings.ADAPTIVE_LEARNING_ENABLED = True
        mock_settings.ADAPTIVE_WEIGHT_ENABLED = True

        pref = MagicMock()
        pref.due_weight = 1.2
        pref.weakness_weight = 0.8
        pref.wrong_weight = 1.0
        pref.new_question_weight = 1.1
        pref.diversity_weight = 0.9
        pref.difficulty_weight = 1.0
        pref.path_weight = 1.05

        db = _make_db([
            _mock_result(scalar_one_or_none_val=pref),
        ])

        result = _run(get_recommend_weights(db, user_id=1))
        assert result["due_weight"] == 1.2
        assert result["weakness_weight"] == 0.8
        assert result["path_weight"] == 1.05


class TestSmartScoreWithWeights:
    """测试 calculate_smart_score 的 V6.4 权重应用。"""

    def _make_question(self):
        q = MagicMock()
        q.id = 1
        q.next_review_at = None
        q.last_answered_at = None
        q.wrong_count = 0
        q.answer_count = 0  # 新题
        return q

    def test_weights_scale_scores(self):
        """due_weight=2.0 时，到期分数翻倍。"""
        from app.services.practice_service import calculate_smart_score
        q = self._make_question()
        q.next_review_at = datetime.utcnow() - timedelta(hours=1)  # 到期

        # 无权重
        score_default, _ = calculate_smart_score(
            q, q, [], {}, set(), datetime.utcnow(),
        )

        # due_weight=2.0
        weights = default_weights()
        weights["due_weight"] = 2.0
        score_weighted, _ = calculate_smart_score(
            q, q, [], {}, set(), datetime.utcnow(), weights=weights,
        )

        # 到期基础分 40，default 总分 = 40 + 20(new) = 60
        # weighted 总分 = 40*2 + 20*1 = 100
        assert score_weighted > score_default
        assert score_weighted == pytest.approx(100.0, abs=1.0)

    def test_none_weights_same_as_default(self):
        """weights=None 与默认权重结果一致。"""
        from app.services.practice_service import calculate_smart_score
        q = self._make_question()

        score_none, reasons_none = calculate_smart_score(
            q, None, [1], {1: (50.0, 0.5)}, set(), datetime.utcnow(),
            weights=None,
        )
        score_default, reasons_default = calculate_smart_score(
            q, None, [1], {1: (50.0, 0.5)}, set(), datetime.utcnow(),
            weights=default_weights(),
        )

        assert score_none == pytest.approx(score_default, abs=0.01)
