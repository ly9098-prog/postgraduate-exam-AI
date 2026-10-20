"""Characterize the export transition contract independently of worker timing."""

from __future__ import annotations

from itertools import product

import pytest

from app.schemas.export_task import ExportTaskStatus
from app.services.export.state_machine import validate_transition

ALLOWED = {
    ("pending", "processing"),
    ("processing", "completed"),
    ("processing", "failed"),
    ("completed", "expired"),
    ("completed", "pending"),
    ("failed", "pending"),
    ("failed", "expired"),
    ("expired", "pending"),
}


@pytest.mark.parametrize(("current", "target"), list(product(ExportTaskStatus, repeat=2)))
@pytest.mark.parametrize("strings", [False, True])
def test_every_export_transition(current, target, strings):
    if strings:
        current, target = current.value, target.value
    if (current, target) in ALLOWED:
        assert validate_transition(current, target, task_id=17) is None
    else:
        with pytest.raises(ValueError) as exc:
            validate_transition(current, target, task_id=17)
        assert str(exc.value) == (
            f"export_state_invalid: transition {current}→{target} not allowed for task 17"
        )


@pytest.mark.parametrize("current", ["", "unknown", "PENDING", " pending "])
def test_unknown_current_state_precedes_target_validation(current):
    with pytest.raises(ValueError) as exc:
        validate_transition(current, "unknown", task_id=-1)
    assert str(exc.value) == (
        f"export_state_invalid: unknown current state '{current}' for task -1"
    )


def test_unknown_target_preserves_default_task_id():
    with pytest.raises(ValueError) as exc:
        validate_transition("processing", "unknown")
    assert str(exc.value) == (
        "export_state_invalid: transition processing→unknown not allowed for task 0"
    )
