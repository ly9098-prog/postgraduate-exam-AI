"""Compatibility baseline for v1-to-v2 migration result handling."""

from __future__ import annotations

from app.services.task_queue_v1_to_v2_contract import parse_v1_to_v2_result


def test_empty_and_absent_results_stop_the_batch():
    for result in (None, [], ["empty", ""]):
        step = parse_v1_to_v2_result(result)
        assert step.outcome == "empty"
        assert step.task_id == ""
        assert step.should_continue is False
        assert step.should_stop is False
        assert step.is_migrated is False


def test_migration_outcomes_preserve_task_id_and_control_flow():
    migrated = parse_v1_to_v2_result(["migrated", "task-1"])
    duplicate = parse_v1_to_v2_result(["duplicate", "task-1"])
    corrupt = parse_v1_to_v2_result(["corrupt", "task-1"])

    assert migrated.task_id == "task-1"
    assert migrated.should_continue is True
    assert migrated.should_stop is False
    assert migrated.is_migrated is True
    assert duplicate.is_migrated is False
    assert corrupt.is_migrated is False


def test_queue_full_and_conflict_stop_the_batch():
    queue_full = parse_v1_to_v2_result(["queue_full", "task-1"])
    conflict = parse_v1_to_v2_result(["conflict", "task-1"])

    assert queue_full.should_continue is True
    assert queue_full.should_stop is True
    assert conflict.should_continue is True
    assert conflict.should_stop is True
