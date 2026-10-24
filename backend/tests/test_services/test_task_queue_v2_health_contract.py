"""Compatibility baseline for v2 queue-health calculations."""

from __future__ import annotations

import json

import pytest

from app.services.task_queue_v2_health_contract import (
    v1_oldest_ready_age,
    v2_oldest_ready_age,
)


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


def test_v1_oldest_ready_age_matches_historical_fallbacks():
    payload = json.dumps({"created_at": 100.0})
    assert v1_oldest_ready_age("task-1", payload, now=200.0) == 100.0
    assert v1_oldest_ready_age("task-1", payload, now=50.0) == -50.0
    assert v1_oldest_ready_age(None, payload, now=200.0) == 0.0
    assert v1_oldest_ready_age("task-1", None, now=200.0) == 0.0
    assert v1_oldest_ready_age("task-1", json.dumps({"created_at": 0}), now=200.0) == 0.0


def test_v1_oldest_ready_age_preserves_historical_payload_errors():
    with pytest.raises(json.JSONDecodeError):
        v1_oldest_ready_age("task-1", "{invalid", now=200.0)
    with pytest.raises(TypeError):
        v1_oldest_ready_age("task-1", json.dumps({"created_at": "bad"}), now=200.0)
