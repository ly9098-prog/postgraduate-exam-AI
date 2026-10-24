"""Compatibility baseline for v2 dead/corrupt diagnostic projections."""

from __future__ import annotations

import json

from app.services.task_queue_v2_diagnostics_contract import (
    build_v2_corrupt_entry,
    build_v2_dead_entry,
)


def test_dead_entry_returns_payload_object_when_valid():
    payload = {"task_id": "task-1", "task_type": "demo", "status": "dead"}
    assert build_v2_dead_entry("task-1", json.dumps(payload)) == payload


def test_dead_entry_marks_expired_hash_and_corrupt_payload():
    assert build_v2_dead_entry("task-1", None) == {
        "task_id": "task-1",
        "error": "hash_expired",
    }
    assert build_v2_dead_entry("task-1", "{invalid") == {
        "task_id": "task-1",
        "error": "corrupt_payload",
    }


def test_corrupt_entry_preserves_score_and_payload_precedence():
    payload = {
        "task_id": "payload-id",
        "task_type": "demo",
        "status": "corrupt",
    }
    entry = build_v2_corrupt_entry("task-1", 123.5, json.dumps(payload))
    assert entry["task_id"] == "payload-id"
    assert entry["discovered_at"] == 123.5
    assert entry["task_type"] == "demo"


def test_corrupt_entry_handles_missing_and_invalid_payloads():
    assert build_v2_corrupt_entry("task-1", 123.5, None) == {
        "task_id": "task-1",
        "discovered_at": 123.5,
    }
    assert build_v2_corrupt_entry("task-1", 123.5, "{invalid") == {
        "task_id": "task-1",
        "discovered_at": 123.5,
        "error": "corrupt_payload",
    }
