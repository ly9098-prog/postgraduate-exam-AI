"""Real compatibility baseline for task queue metrics formatting."""

from __future__ import annotations

import pytest

from app.services.task_queue_metrics import append_queue_counters


class TestAppendQueueCounters:
    def test_empty_metrics_outputs_zeros(self):
        lines: list[str] = []
        append_queue_counters(lines, {})
        assert len(lines) == 7
        for line in lines:
            assert line.endswith(" 0")

    def test_all_metrics_present(self):
        metrics = {
            "lease_renewal_failure": 5,
            "duplicate_enqueue_prevented": 10,
            "reaper_reclaimed": 3,
            "owner_fencing_rejected": 2,
            "enqueue_rejected": 1,
            "dead_purge_count": 7,
            "corrupt_cleaned": 4,
        }
        lines: list[str] = []
        append_queue_counters(lines, metrics)
        assert len(lines) == 7
        assert "task_queue_lease_renewal_failure 5" in lines
        assert "task_queue_corrupt_cleaned 4" in lines

    def test_partial_metrics(self):
        metrics = {"lease_renewal_failure": 5}
        lines: list[str] = []
        append_queue_counters(lines, metrics)
        assert "task_queue_lease_renewal_failure 5" in lines
        assert "task_queue_reaper_reclaimed 0" in lines

    def test_extra_metrics_ignored(self):
        metrics = {"lease_renewal_failure": 5, "unknown_metric": 999}
        lines: list[str] = []
        append_queue_counters(lines, metrics)
        assert len(lines) == 7
        assert not any("unknown_metric" in line for line in lines)

    def test_lines_appended_to_existing_list(self):
        lines = ["existing_line"]
        append_queue_counters(lines, {})
        assert len(lines) == 8
        assert lines[0] == "existing_line"
