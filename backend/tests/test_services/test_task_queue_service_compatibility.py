"""Compatibility baseline for task queue service contracts.

These tests intentionally avoid Redis.  They pin the in-process dataclass,
rolling-version, correlation, and admission-limit rules used by both queue
protocols before any extraction changes their runtime semantics.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.services.task_queue_service import (
    EnqueueResult,
    Task,
    TaskStatus,
    _get_max_ready,
    _minimum_worker_version_for_task,
    _normalize_task_schema_version,
    _task_correlation,
)


class TestEnqueueResult:
    def test_default_is_accepted_and_truthy(self):
        result = EnqueueResult()

        assert result.accepted is True
        assert bool(result) is True
        assert result.task_id is None
        assert result.reason == ""
        assert result.retry_after == 0

    def test_rejection_is_falsy_and_carries_reason(self):
        result = EnqueueResult(
            accepted=False,
            task_id=None,
            reason="queue_full",
            retry_after=30,
        )

        assert bool(result) is False
        assert result.reason == "queue_full"
        assert result.retry_after == 30


class TestTaskDataContract:
    def test_default_task_contract(self):
        task = Task(task_id="task-1", task_type="demo", payload={"value": 1})

        assert task.status is TaskStatus.PENDING
        assert task.retry_count == 0
        assert task.generation == 0
        assert task.schema_version == 2
        assert task.minimum_worker_version == 1
        assert task.owner_token == ""

    def test_to_dict_and_from_dict_round_trip_preserves_all_fields(self):
        task = Task(
            task_id="task-1",
            task_type="demo",
            payload={"value": 1},
            status=TaskStatus.PROCESSING,
            retry_count=2,
            max_retries=5,
            created_at=100.0,
            updated_at=101.0,
            lease_expires_at=401.0,
            owner_token="owner",
            error="temporary failure",
            generation=3,
            schema_version=2,
            minimum_worker_version=2,
            created_by_version="1.2.3",
            trace_id="trace-1",
            request_id="request-1",
        )

        restored = Task.from_dict(task.to_dict())

        assert restored == task

    def test_legacy_payload_defaults_do_not_invent_ownership(self):
        restored = Task.from_dict(
            {
                "task_id": "legacy",
                "task_type": "demo",
                "status": "pending",
            }
        )

        assert restored.payload == {}
        assert restored.owner_token == ""
        assert restored.generation == 0
        assert restored.schema_version == 1
        assert restored.minimum_worker_version == 1
        assert restored.created_at == 0.0


class TestTaskVersionCompatibility:
    @pytest.mark.parametrize("schema_version", [1, 2, 3])
    def test_generic_task_keeps_declared_schema_version(self, schema_version):
        assert _normalize_task_schema_version("demo", schema_version) == schema_version

    @pytest.mark.parametrize("schema_version", [0, 1, 3, 4])
    def test_answer_projection_rejects_non_current_schema(self, schema_version):
        with pytest.raises(ValueError, match="unsupported answer_projection"):
            _normalize_task_schema_version("answer_projection", schema_version)

    def test_answer_projection_requires_current_schema(self):
        assert _normalize_task_schema_version("answer_projection", 2) == 2

    @pytest.mark.parametrize(
        ("task_type", "schema_version", "expected"),
        [
            ("demo", 1, 1),
            ("demo", 2, 1),
            ("answer_projection", 2, 2),
        ],
    )
    def test_minimum_worker_version(self, task_type, schema_version, expected):
        assert _minimum_worker_version_for_task(task_type, schema_version) == expected


class TestTaskCorrelation:
    def test_empty_payload_has_no_correlation(self):
        assert _task_correlation({}) == ("", "")

    def test_detached_options_metadata_is_used_as_fallback(self):
        payload = {
            "options": {
                "_trace_id": "trace-option",
                "_request_id": "request-option",
            }
        }

        assert _task_correlation(payload) == ("trace-option", "request-option")

    def test_reserved_trace_metadata_is_used_when_options_are_absent(self):
        payload = {
            "_trace": {
                "trace_id": "trace-reserved",
                "request_id": "request-reserved",
            }
        }

        assert _task_correlation(payload) == ("trace-reserved", "request-reserved")

    def test_active_log_context_wins_over_detached_metadata(self, monkeypatch):
        monkeypatch.setattr(
            "app.core.log_context.get_log_context",
            lambda: {"trace_id": "trace-live", "request_id": "request-live"},
        )
        payload = {
            "options": {
                "_trace_id": "trace-option",
                "_request_id": "request-option",
            }
        }

        assert _task_correlation(payload) == ("trace-live", "request-live")


class TestReadyQueueAdmissionLimits:
    @pytest.mark.parametrize(
        ("task_type", "setting_name"),
        [
            ("import_pipeline", "TASK_QUEUE_MAX_READY_IMPORT"),
            ("image_pipeline", "TASK_QUEUE_MAX_READY_IMPORT"),
            ("excel_pipeline", "TASK_QUEUE_MAX_READY_IMPORT"),
            ("resume_pipeline", "TASK_QUEUE_MAX_READY_IMPORT"),
            ("admin_resume", "TASK_QUEUE_MAX_READY_IMPORT"),
            ("ocr_pipeline", "TASK_QUEUE_MAX_READY_OCR"),
            ("prewarm_analysis", "TASK_QUEUE_MAX_READY_AI"),
            ("error_diagnosis", "TASK_QUEUE_MAX_READY_AI"),
            ("formula_batch", "TASK_QUEUE_MAX_READY_FORMULA"),
            ("batch_image", "TASK_QUEUE_MAX_READY_BATCH_IMAGE"),
            ("answer_projection", "TASK_QUEUE_MAX_READY_ANSWER_PROJECTION"),
            ("unknown_task", "TASK_QUEUE_MAX_READY_DEFAULT"),
        ],
    )
    def test_task_type_uses_its_configured_limit(
        self, monkeypatch, task_type, setting_name
    ):
        monkeypatch.setattr(settings, setting_name, 37)

        assert _get_max_ready(task_type) == 37

    def test_limit_is_read_from_current_settings_not_cached(self, monkeypatch):
        monkeypatch.setattr(settings, "TASK_QUEUE_MAX_READY_DEFAULT", 11)

        assert _get_max_ready("new-task-type") == 11
