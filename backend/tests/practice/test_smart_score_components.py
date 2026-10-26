"""Characterize score groups, reason order and graph boundary behavior."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services.practice.smart_scoring import calculate_smart_score

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)


def score(*, state=None, kp_ids=None, mastery=None, recent=None, **kwargs):
    return calculate_smart_score(
        None, state, kp_ids or [], mastery or {}, recent or set(), NOW, **kwargs,
    )


def state(**kwargs):
    values = {
        "next_review_at": None, "wrong_count": 0, "answer_count": 1,
        "last_answered_at": None,
    }
    return SimpleNamespace(**(values | kwargs))


@pytest.mark.parametrize(("days", "expected", "reasons"), [
    (-1, 0.0, []),
    (0, 40.0, ["due_review"]),
    (3, 46.0, ["due_review", "overdue_3d"]),
    (30, 60.0, ["due_review", "overdue_30d"]),
])
def test_review_window_and_overdue_cap(days, expected, reasons):
    assert score(state=state(next_review_at=NOW - timedelta(days=days))) == (
        expected, reasons,
    )


@pytest.mark.parametrize(("mastery", "observations", "expected", "reasons"), [
    ((40.0, 0.0), (2, 2), 42.0, ["observed_weak", "new_question", "diversity"]),
    ((40.0, 0.0), (2, 1), 30.0, ["new_question", "diversity"]),
    ((41.0, 0.0), (2, 2), 30.0, ["new_question", "diversity"]),
    ((0.0, 0.375), (2, 2), 45.0, ["weak_kp", "new_question", "diversity"]),
])
def test_confirmed_weakness_precedes_observed_bonus(mastery, observations, expected, reasons):
    assert score(
        kp_ids=[1], mastery={1: mastery}, kp_observations={1: observations},
    ) == (expected, reasons)


def test_all_group_order_and_personalized_weights():
    current = state(
        next_review_at=NOW - timedelta(days=4), wrong_count=5, answer_count=0,
        last_answered_at=NOW - timedelta(days=30),
    )
    args = dict(
        state=current, kp_ids=[1], mastery={1: (0.0, 1.0)},
        blocked_kps={1: [{"path_quality": 1.5}]},
    )
    expected_reasons = [
        "due_review", "overdue_4d", "weak_kp", "wrong_history", "new_question",
        "long_unpracticed", "diversity", "weak_prerequisite",
    ]
    assert score(**args) == (125.5, expected_reasons)
    assert score(**args, weights={}) == (125.5, expected_reasons)
    assert score(**args, weights={"due_weight": 2.0, "path_weight": 0.5}) == (
        192.25, expected_reasons,
    )


@pytest.mark.parametrize(("days", "expected", "reasons"), [
    (29, 0.0, []), (30, 15.0, ["long_unpracticed"]),
])
def test_long_unpracticed_threshold(days, expected, reasons):
    assert score(state=state(last_answered_at=NOW - timedelta(days=days))) == (
        expected, reasons,
    )


def test_diversity_uses_any_recent_overlap_and_weakness_averages_duplicates():
    assert score(
        kp_ids=[1, 1, 2], mastery={1: (0.0, 1.0), 2: (100.0, 1.0)}, recent={2},
    ) == (20.0 + 80.0 / 3, ["weak_kp", "new_question"])


@pytest.mark.parametrize(("blocked", "expected", "reasons"), [
    (None, 38.0, ["new_question", "diversity", "path_ready"]),
    ({1: []}, 30.0, ["new_question", "diversity"]),
    ({1: [{"path_quality": 0}]}, 30.0, [
        "new_question", "diversity", "weak_prerequisite",
    ]),
])
def test_blocked_key_presence_prevents_ready_even_with_empty_or_zero_evidence(
    blocked, expected, reasons,
):
    assert score(
        kp_ids=[1], blocked_kps=blocked,
        prerequisites_by_target={1: [{
            "depth": 1, "mastery_score": 60.0, "mastery_confidence": 0.3,
        }]},
    ) == (expected, reasons)


@pytest.mark.parametrize(("confirmed", "quality", "bonus"), [
    (True, 2.0, 45.0), (False, 2.0, 10.0), (True, -1.0, 0.0),
])
def test_graph_bonus_clamps_evidence_and_distinguishes_unknown_prerequisites(
    confirmed, quality, bonus,
):
    result, reasons = score(kp_ids=[1], graph_candidates={1: {
        "confirmed_gap": confirmed, "path_quality": quality,
        "origin_mastery_score": -1.0, "origin_mastery_confidence": 2.0,
        "mastery_score": -1.0, "mastery_confidence": 2.0,
    }})
    assert result == 30.0 + bonus
    assert reasons == ["new_question", "diversity"] + (
        ["prerequisite_need"] if bonus else []
    )


def test_invalid_graph_configuration_is_rejected_before_accessing_question_state():
    class UnreadableState:
        def __bool__(self):
            raise AssertionError("state must not be read before graph config")

    with pytest.raises(ValueError):
        score(
            state=UnreadableState(),
            graph_config={"prerequisite_mastery_threshold": "invalid"},
        )


def test_observed_weakness_uses_live_module_port(monkeypatch):
    from app.services.practice import smart_scoring

    calls = []

    def observed(ids, mastery, observations):
        calls.append((ids, mastery, observations))
        return [1]

    monkeypatch.setattr(smart_scoring, "_get_observed_weak_kp_ids", observed)
    observations = {1: (1, 1)}
    assert score(kp_ids=[1], kp_observations=observations) == (
        42.0, ["observed_weak", "new_question", "diversity"],
    )
    assert len(calls) == 1 and calls[0][2] is observations


def test_graph_unknown_still_validates_prerequisite_numbers():
    with pytest.raises(ValueError):
        score(kp_ids=[1], graph_candidates={
            1: {"confirmed_gap": False, "mastery_score": "invalid"},
        })


def test_best_graph_bonus_is_not_summed_and_path_ready_is_awarded_once():
    assert score(
        kp_ids=[1, 2], graph_candidates={
            1: {"path_quality": 1.0}, 2: {"path_quality": 1.0},
        },
        prerequisites_by_target={
            kp_id: [{"depth": 1, "mastery_score": 100.0, "mastery_confidence": 1.0}]
            for kp_id in (1, 2)
        },
    ) == (43.0, ["new_question", "diversity", "prerequisite_need", "path_ready"])
