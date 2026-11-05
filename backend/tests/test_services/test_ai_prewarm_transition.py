"""Prewarm transition contracts for revision and recovery supersession."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.ai.prewarm_transition import (
    dead_retry_budget,
    recovery_regenerated,
    revision_changed,
)


@pytest.mark.parametrize(
    ("task_data", "expected"),
    [
        ({"max_retries": 1, "error": "ai_service_unavailable: fallback"}, 3),
        ({"max_retries": 8, "error": "ai_service_unavailable: checking"}, 8),
        ({"error": "ai_service_unavailable: transient"}, 3),
        ({"max_retries": 1, "error": "ai_provider_auth_failed: fallback"}, None),
        ({"max_retries": 1, "error": ""}, None),
    ],
)
def test_dead_retry_budget_preserves_historical_compatibility_and_other_failures(
    task_data, expected,
):
    assert dead_retry_budget(task_data) == expected


def build_revision(*, review_count, wrong_answer):
    return f"r{review_count}:{wrong_answer}"


def test_revision_change_ignores_empty_expected_revision():
    wrong = SimpleNamespace(review_count=2, wrong_answer="A")
    assert (
        revision_changed(
            wrong_question=wrong,
            expected_revision=None,
            build_revision=build_revision,
        )
        is False
    )
    assert (
        revision_changed(
            wrong_question=wrong,
            expected_revision="",
            build_revision=build_revision,
        )
        is False
    )


def test_revision_change_compares_current_wrong_answer_and_review_count():
    wrong = SimpleNamespace(review_count=2, wrong_answer="A")
    assert (
        revision_changed(
            wrong_question=wrong,
            expected_revision="r2:A",
            build_revision=build_revision,
        )
        is False
    )
    assert (
        revision_changed(
            wrong_question=wrong,
            expected_revision="r1:A",
            build_revision=build_revision,
        )
        is True
    )
    assert (
        revision_changed(
            wrong_question=wrong,
            expected_revision="r2:B",
            build_revision=build_revision,
        )
        is True
    )


def test_recovery_regeneration_compares_normalized_empty_values():
    wrong = SimpleNamespace(ai_analysis={"_meta": {"generated_at": "new"}})

    def generated_at(value):
        return value["_meta"]["generated_at"]

    assert (
        recovery_regenerated(
            wrong_question=wrong,
            baseline_generated_at=None,
            generated_at=generated_at,
        )
        is False
    )
    assert (
        recovery_regenerated(
            wrong_question=wrong,
            baseline_generated_at="new",
            generated_at=generated_at,
        )
        is False
    )
    assert (
        recovery_regenerated(
            wrong_question=wrong,
            baseline_generated_at="old",
            generated_at=generated_at,
        )
        is True
    )
    assert (
        recovery_regenerated(
            wrong_question=SimpleNamespace(ai_analysis=None),
            baseline_generated_at="old",
            generated_at=lambda _value: None,
        )
        is True
    )
