"""Pure-function compatibility baseline for rank_chapter_recommendations.

Pins the candidate filtering, multi-key sort order (priority desc, depth desc,
kp id asc), non-overlap selection, limit-aware backfill of overlapping
candidates, output payload shape, recommendation-kind/copy wiring, route params,
and the last_chapter_practiced_at ISO serialization contract.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.services.knowledge_diagnosis_logic import (
    _CANDIDATE_MAX_DEPTH,
    _DEFAULT_QUESTION_COUNT,
    _MAX_RECOMMENDATIONS,
    rank_chapter_recommendations,
)

NOW = datetime(2026, 8, 16, 12, 0, 0)


def _node(
    *,
    kp_id,
    name="n",
    depth=1,
    has_children=True,
    trainable=10,
    coverage=0.9,
    reliable=8,
    weak=0,
    mastery=80.0,
    status="ok",
    ancestors=(),
):
    return {
        "knowledge_point_id": kp_id,
        "name": name,
        "depth": depth,
        "has_children": has_children,
        "subtree_trainable_knowledge_points": trainable,
        "subtree_coverage_ratio": coverage,
        "subtree_reliable_knowledge_points": reliable,
        "subtree_weak_knowledge_points": weak,
        "subtree_mastery_score": mastery,
        "subtree_status": status,
        "ancestor_ids": list(ancestors),
    }


class TestCandidateFiltering:
    def test_empty_nodes_returns_empty_list(self):
        assert rank_chapter_recommendations([], {}, subject_id=1, now=NOW) == []

    def test_leaf_node_without_children_filtered_out(self):
        node = _node(kp_id=1, has_children=False)
        assert rank_chapter_recommendations([node], {}, subject_id=1, now=NOW) == []

    def test_node_depth_above_max_filtered_out(self):
        # _CANDIDATE_MAX_DEPTH is 2; depth=3 is filtered.
        node = _node(kp_id=1, depth=3)
        assert rank_chapter_recommendations([node], {}, subject_id=1, now=NOW) == []

    def test_node_at_max_depth_kept(self):
        node = _node(kp_id=1, depth=2)
        result = rank_chapter_recommendations([node], {}, subject_id=1, now=NOW)
        assert len(result) == 1

    def test_node_zero_trainable_filtered_out(self):
        node = _node(kp_id=1, trainable=0)
        assert rank_chapter_recommendations([node], {}, subject_id=1, now=NOW) == []

    def test_node_negative_trainable_filtered_out(self):
        node = _node(kp_id=1, trainable=-5)
        assert rank_chapter_recommendations([node], {}, subject_id=1, now=NOW) == []


class TestSortOrder:
    def test_higher_priority_ranks_first(self):
        # Lower coverage -> higher priority.
        low_cov = _node(kp_id=1, coverage=0.1, name="low")
        high_cov = _node(kp_id=2, coverage=1.0, name="high")
        result = rank_chapter_recommendations(
            [high_cov, low_cov], {}, subject_id=1, now=NOW
        )
        assert result[0]["knowledge_point_id"] == 1
        assert result[1]["knowledge_point_id"] == 2

    def test_equal_priority_deeper_depth_first(self):
        # Equal priority -> deeper depth first (depth desc in sort key).
        # depth=1 node has lower coverage so its coverage term (+2.0) exactly
        # offsets the depth bonus gap (depth=1 -> +2, depth=2 -> +4, diff 2).
        # Both priorities round to 14.0, exercising the depth-desc tie-break.
        shallow = _node(kp_id=1, depth=1, coverage=28 / 30, mastery=100.0)
        deep = _node(kp_id=2, depth=2, coverage=1.0, mastery=100.0)
        result = rank_chapter_recommendations(
            [shallow, deep], {}, subject_id=1, now=NOW
        )
        assert result[0]["knowledge_point_id"] == 2  # depth=2 wins
        assert result[1]["knowledge_point_id"] == 1
        # Confirm priorities are actually equal (otherwise depth tie-break is moot).
        assert result[0]["priority_score"] == result[1]["priority_score"]

    def test_equal_priority_equal_depth_lower_kp_id_first(self):
        # Tie-break by ascending knowledge_point_id.
        a = _node(kp_id=10, depth=1, coverage=1.0, mastery=100.0)
        b = _node(kp_id=5, depth=1, coverage=1.0, mastery=100.0)
        result = rank_chapter_recommendations([a, b], {}, subject_id=1, now=NOW)
        assert result[0]["knowledge_point_id"] == 5
        assert result[1]["knowledge_point_id"] == 10


class TestNonOverlapSelection:
    def test_ancestor_descendant_pair_keeps_higher_priority_only_first_pass(self):
        # node 2 has ancestor 1; both are candidates. The higher-priority one
        # is selected first; the other is skipped in the non-overlap pass.
        low_cov = _node(kp_id=1, coverage=0.1, name="root", ancestors=[])
        high_cov = _node(
            kp_id=2, coverage=1.0, name="child", ancestors=[1]
        )
        result = rank_chapter_recommendations(
            [low_cov, high_cov], {}, subject_id=1, now=NOW, limit=2
        )
        # low_cov (kp=1) has higher priority (coverage 0.1) -> selected first.
        # high_cov (kp=2) overlaps (its ancestor is kp=1) -> skipped in pass 1.
        # But limit=2 -> backfill pass adds high_cov because it is not yet selected.
        assert [r["knowledge_point_id"] for r in result] == [1, 2]

    def test_limit_one_with_overlap_keeps_only_first(self):
        low_cov = _node(kp_id=1, coverage=0.1, ancestors=[])
        high_cov = _node(kp_id=2, coverage=1.0, ancestors=[1])
        result = rank_chapter_recommendations(
            [low_cov, high_cov], {}, subject_id=1, now=NOW, limit=1
        )
        assert [r["knowledge_point_id"] for r in result] == [1]

    def test_disjoint_nodes_all_selected(self):
        a = _node(kp_id=1, coverage=0.1, ancestors=[])
        b = _node(kp_id=2, coverage=0.2, ancestors=[])
        c = _node(kp_id=3, coverage=0.3, ancestors=[])
        result = rank_chapter_recommendations(
            [a, b, c], {}, subject_id=1, now=NOW, limit=3
        )
        assert [r["knowledge_point_id"] for r in result] == [1, 2, 3]

    def test_backfill_skips_already_selected_ids(self):
        # Two disjoint nodes selected in pass 1; pass 2 backfill must skip them.
        a = _node(kp_id=1, coverage=0.1, ancestors=[])
        b = _node(kp_id=2, coverage=0.2, ancestors=[])
        # c overlaps a (ancestor 1) but is lower priority
        c = _node(kp_id=3, coverage=0.5, ancestors=[1])
        result = rank_chapter_recommendations(
            [a, b, c], {}, subject_id=1, now=NOW, limit=3
        )
        # Pass 1 selects a (1) and b (2); c (3) overlaps a -> skipped.
        # Pass 2 backfill: c not yet selected -> added.
        assert [r["knowledge_point_id"] for r in result] == [1, 2, 3]

    def test_fewer_candidates_than_limit_returns_all_candidates(self):
        a = _node(kp_id=1, coverage=0.1, ancestors=[])
        result = rank_chapter_recommendations(
            [a], {}, subject_id=1, now=NOW, limit=5
        )
        assert len(result) == 1

    def test_default_limit_is_three(self):
        assert _MAX_RECOMMENDATIONS == 3
        a = _node(kp_id=1, coverage=0.1, ancestors=[])
        b = _node(kp_id=2, coverage=0.2, ancestors=[])
        c = _node(kp_id=3, coverage=0.3, ancestors=[])
        d = _node(kp_id=4, coverage=0.4, ancestors=[])
        result = rank_chapter_recommendations([a, b, c, d], {}, subject_id=1, now=NOW)
        assert len(result) == 3
        assert [r["knowledge_point_id"] for r in result] == [1, 2, 3]


class TestPayloadShape:
    def _result(self, **kwargs):
        node = _node(kp_id=5, name="指令系统", **kwargs)
        return rank_chapter_recommendations([node], {5: {"session_count": 3}},
                                             subject_id=42, now=NOW)[0]

    def test_rank_starts_at_one(self):
        assert self._result()["rank"] == 1

    def test_kind_present(self):
        assert self._result()["kind"] in {"build", "strengthen", "review", "maintain"}

    def test_knowledge_point_id_int(self):
        assert self._result()["knowledge_point_id"] == 5

    def test_knowledge_point_name_string(self):
        assert self._result()["knowledge_point_name"] == "指令系统"

    def test_depth_int(self):
        assert self._result()["depth"] == 1

    def test_priority_score_float(self):
        assert isinstance(self._result()["priority_score"], float)

    def test_title_reason_action_label_strings(self):
        r = self._result()
        assert isinstance(r["title"], str) and r["title"]
        assert isinstance(r["reason"], str) and r["reason"]
        assert isinstance(r["action_label"], str) and r["action_label"]

    def test_mastery_score_rounded_to_one_decimal(self):
        r = self._result(mastery=80.456)
        assert r["mastery_score"] == 80.5

    def test_mastery_none_returns_none(self):
        r = self._result(mastery=None)
        assert r["mastery_score"] is None

    def test_coverage_ratio_clamped_and_rounded_to_four(self):
        r = self._result(coverage=2.0)
        assert r["coverage_ratio"] == 1.0
        r2 = self._result(coverage=-0.5)
        assert r2["coverage_ratio"] == 0.0
        r3 = self._result(coverage=0.3333)
        assert r3["coverage_ratio"] == 0.3333

    def test_weak_trainable_reliable_counts_int(self):
        r = self._result(weak=3, trainable=12, reliable=8)
        assert r["weak_knowledge_points"] == 3
        assert r["trainable_knowledge_points"] == 12
        assert r["reliable_knowledge_points"] == 8

    def test_last_chapter_practiced_at_iso_with_z_suffix(self):
        stat = {"last_practiced_at": NOW - timedelta(days=5), "session_count": 1}
        node = _node(kp_id=5)
        result = rank_chapter_recommendations([node], {5: stat}, subject_id=1, now=NOW)
        assert result[0]["last_chapter_practiced_at"] == (NOW - timedelta(days=5)).isoformat() + "Z"

    def test_string_last_practiced_at_raises_type_error_in_priority_score(self):
        # Pin real behavior: _days_since only guards None, not non-datetime values.
        # A string last_practiced_at propagates into now - value -> TypeError.
        # Callers must normalize chapter_stat["last_practiced_at"] to datetime.
        import pytest

        stat = {"last_practiced_at": "2026-08-11", "session_count": 0}
        node = _node(kp_id=5)
        with pytest.raises(TypeError):
            rank_chapter_recommendations([node], {5: stat}, subject_id=1, now=NOW)

    def test_last_chapter_practiced_at_none_when_missing(self):
        node = _node(kp_id=5)
        result = rank_chapter_recommendations([node], {5: {}}, subject_id=1, now=NOW)
        assert result[0]["last_chapter_practiced_at"] is None

    def test_chapter_session_count_int(self):
        node = _node(kp_id=5)
        result = rank_chapter_recommendations([node], {5: {"session_count": 7}},
                                               subject_id=1, now=NOW)
        assert result[0]["chapter_session_count"] == 7

    def test_chapter_session_count_defaults_zero(self):
        node = _node(kp_id=5)
        result = rank_chapter_recommendations([node], {5: {}}, subject_id=1, now=NOW)
        assert result[0]["chapter_session_count"] == 0

    def test_route_is_practice(self):
        assert self._result()["route"] == "practice"

    def test_route_params_shape(self):
        r = self._result()["route_params"]
        assert r == {
            "subject_id": 42,
            "mode": "random",
            "count": _DEFAULT_QUESTION_COUNT,
            "knowledge_point_id": 5,
            "include_descendants": 1,
            "include_children": 1,
            "allow_repeat": 1,
            "autostart": 1,
            "source": "knowledge_diagnosis",
        }

    def test_subject_id_int_passed_through(self):
        r = self._result()["route_params"]
        assert r["subject_id"] == 42
        assert isinstance(r["subject_id"], int)


class TestKindWiring:
    def test_build_kind_wired_to_build_copy(self):
        node = _node(kp_id=1, coverage=0.2, reliable=2, mastery=None, status="no_data")
        result = rank_chapter_recommendations([node], {}, subject_id=1, now=NOW)
        assert result[0]["kind"] == "build"
        assert "建立" in result[0]["title"]

    def test_strengthen_kind_wired(self):
        node = _node(kp_id=1, weak=3, mastery=50.0)
        result = rank_chapter_recommendations([node], {}, subject_id=1, now=NOW)
        assert result[0]["kind"] == "strengthen"
        assert "强化" in result[0]["title"]

    def test_review_kind_wired(self):
        node = _node(kp_id=1, mastery=80.0, coverage=0.9, reliable=8, weak=0)
        stat = {"last_practiced_at": NOW - timedelta(days=20), "session_count": 1}
        result = rank_chapter_recommendations([node], {1: stat}, subject_id=1, now=NOW)
        assert result[0]["kind"] == "review"
        assert "复习" in result[0]["title"]

    def test_maintain_kind_wired(self):
        node = _node(kp_id=1, mastery=80.0, coverage=0.9, reliable=8, weak=0)
        stat = {"last_practiced_at": NOW - timedelta(days=1), "session_count": 1}
        result = rank_chapter_recommendations([node], {1: stat}, subject_id=1, now=NOW)
        assert result[0]["kind"] == "maintain"
        assert "巩固" in result[0]["title"]


class TestEndToEnd:
    def test_realistic_mix(self):
        # Three disjoint chapters with different diagnosis states.
        build_node = _node(
            kp_id=10, name="建立章", coverage=0.1, reliable=2, trainable=10,
            mastery=None, status="no_data", ancestors=[],
        )
        strengthen_node = _node(
            kp_id=20, name="强化章", coverage=0.6, reliable=6, trainable=10,
            weak=4, mastery=50.0, ancestors=[],
        )
        review_node = _node(
            kp_id=30, name="复习章", coverage=0.9, reliable=8, trainable=10,
            weak=0, mastery=80.0, ancestors=[],
        )
        stats = {
            20: {"session_count": 2, "last_practiced_at": NOW - timedelta(days=3)},
            30: {"session_count": 5, "last_practiced_at": NOW - timedelta(days=20)},
        }
        result = rank_chapter_recommendations(
            [strengthen_node, review_node, build_node],
            stats,
            subject_id=7,
            now=NOW,
            limit=3,
        )
        # Priority order: build (coverage 0.1) > strengthen (coverage 0.6, weak 4)
        # > review (coverage 0.9). All disjoint -> all three selected.
        assert [r["knowledge_point_id"] for r in result] == [10, 20, 30]
        assert [r["kind"] for r in result] == ["build", "strengthen", "review"]
        assert [r["rank"] for r in result] == [1, 2, 3]
        # subject_id propagated into route_params
        assert all(r["route_params"]["subject_id"] == 7 for r in result)

    def test_subject_id_zero_propagated(self):
        node = _node(kp_id=1)
        result = rank_chapter_recommendations([node], {}, subject_id=0, now=NOW)
        assert result[0]["route_params"]["subject_id"] == 0

    def test_negative_subject_id_propagated(self):
        # Defensive pin: function does not validate subject_id sign.
        node = _node(kp_id=1)
        result = rank_chapter_recommendations([node], {}, subject_id=-1, now=NOW)
        assert result[0]["route_params"]["subject_id"] == -1

    def test_limit_zero_still_appends_first_candidate_then_breaks(self):
        # Pin real behavior: the loop appends BEFORE checking len >= limit.
        # With limit=0, the first candidate is appended (len=1 >= 0 -> break).
        node = _node(kp_id=1)
        result = rank_chapter_recommendations([node], {}, subject_id=1, now=NOW, limit=0)
        assert len(result) == 1
        assert result[0]["knowledge_point_id"] == 1

    def test_limit_negative_still_appends_first_candidate_then_breaks(self):
        # Same as limit=0: append happens before the len check, so negative
        # limits still return exactly one element.
        node = _node(kp_id=1)
        result = rank_chapter_recommendations([node], {}, subject_id=1, now=NOW, limit=-1)
        assert len(result) == 1

    def test_candidate_max_depth_is_two(self):
        assert _CANDIDATE_MAX_DEPTH == 2
