"""Unit tests for task queue metrics (P0-1 coverage)."""

import pytest
from app.services.task_queue_service import Task


class TestTaskDataclass:
    """Task dataclass fields (P0-1 generation field)."""

    def test_task_generation_field(self):
        t = Task(task_id="test-1", task_type="test", payload={"a": 1})
        assert t.generation == 0  # default
        d = t.to_dict()
        assert d["generation"] == 0
        restored = Task.from_dict(d)
        assert restored.generation == 0

    def test_task_default_lease_sec(self):
        from app.services.task_queue_service import _DEFAULT_LEASE_SEC
        assert _DEFAULT_LEASE_SEC > 0
