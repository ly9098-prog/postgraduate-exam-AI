"""Pure-function compatibility baseline for knowledge diagnosis ranking logic.

Pins the canonical type coercion, accuracy/days-since helpers, chapter-kind
classification, priority scoring, scope coverage, empty stat shape, and
multi-target session attribution in ``knowledge_diagnosis_logic`` so future
refactors of recommendation ranking cannot silently change coverage gating,
priority weights, recommendation copy, ancestor-overlap detection, or session
aggregation semantics.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.services.knowledge_diagnosis_logic import (
    _accuracy,
    _chapter_kind,
    _days_since,
    _empty_chapter_stat,
    _float,
    _int,
    _overlaps,
    _priority_score,
    _recommendation_copy,
    _scope_coverage,
    aggregate_session_stats,
)

NOW = datetime(2026, 8, 16, 12, 0, 0)


class TestInt:
    def test_int_value_returned(self):
        assert _int(5) == 5
        assert _int("5") == 5

    def test_float_value_truncated(self):
        assert _int(3.99) == 3
        # int("3.99") raises ValueError -> returns default (0), NOT truncation.
        assert _int("3.99") == 0

    def test_invalid_string_returns_default(self):
        assert _int("abc") == 0
        assert _int("abc", default=7) == 7

    def test_none_returns_default(self):
        assert _int(None) == 0
        assert _int(None, default=9) == 9

    def test_list_returns_default(self):
        assert _int([1, 2]) == 0

    def test_dict_returns_default(self):
        assert _int({"a": 1}) == 0

    def test_bool_int_value(self):
        # bool is a subclass of int; int(True) == 1, int(False) == 0
        assert _int(True) == 1
        assert _int(False) == 0


class TestFloat:
    def test_float_value_returned(self):
        assert _float(1.5) == 1.5
        assert _float("1.5") == 1.5

    def test_int_value_promoted(self):
        assert _float(3) == 3.0

    def test_invalid_string_returns_default(self):
        assert _float("abc") == 0.0
        assert _float("abc", default=2.5) == 2.5

    def test_none_returns_default(self):
        assert _float(None) == 0.0
        assert _float(None, default=9.5) == 9.5

    def test_list_returns_default(self):
        assert _float([1.0]) == 0.0

    def test_bool_float_value(self):
        # bool is a subclass of int; float(True) == 1.0
        assert _float(True) == 1.0


class TestAccuracy:
    def test_total_zero_returns_none(self):
        assert _accuracy(0, 0) is None
        assert _accuracy(5, 0) is None

    def test_total_negative_returns_none(self):
        assert _accuracy(0, -1) is None
        assert _accuracy(5, -5) is None

    def test_perfect_accuracy(self):
        assert _accuracy(10, 10) == 1.0

    def test_thirds_rounded_to_4_places(self):
        # 1/3 = 0.3333... -> round to 0.3333
        assert _accuracy(1, 3) == 0.3333

        # 2/3 = 0.6666... -> round to 0.6667
        assert _accuracy(2, 3) == 0.6667

    def test_correct_greater_than_total_returns_gt_one(self):
        # No clamp; the function does not cap correct at total.
        assert _accuracy(15, 10) == 1.5

    def test_negative_correct_returns_negative_accuracy(self):
        # No clamp on correct either.
        assert _accuracy(-5, 10) == -0.5


class TestDaysSince:
    def test_none_returns_none(self):
        assert _days_since(None, now=NOW) is None

    def test_zero_seconds_ago_returns_zero(self):
        assert _days_since(NOW, now=NOW) == 0

    def test_one_day_ago(self):
        past = NOW - timedelta(days=1)
        assert _days_since(past, now=NOW) == 1

    def test_just_under_one_day(self):
        # 23h59m ago -> 0 full days -> 0
        past = NOW - timedelta(hours=23, minutes=59)
        assert _days_since(past, now=NOW) == 0

    def test_future_returns_zero(self):
        # max(0, ...) clamps future values to zero.
        future = NOW + timedelta(days=2)
        assert _days_since(future, now=NOW) == 0

    def test_uses_floor_of_seconds(self):
        # 1.5 days -> floor of 1 (1*86400 = 86400s; 1.5d = 129600s -> //86400 = 1)
        past = NOW - timedelta(days=1, hours=12)
        assert _days_since(past, now=NOW) == 1

    def test_partial_seconds_floor(self):
        # 23h59m59s ago -> 86399 seconds -> 86399//86400 = 0 full days
        past = NOW - timedelta(hours=23, minutes=59, seconds=59)
        assert _days_since(past, now=NOW) == 0


class TestChapterKind:
    def _node(self, **kwargs):
        base = {
            "subtree_status": "no_data",
            "subtree_coverage_ratio": 0.0,
            "subtree_reliable_knowledge_points": 0,
            "subtree_weak_knowledge_points": 0,
            "subtree_mastery_score": None,
        }
        base.update(kwargs)
        return base

    def test_no_data_status_returns_build(self):
        node = self._node(subtree_status="no_data", subtree_reliable_knowledge_points=10)
        assert _chapter_kind(node, {}, now=NOW) == "build"

    def test_insufficient_status_returns_build(self):
        node = self._node(
            subtree_status="insufficient", subtree_reliable_knowledge_points=10
        )
        assert _chapter_kind(node, {}, now=NOW) == "build"

    def test_coverage_below_threshold_returns_build(self):
        node = self._node(
            subtree_status="ok",
            subtree_coverage_ratio=0.34,
            subtree_reliable_knowledge_points=10,
        )
        assert _chapter_kind(node, {}, now=NOW) == "build"

    def test_coverage_exactly_threshold_returns_non_build(self):
        # threshold is "< 0.35"; 0.35 does not trigger build
        node = self._node(
            subtree_status="ok",
            subtree_coverage_ratio=0.35,
            subtree_reliable_knowledge_points=10,
        )
        assert _chapter_kind(node, {}, now=NOW) != "build"

    def test_reliable_zero_returns_build(self):
        node = self._node(
            subtree_status="ok",
            subtree_coverage_ratio=0.9,
            subtree_reliable_knowledge_points=0,
        )
        assert _chapter_kind(node, {}, now=NOW) == "build"

    def test_weak_knowledge_points_positive_returns_strengthen(self):
        node = self._node(
            subtree_status="ok",
            subtree_coverage_ratio=0.9,
            subtree_reliable_knowledge_points=10,
            subtree_weak_knowledge_points=2,
        )
        assert _chapter_kind(node, {}, now=NOW) == "strengthen"

    def test_mastery_below_threshold_returns_strengthen(self):
        node = self._node(
            subtree_status="ok",
            subtree_coverage_ratio=0.9,
            subtree_reliable_knowledge_points=10,
            subtree_weak_knowledge_points=0,
            subtree_mastery_score=64.0,
        )
        assert _chapter_kind(node, {}, now=NOW) == "strengthen"

    def test_mastery_exactly_threshold_does_not_strengthen(self):
        # "<65.0" so 65.0 does not trigger strengthen
        node = self._node(
            subtree_status="ok",
            subtree_coverage_ratio=0.9,
            subtree_reliable_knowledge_points=10,
            subtree_weak_knowledge_points=0,
            subtree_mastery_score=65.0,
        )
        assert _chapter_kind(node, {}, now=NOW) != "strengthen"

    def test_days_gte_14_returns_review(self):
        node = self._node(
            subtree_status="ok",
            subtree_coverage_ratio=0.9,
            subtree_reliable_knowledge_points=10,
            subtree_weak_knowledge_points=0,
            subtree_mastery_score=80.0,
        )
        past = NOW - timedelta(days=14)
        assert _chapter_kind(node, {"last_practiced_at": past}, now=NOW) == "review"

    def test_days_below_14_returns_maintain(self):
        node = self._node(
            subtree_status="ok",
            subtree_coverage_ratio=0.9,
            subtree_reliable_knowledge_points=10,
            subtree_weak_knowledge_points=0,
            subtree_mastery_score=80.0,
        )
        past = NOW - timedelta(days=13)
        assert _chapter_kind(node, {"last_practiced_at": past}, now=NOW) == "maintain"

    def test_no_practice_record_returns_maintain(self):
        node = self._node(
            subtree_status="ok",
            subtree_coverage_ratio=0.9,
            subtree_reliable_knowledge_points=10,
            subtree_weak_knowledge_points=0,
            subtree_mastery_score=80.0,
        )
        assert _chapter_kind(node, {"last_practiced_at": None}, now=NOW) == "maintain"


class TestPriorityScore:
    def _node(self, **kwargs):
        base = {
            "subtree_status": "ok",
            "subtree_coverage_ratio": 1.0,
            "subtree_weak_knowledge_points": 0,
            "subtree_mastery_score": 100.0,
            "depth": 1,
        }
        base.update(kwargs)
        return base

    def test_low_coverage_adds_high_coverage_score(self):
        # coverage=0 -> (1-0)*30 = 30
        node = self._node(subtree_coverage_ratio=0.0)
        score = _priority_score(node, {}, now=NOW)
        assert score >= 30.0

    def test_full_coverage_no_coverage_score(self):
        node = self._node(subtree_coverage_ratio=1.0)
        score = _priority_score(node, {}, now=NOW)
        # coverage term is (1-1)*30 = 0
        assert score < 30.0

    def test_coverage_above_one_clamped_to_one(self):
        node = self._node(subtree_coverage_ratio=2.0)
        score_high = _priority_score(node, {}, now=NOW)
        node["subtree_coverage_ratio"] = 1.0
        score_full = _priority_score(node, {}, now=NOW)
        assert score_high == score_full

    def test_coverage_negative_clamped_to_zero(self):
        node = self._node(subtree_coverage_ratio=-1.0)
        score_neg = _priority_score(node, {}, now=NOW)
        node["subtree_coverage_ratio"] = 0.0
        score_zero = _priority_score(node, {}, now=NOW)
        assert score_neg == score_zero

    def test_weak_capped_at_five(self):
        # min(5, weak) * 5: weak=10 -> 5*5 = 25; weak=3 -> 3*5 = 15
        node_many = self._node(subtree_weak_knowledge_points=10)
        node_few = self._node(subtree_weak_knowledge_points=3)
        diff = _priority_score(node_many, {}, now=NOW) - _priority_score(
            node_few, {}, now=NOW
        )
        assert abs(diff - 10.0) < 0.01

    def test_mastery_none_adds_20(self):
        node_none = self._node(subtree_mastery_score=None)
        node_full = self._node(subtree_mastery_score=100.0)
        diff = _priority_score(node_none, {}, now=NOW) - _priority_score(
            node_full, {}, now=NOW
        )
        # mastery=100 -> max(0, 72-100)*0.75 = 0; mastery=None -> 20
        # diff = 20 - 0 = 20
        assert abs(diff - 20.0) < 0.01

    def test_status_no_data_adds_12(self):
        node_ok = self._node(subtree_status="ok")
        node_no = self._node(subtree_status="no_data")
        diff = _priority_score(node_no, {}, now=NOW) - _priority_score(
            node_ok, {}, now=NOW
        )
        assert abs(diff - 12.0) < 0.01

    def test_session_count_zero_adds_10(self):
        node = self._node()
        score_zero = _priority_score(node, {"session_count": 0}, now=NOW)
        score_one = _priority_score(node, {"session_count": 1}, now=NOW)
        # session_count <= 0 -> +10; session_count=1 falls through to days checks
        diff = score_zero - score_one
        assert abs(diff - 10.0) < 0.01

    def test_days_gte_21_adds_12(self):
        node = self._node()
        score_old = _priority_score(
            node, {"session_count": 1, "last_practiced_at": NOW - timedelta(days=21)},
            now=NOW,
        )
        score_recent = _priority_score(
            node, {"session_count": 1, "last_practiced_at": NOW - timedelta(days=10)},
            now=NOW,
        )
        # days>=21 -> +12; days=10 falls through to days<=2 check (false) -> 0
        diff = score_old - score_recent
        assert abs(diff - 12.0) < 0.01

    def test_days_gte_14_below_21_adds_8(self):
        node = self._node()
        score_mid = _priority_score(
            node, {"session_count": 1, "last_practiced_at": NOW - timedelta(days=14)},
            now=NOW,
        )
        score_recent = _priority_score(
            node, {"session_count": 1, "last_practiced_at": NOW - timedelta(days=10)},
            now=NOW,
        )
        diff = score_mid - score_recent
        assert abs(diff - 8.0) < 0.01

    def test_days_le_2_subtracts_8(self):
        node = self._node()
        score_recent = _priority_score(
            node, {"session_count": 1, "last_practiced_at": NOW - timedelta(days=1)},
            now=NOW,
        )
        score_mid = _priority_score(
            node, {"session_count": 1, "last_practiced_at": NOW - timedelta(days=10)},
            now=NOW,
        )
        # days<=2 -> -8; days=10 -> 0; BUT total is floored at 0 via max(0.0, score).
        # score_recent base (coverage0+weak0+mastery0+status0+session0+depth2) = 2,
        # minus 8 = -6 -> floored to 0. score_mid base = 2 (no days bonus) -> 2.
        # diff = 0 - 2 = -2.
        diff = score_recent - score_mid
        assert abs(diff - (-2.0)) < 0.01

    def test_depth_capped_at_two(self):
        # min(depth, 2) * 2.0
        node_d1 = self._node(depth=1)
        node_d5 = self._node(depth=5)
        diff = _priority_score(node_d5, {}, now=NOW) - _priority_score(
            node_d1, {}, now=NOW
        )
        assert abs(diff - 2.0) < 0.01

    def test_negative_total_score_clamped_to_zero(self):
        # Construct a node where recent practice + high mastery yields negative;
        # verify floor at 0.
        node = self._node(
            subtree_coverage_ratio=1.0,
            subtree_weak_knowledge_points=0,
            subtree_mastery_score=100.0,
            subtree_status="ok",
            depth=0,
        )
        stat = {
            "session_count": 5,
            "last_practiced_at": NOW - timedelta(days=1),
        }
        score = _priority_score(node, stat, now=NOW)
        assert score >= 0.0

    def test_score_rounded_to_two_decimals(self):
        node = self._node(subtree_coverage_ratio=0.333)
        score = _priority_score(node, {}, now=NOW)
        # Round happens at the end; check the score has at most 2 decimal places.
        assert round(score, 2) == score


class TestRecommendationCopy:
    def _node(self, **kwargs):
        base = {
            "name": "指令系统",
            "subtree_coverage_ratio": 0.9,
            "subtree_reliable_knowledge_points": 18,
            "subtree_trainable_knowledge_points": 20,
            "subtree_weak_knowledge_points": 0,
            "subtree_mastery_score": 80.0,
        }
        base.update(kwargs)
        return base

    def test_build_kind_copy(self):
        node = self._node(subtree_coverage_ratio=0.2, subtree_reliable_knowledge_points=4)
        title, body, cta = _recommendation_copy("build", node, {}, now=NOW)
        assert "建立" in title and "指令系统" in title
        assert "20%" in body  # round(0.2*100)
        assert "4/20" in body
        assert cta == "开始建立覆盖"

    def test_strengthen_kind_copy_with_weak(self):
        node = self._node(subtree_weak_knowledge_points=3)
        title, body, cta = _recommendation_copy("strengthen", node, {}, now=NOW)
        assert "强化" in title
        assert "3 个薄弱知识点" in body
        assert cta == "开始弱项强化"

    def test_strengthen_kind_copy_without_weak(self):
        node = self._node(subtree_weak_knowledge_points=0)
        title, body, cta = _recommendation_copy("strengthen", node, {}, now=NOW)
        assert "强化" in title
        assert "薄弱知识点" not in body

    def test_review_kind_copy_with_days(self):
        past = NOW - timedelta(days=20)
        node = self._node()
        title, body, cta = _recommendation_copy(
            "review", node, {"last_practiced_at": past}, now=NOW
        )
        assert "复习" in title
        assert "20 天" in body
        assert cta == "开始章节复习"

    def test_review_kind_copy_without_practice(self):
        node = self._node()
        title, body, cta = _recommendation_copy(
            "review", node, {"last_practiced_at": None}, now=NOW
        )
        assert "复习" in title
        assert "近期没有章节专项记录" in body

    def test_maintain_kind_copy(self):
        node = self._node()
        title, body, cta = _recommendation_copy("maintain", node, {}, now=NOW)
        assert "巩固" in title
        assert cta == "继续巩固"

    def test_unknown_kind_falls_back_to_maintain_copy(self):
        node = self._node()
        title, body, cta = _recommendation_copy("mystery", node, {}, now=NOW)
        assert "巩固" in title
        assert cta == "继续巩固"

    def test_mastery_none_renders_unreliable_text(self):
        node = self._node(subtree_mastery_score=None)
        _, body, _ = _recommendation_copy("maintain", node, {}, now=NOW)
        assert "尚未形成可靠判断" in body

    def test_mastery_rounded_to_int_percent(self):
        node = self._node(subtree_mastery_score=80.4)
        _, body, _ = _recommendation_copy("maintain", node, {}, now=NOW)
        assert "80%" in body

    def test_missing_name_uses_default(self):
        node = self._node()
        node.pop("name")
        title, _, _ = _recommendation_copy("maintain", node, {}, now=NOW)
        assert "知识章节" in title


class TestOverlaps:
    def _candidate(self, kp_id, ancestors=()):
        return {
            "knowledge_point_id": kp_id,
            "ancestor_ids": list(ancestors),
        }

    def test_candidate_ancestor_contains_selected_id(self):
        candidate = self._candidate(10, ancestors=[1, 2, 3])
        selected = self._candidate(3)
        assert _overlaps(candidate, selected) is True

    def test_candidate_id_in_selected_ancestors(self):
        candidate = self._candidate(10)
        selected = self._candidate(7, ancestors=[10])
        assert _overlaps(candidate, selected) is True

    def test_no_overlap(self):
        candidate = self._candidate(10, ancestors=[1, 2])
        selected = self._candidate(20, ancestors=[3, 4])
        assert _overlaps(candidate, selected) is False

    def test_zero_ids_no_overlap(self):
        # Both id=0; ancestors empty -> 0 in [] is False
        candidate = self._candidate(0)
        selected = self._candidate(0)
        assert _overlaps(candidate, selected) is False

    def test_candidate_id_zero_in_selected_ancestors(self):
        # 0 is a valid ancestor entry (ids filtered elsewhere); pin behavior.
        candidate = self._candidate(0)
        selected = self._candidate(7, ancestors=[0])
        assert _overlaps(candidate, selected) is True

    def test_missing_ancestor_ids_treated_as_empty(self):
        candidate = {"knowledge_point_id": 10}
        selected = {"knowledge_point_id": 20}
        assert _overlaps(candidate, selected) is False

    def test_none_ancestor_ids_treated_as_empty(self):
        candidate = {"knowledge_point_id": 10, "ancestor_ids": None}
        selected = {"knowledge_point_id": 20}
        assert _overlaps(candidate, selected) is False


class TestScopeCoverage:
    def test_resolved_zero_returns_none(self):
        assert _scope_coverage(0, 0) is None
        assert _scope_coverage(10, 0) is None

    def test_resolved_negative_returns_none(self):
        assert _scope_coverage(0, -1) is None

    def test_full_coverage(self):
        assert _scope_coverage(10, 10) == 1.0

    def test_half_coverage(self):
        assert _scope_coverage(5, 10) == 0.5

    def test_ratio_clamped_above_one(self):
        # served > resolved -> ratio > 1 -> clamped to 1.0
        assert _scope_coverage(15, 10) == 1.0

    def test_ratio_clamped_below_zero(self):
        # served negative -> max(0, ...) -> 0
        assert _scope_coverage(-5, 10) == 0.0

    def test_ratio_rounded_to_four_places(self):
        assert _scope_coverage(1, 3) == 0.3333
        assert _scope_coverage(2, 3) == 0.6667


class TestEmptyChapterStat:
    def test_returns_expected_shape(self):
        stat = _empty_chapter_stat()
        assert stat == {
            "session_count": 0,
            "recent_session_count": 0,
            "question_count": 0,
            "correct_count": 0,
            "last_practiced_at": None,
            "served_ids": set(),
            "resolved_ids": set(),
            "scope_served_count": 0,
            "scope_resolved_count": 0,
        }

    def test_returns_fresh_set_instances(self):
        # Each call must return independent sets so callers can mutate.
        stat1 = _empty_chapter_stat()
        stat2 = _empty_chapter_stat()
        stat1["served_ids"].add(1)
        stat1["resolved_ids"].add(99)
        assert stat2["served_ids"] == set()
        assert stat2["resolved_ids"] == set()


class TestAggregateSessionStats:
    def test_empty_inputs_return_empty_stats(self):
        stats, total = aggregate_session_stats([], [])
        assert stats == {}
        assert total == {
            "session_count": 0,
            "recent_session_count": 0,
            "question_count": 0,
            "correct_count": 0,
            "served_ids": set(),
            "resolved_ids": set(),
            "scope_served_count": 0,
            "scope_resolved_count": 0,
            "scope_coverage_ratio": None,
        }

    def test_single_session_attributes_to_root_only_when_no_ancestors(self):
        nodes = [{"knowledge_point_id": 5, "ancestor_ids": []}]
        sessions = [
            {
                "root_knowledge_point_id": 5,
                "question_count": 10,
                "correct_count": 8,
                "finished_at": NOW,
                "served_ids": {1, 2},
                "resolved_ids": {1, 2, 3},
                "served_count": 2,
                "resolved_count": 3,
            }
        ]
        stats, total = aggregate_session_stats(nodes, sessions)
        assert set(stats.keys()) == {5}
        assert stats[5]["session_count"] == 1
        assert stats[5]["question_count"] == 10
        assert stats[5]["correct_count"] == 8
        assert stats[5]["served_ids"] == {1, 2}
        assert stats[5]["resolved_ids"] == {1, 2, 3}
        assert stats[5]["scope_served_count"] == 2
        assert stats[5]["scope_resolved_count"] == 3
        assert stats[5]["last_practiced_at"] == NOW

    def test_session_attributes_to_root_and_all_ancestors(self):
        nodes = [{"knowledge_point_id": 5, "ancestor_ids": [3, 1]}]
        sessions = [
            {
                "root_knowledge_point_id": 5,
                "question_count": 10,
                "correct_count": 8,
                "finished_at": NOW,
                "served_count": 2,
                "resolved_count": 3,
            }
        ]
        stats, total = aggregate_session_stats(nodes, sessions)
        assert set(stats.keys()) == {5, 3, 1}
        for kp_id in (5, 3, 1):
            assert stats[kp_id]["session_count"] == 1
            assert stats[kp_id]["question_count"] == 10

    def test_zero_root_id_filtered_out(self):
        # target_ids with id <= 0 are skipped
        nodes = [{"knowledge_point_id": 0, "ancestor_ids": []}]
        sessions = [
            {
                "root_knowledge_point_id": 0,
                "question_count": 5,
                "correct_count": 5,
                "finished_at": NOW,
            }
        ]
        stats, total = aggregate_session_stats(nodes, sessions)
        assert stats == {}
        # but totals still include the session
        assert total["session_count"] == 1
        assert total["question_count"] == 5

    def test_recent_session_counted_when_finished_at_ge_recent_since(self):
        nodes = [{"knowledge_point_id": 5, "ancestor_ids": []}]
        recent_since = NOW - timedelta(days=1)
        sessions = [
            {
                "root_knowledge_point_id": 5,
                "question_count": 1,
                "correct_count": 1,
                "finished_at": NOW,
            }
        ]
        stats, total = aggregate_session_stats(nodes, sessions, recent_since=recent_since)
        assert total["recent_session_count"] == 1
        assert stats[5]["recent_session_count"] == 1

    def test_old_session_not_recent(self):
        nodes = [{"knowledge_point_id": 5, "ancestor_ids": []}]
        recent_since = NOW - timedelta(days=1)
        sessions = [
            {
                "root_knowledge_point_id": 5,
                "question_count": 1,
                "correct_count": 1,
                "finished_at": NOW - timedelta(days=5),
            }
        ]
        stats, total = aggregate_session_stats(nodes, sessions, recent_since=recent_since)
        assert total["recent_session_count"] == 0
        assert stats[5]["recent_session_count"] == 0

    def test_finished_at_string_not_treated_as_recent(self):
        # Only datetime instances trigger "is_recent"; strings do not.
        nodes = [{"knowledge_point_id": 5, "ancestor_ids": []}]
        recent_since = NOW - timedelta(days=1)
        sessions = [
            {
                "root_knowledge_point_id": 5,
                "question_count": 1,
                "correct_count": 1,
                "finished_at": "2026-08-16T12:00:00",
            }
        ]
        stats, total = aggregate_session_stats(nodes, sessions, recent_since=recent_since)
        assert total["recent_session_count"] == 0
        # And last_practiced_at stays None because string is not datetime.
        assert stats[5]["last_practiced_at"] is None

    def test_last_practiced_at_keeps_latest(self):
        nodes = [{"knowledge_point_id": 5, "ancestor_ids": []}]
        earlier = NOW - timedelta(days=2)
        later = NOW - timedelta(days=1)
        sessions = [
            {
                "root_knowledge_point_id": 5,
                "question_count": 1,
                "correct_count": 1,
                "finished_at": earlier,
            },
            {
                "root_knowledge_point_id": 5,
                "question_count": 1,
                "correct_count": 1,
                "finished_at": later,
            },
        ]
        stats, total = aggregate_session_stats(nodes, sessions)
        assert stats[5]["last_practiced_at"] == later

    def test_served_count_defaults_to_len_served_ids_when_missing(self):
        nodes = [{"knowledge_point_id": 5, "ancestor_ids": []}]
        sessions = [
            {
                "root_knowledge_point_id": 5,
                "question_count": 1,
                "correct_count": 1,
                "finished_at": NOW,
                "served_ids": {10, 20},
                "resolved_ids": {10, 20, 30},
                # served_count / resolved_count omitted
            }
        ]
        stats, total = aggregate_session_stats(nodes, sessions)
        assert stats[5]["scope_served_count"] == 2
        assert stats[5]["scope_resolved_count"] == 3
        assert total["scope_served_count"] == 2
        assert total["scope_resolved_count"] == 3

    def test_negative_counts_clamped_to_zero(self):
        nodes = [{"knowledge_point_id": 5, "ancestor_ids": []}]
        sessions = [
            {
                "root_knowledge_point_id": 5,
                "question_count": 5,
                "correct_count": 5,
                "finished_at": NOW,
                "served_count": -3,
                "resolved_count": -4,
            }
        ]
        stats, total = aggregate_session_stats(nodes, sessions)
        assert stats[5]["scope_served_count"] == 0
        assert stats[5]["scope_resolved_count"] == 0
        assert total["scope_served_count"] == 0
        assert total["scope_resolved_count"] == 0
        # resolved <= 0 -> scope_coverage_ratio is None
        assert total["scope_coverage_ratio"] is None

    def test_root_not_in_nodes_still_attributes_to_root_id_only(self):
        # No node lookup -> ancestor contribution skipped, but root still recorded.
        nodes = []
        sessions = [
            {
                "root_knowledge_point_id": 99,
                "question_count": 4,
                "correct_count": 4,
                "finished_at": NOW,
            }
        ]
        stats, total = aggregate_session_stats(nodes, sessions)
        assert set(stats.keys()) == {99}
        assert stats[99]["session_count"] == 1

    def test_unique_served_resolved_merged_across_sessions(self):
        nodes = [{"knowledge_point_id": 5, "ancestor_ids": []}]
        sessions = [
            {
                "root_knowledge_point_id": 5,
                "question_count": 1,
                "correct_count": 1,
                "finished_at": NOW,
                "served_ids": {1, 2},
                "resolved_ids": {1},
            },
            {
                "root_knowledge_point_id": 5,
                "question_count": 1,
                "correct_count": 1,
                "finished_at": NOW,
                "served_ids": {2, 3},
                "resolved_ids": {3, 4},
            },
        ]
        _, total = aggregate_session_stats(nodes, sessions)
        assert total["served_ids"] == {1, 2, 3}
        assert total["resolved_ids"] == {1, 3, 4}

    def test_scope_coverage_ratio_in_total(self):
        nodes = [{"knowledge_point_id": 5, "ancestor_ids": []}]
        sessions = [
            {
                "root_knowledge_point_id": 5,
                "question_count": 1,
                "correct_count": 1,
                "finished_at": NOW,
                "served_count": 8,
                "resolved_count": 10,
            }
        ]
        _, total = aggregate_session_stats(nodes, sessions)
        assert total["scope_coverage_ratio"] == 0.8

    def test_duplicate_ancestor_ids_deduplicated_via_dict_fromkeys(self):
        # ancestor_ids contains duplicates; each target_id counted once.
        nodes = [{"knowledge_point_id": 5, "ancestor_ids": [3, 3, 1]}]
        sessions = [
            {
                "root_knowledge_point_id": 5,
                "question_count": 10,
                "correct_count": 5,
                "finished_at": NOW,
            }
        ]
        stats, _ = aggregate_session_stats(nodes, sessions)
        # Each ancestor gets exactly one increment.
        assert stats[3]["session_count"] == 1
        assert stats[1]["session_count"] == 1
