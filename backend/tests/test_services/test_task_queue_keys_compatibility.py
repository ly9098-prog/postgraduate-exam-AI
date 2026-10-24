"""Real compatibility baseline for task queue Redis key construction."""

from __future__ import annotations

import pytest

from app.services.task_queue_keys import (
    _corrupt_key,
    _dead_key,
    _heartbeat_key,
    _idempotent_key,
    _p_key,
    _q_key,
    _retry_key,
    _task_hash_key,
    _v2_corrupt_key,
    _v2_dead_key,
    _v2_fencing_key,
    _v2_heartbeat_key,
    _v2_idempotent_key,
    _v2_p_key,
    _v2_q_key,
    _v2_retry_key,
    _v2_task_hash_key,
)


class TestV1Keys:
    def test_q_key(self):
        assert _q_key("import_pipeline") == "taskq:queue:import_pipeline"

    def test_p_key(self):
        assert _p_key("image_pipeline") == "taskq:processing:image_pipeline"

    def test_dead_key(self):
        assert _dead_key("excel_pipeline") == "taskq:dead:excel_pipeline"

    def test_retry_key(self):
        assert _retry_key("batch_image") == "taskq:retry:batch_image"

    def test_corrupt_key(self):
        assert _corrupt_key("formula_batch") == "taskq:corrupt:formula_batch"

    def test_task_hash_key(self):
        assert _task_hash_key("task_123") == "taskq:task:task_123"

    def test_heartbeat_key(self):
        assert _heartbeat_key("task_123") == "taskq:heartbeat:task_123"

    def test_idempotent_key(self):
        assert _idempotent_key("task_123") == "taskq:idempotent:task_123"


class TestV2Keys:
    def test_v2_q_key(self):
        key = _v2_q_key("import_pipeline")
        assert "import_pipeline" in key
        assert key != _q_key("import_pipeline")

    def test_v2_p_key(self):
        key = _v2_p_key("image_pipeline")
        assert "image_pipeline" in key

    def test_v2_dead_key(self):
        key = _v2_dead_key("excel_pipeline")
        assert "excel_pipeline" in key

    def test_v2_retry_key(self):
        key = _v2_retry_key("batch_image")
        assert "batch_image" in key

    def test_v2_corrupt_key(self):
        key = _v2_corrupt_key("formula_batch")
        assert "formula_batch" in key

    def test_v2_task_hash_key(self):
        key = _v2_task_hash_key("task_123")
        assert "task_123" in key

    def test_v2_heartbeat_key(self):
        key = _v2_heartbeat_key("task_123")
        assert "task_123" in key

    def test_v2_fencing_key(self):
        key = _v2_fencing_key("task_123")
        assert "task_123" in key

    def test_v2_idempotent_key(self):
        key = _v2_idempotent_key("task_123")
        assert "task_123" in key
