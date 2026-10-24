"""Compatibility baseline for v2 queue-health calculations."""

from __future__ import annotations

import json

from app.services.task_queue_v2_health_contract import v2_oldest_ready_age


def test_oldest_ready_age_requires_task_id_and_payload():
    payload = json.dumps({"created_at": 100.0})
    assert v2_oldest_ready_age(None, payload, now=200.0) == 0.0
    assert v2_oldest_ready_age("task-1", None, now=200.0) == 0.0


def test_oldest_ready_age_ignores_invalid_payloads_and_timestamps():
    assert v2_oldest_ready_age("task-1", "{invalid", now=200.0) == 0.0
    assert v2_oldest_ready_age("task-1", json.dumps({"created_at": "bad"}), now=200.0) == 0.0
    assert v2_oldest_ready_age("task-1", json.dumps({"created_at": 0}), now=200.0) == 0.0
    assert v2_oldest_ready_age("task-1", json.dumps({}), now=200.0) == 0.0


def test_oldest_ready_age_uses_payload_time_and_clamps_future_dates():
    payload = json.dumps({"created_at": 100.0})
    assert v2_oldest_ready_age("task-1", payload, now=200.0) == 100.0
    assert v2_oldest_ready_age("task-1", payload, now=50.0) == 0.0
