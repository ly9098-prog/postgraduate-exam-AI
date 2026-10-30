"""Review transitions preserve field history and validation/clock ordering."""

from datetime import datetime
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.api.v1 import admin_formulas
from app.models.formula import FormulaCard
from app.services.formula_review_rules import apply_formula_action

NOW = datetime(2026, 10, 30, 12, 0)
EARLIER = datetime(2026, 10, 1)


def make_card(status: str) -> FormulaCard:
    return FormulaCard(
        id=41,
        status=status,
        version=7,
        updated_by=2,
        reviewed_by=3,
        reviewed_at=EARLIER,
        published_at=EARLIER,
        rejection_reason="historical reason",
    )


@pytest.mark.parametrize(
    ("status", "action", "expected", "reviewer", "published", "reason"),
    [
        ("draft", "approve", "pending_review", None, None, None),
        ("pending_review", "approve", "published", 9, NOW, None),
        ("pending_review", "reject", "rejected", 9, None, "needs evidence"),
        ("rejected", "restore", "draft", None, None, "historical reason"),
        ("published", "offline", "offline", None, None, "historical reason"),
        ("offline", "publish", "published", 9, NOW, "historical reason"),
        ("approved", "publish", "published", 9, NOW, "historical reason"),
        ("draft", "restore", "draft", None, None, "historical reason"),
    ],
)
def test_review_field_history(status, action, expected, reviewer, published, reason):
    card = make_card(status)
    result = apply_formula_action(
        card, action, 9, now=NOW, rejection_reason="  needs evidence  "
    )
    assert result == card.status == expected
    assert card.version == 8
    assert card.updated_by == 9
    assert card.reviewed_by == reviewer
    assert card.reviewed_at == (NOW if reviewer else None)
    assert card.published_at == published
    assert card.rejection_reason == reason


@pytest.mark.parametrize(
    ("status", "action", "allowed"),
    [
        ("published", "approve", ["offline"]),
        ("unknown", "approve", []),
        ("draft", "unknown", ["restore", "approve"]),
    ],
)
def test_invalid_transition_does_not_read_clock_or_mutate(status, action, allowed):
    card = make_card(status)
    before = dict(card.__dict__)
    clock = Mock(return_value=NOW)
    with pytest.raises(HTTPException) as raised:
        apply_formula_action(card, action, 9, clock=clock)
    assert raised.value.status_code == 422
    assert raised.value.detail == (
        f"Cannot transition from {status} with action {action}. Allowed: {allowed}"
    )
    assert card.__dict__ == before
    clock.assert_not_called()


@pytest.mark.parametrize("reason", [None, "", " \t "])
def test_missing_reason_reads_clock_then_rejects_without_mutation(reason):
    card = make_card("pending_review")
    before = dict(card.__dict__)
    clock = Mock(return_value=NOW)
    with pytest.raises(HTTPException) as raised:
        apply_formula_action(card, "reject", 9, rejection_reason=reason, clock=clock)
    assert (raised.value.status_code, raised.value.detail) == (
        422,
        "Rejection reason required",
    )
    clock.assert_called_once_with()
    assert card.__dict__ == before


def test_legacy_route_helper_uses_its_current_clock(monkeypatch):
    clock = Mock(return_value=NOW)
    monkeypatch.setattr(admin_formulas, "utcnow", clock)
    card = make_card("pending_review")
    assert admin_formulas._apply_formula_action(card, "approve", 9) == "published"
    clock.assert_called_once_with()
    assert card.published_at is NOW


def test_explicit_time_bypasses_the_route_clock(monkeypatch):
    clock = Mock(side_effect=AssertionError("clock must not run"))
    monkeypatch.setattr(admin_formulas, "utcnow", clock)
    card = make_card("pending_review")
    admin_formulas._apply_formula_action(card, "approve", 9, now=NOW)
    assert card.reviewed_at is NOW
    clock.assert_not_called()


def test_clock_failure_precedes_all_card_mutations():
    card = make_card("pending_review")
    before = dict(card.__dict__)
    with pytest.raises(RuntimeError, match="synthetic clock failure"):
        apply_formula_action(
            card, "approve", 9, clock=Mock(side_effect=RuntimeError("synthetic clock failure"))
        )
    assert card.__dict__ == before
