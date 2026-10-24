"""Compatibility baseline for v1 dead-list diagnostics and purge decisions."""

from __future__ import annotations

import json

import pytest

from app.services.task_queue_v1_dead_contract import (
    build_v1_dead_entry,
    build_v1_dead_purge_plan,
)


def test_dead_entry_returns_payload_object_when_valid():
    payload = {"task_id": "task-1", "task_type": "demo", "status": "dead"}
    assert build_v1_dead_entry("task-1", json.dumps(payload)) == payload


def test_dead_entry_marks_expired_hash_and_corrupt_payload():
    assert build_v1_dead_entry("task-1", None) == {
        "task_id": "task-1",
        "error": "hash_expired",
    }
    assert build_v1_dead_entry("task-1", "{invalid") == {
        "task_id": "task-1",
        "error": "corrupt_payload",
    }


def test_missing_and_corrupt_payloads_leave_dead_list_without_hash_delete():
    missing = build_v1_dead_purge_plan(None, now=100.0, max_age_sec=10)
    corrupt = build_v1_dead_purge_plan("{invalid", now=100.0, max_age_sec=10)

    assert missing.remove_from_dead is True
    assert missing.delete_hash is False
    assert corrupt.remove_from_dead is True
    assert corrupt.delete_hash is False


def test_old_payload_removes_dead_entry_and_hash():
    raw = json.dumps({"updated_at": 80.0})
    plan = build_v1_dead_purge_plan(raw, now=100.0, max_age_sec=10)

    assert plan.remove_from_dead is True
    assert plan.delete_hash is True


def test_recent_payload_is_retained_and_boundary_is_exclusive():
    raw = json.dumps({"updated_at": 95.0})
    retained = build_v1_dead_purge_plan(raw, now=100.0, max_age_sec=10)
    boundary = build_v1_dead_purge_plan(raw, now=105.0, max_age_sec=10)

    assert retained.remove_from_dead is False
    assert retained.delete_hash is False
    assert boundary.remove_from_dead is False
    assert boundary.delete_hash is False


def test_non_object_payload_preserves_historical_attribute_failure():
    with pytest.raises(AttributeError):
        build_v1_dead_purge_plan("[]", now=100.0, max_age_sec=10)
