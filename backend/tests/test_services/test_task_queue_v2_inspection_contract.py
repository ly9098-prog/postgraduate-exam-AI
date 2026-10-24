"""Compatibility baseline for v2 task-hash inspection projection."""

from __future__ import annotations

import json

from app.services.task_queue_v2_inspection_contract import build_v2_task_inspection


def test_empty_hash_maps_to_none():
    assert build_v2_task_inspection("task-1", {}) is None
    assert build_v2_task_inspection("task-1", None) is None


def test_task_hash_includes_requested_id_and_all_fields():
    raw = {
        "data": json.dumps({"task_id": "task-1", "status": "processing"}),
        "status": "processing",
        "owner_token": "owner",
    }
    result = build_v2_task_inspection("task-1", raw)

    assert result["task_id"] == "task-1"
    assert result["data"] == {"task_id": "task-1", "status": "processing"}
    assert result["status"] == "processing"
    assert result["owner_token"] == "owner"


def test_invalid_data_field_remains_raw_string():
    result = build_v2_task_inspection("task-1", {"data": "{invalid"})
    assert result["data"] == "{invalid"
