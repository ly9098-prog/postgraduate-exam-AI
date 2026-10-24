"""Real compatibility baseline for task health observability rules."""

from __future__ import annotations

import pytest

from app.services.task_observability_rules import evaluate_task_health


def _healthy_inputs():
    return {
        "outbox": {"oldest_unpublished_seconds": 0, "counts": {"failed": 0}},
        "redis": {"configured": True, "available": True, "oldest_ready_seconds": 0, "totals": {"dead": 0, "corrupt": 0}, "memory": {"max_bytes": 1000000, "used_bytes": 100, "evicted_keys": 0}},
        "projection": {"unprojected": 0},
        "async_runtime_expected": True,
    }


class TestEvaluateTaskHealth:
    def test_healthy_returns_ok(self):
        result = evaluate_task_health(**_healthy_inputs())
        assert result["ok"] is True
        assert result["severity"] == "ok"
        assert result["issues"] == []

    def test_redis_not_configured(self):
        inputs = _healthy_inputs()
        inputs["redis"]["configured"] = False
        result = evaluate_task_health(**inputs)
        assert result["ok"] is False
        codes = [i["code"] for i in result["issues"]]
        assert "REDIS_NOT_CONFIGURED" in codes

    def test_redis_unavailable(self):
        inputs = _healthy_inputs()
        inputs["redis"]["available"] = False
        result = evaluate_task_health(**inputs)
        assert result["ok"] is False
        codes = [i["code"] for i in result["issues"]]
        assert "REDIS_UNAVAILABLE" in codes

    def test_async_not_expected_no_redis_checks(self):
        inputs = _healthy_inputs()
        inputs["async_runtime_expected"] = False
        inputs["redis"]["configured"] = False
        result = evaluate_task_health(**inputs)
        codes = [i["code"] for i in result["issues"]]
        assert "REDIS_NOT_CONFIGURED" not in codes

    def test_outbox_stalled(self):
        inputs = _healthy_inputs()
        inputs["outbox"]["oldest_unpublished_seconds"] = 999999
        result = evaluate_task_health(**inputs)
        assert result["ok"] is False
        codes = [i["code"] for i in result["issues"]]
        assert "OUTBOX_STALLED" in codes

    def test_queue_stalled(self):
        inputs = _healthy_inputs()
        inputs["redis"]["oldest_ready_seconds"] = 999999
        result = evaluate_task_health(**inputs)
        assert result["ok"] is False
        codes = [i["code"] for i in result["issues"]]
        assert "QUEUE_STALLED" in codes

    def test_deadletter_high(self):
        inputs = _healthy_inputs()
        inputs["redis"]["totals"]["dead"] = 999
        result = evaluate_task_health(**inputs)
        assert result["ok"] is False
        codes = [i["code"] for i in result["issues"]]
        assert "TASK_DEADLETTER_HIGH" in codes

    def test_projection_backlog(self):
        inputs = _healthy_inputs()
        inputs["projection"]["unprojected"] = 999
        result = evaluate_task_health(**inputs)
        assert result["ok"] is False
        codes = [i["code"] for i in result["issues"]]
        assert "ANSWER_PROJECTION_BACKLOG_HIGH" in codes

    def test_outbox_failed(self):
        inputs = _healthy_inputs()
        inputs["outbox"]["counts"]["failed"] = 999
        result = evaluate_task_health(**inputs)
        assert result["ok"] is False
        codes = [i["code"] for i in result["issues"]]
        assert "OUTBOX_FAILED_HIGH" in codes

    def test_warning_severity(self):
        inputs = _healthy_inputs()
        inputs["outbox"]["counts"]["failed"] = 1
        result = evaluate_task_health(**inputs)
        assert result["severity"] in ("warning", "ok")

    def test_issues_have_required_fields(self):
        inputs = _healthy_inputs()
        inputs["redis"]["available"] = False
        result = evaluate_task_health(**inputs)
        for issue in result["issues"]:
            assert "code" in issue
            assert "severity" in issue
            assert "message" in issue
