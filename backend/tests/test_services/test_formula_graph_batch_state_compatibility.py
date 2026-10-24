"""Real compatibility baseline for formula graph batch state pure functions.

Covers ``_cleanup_old_jobs`` (oldest completed job eviction) and
``get_batch_status`` (in-process status lookup).
"""

from __future__ import annotations

import pytest

from app.services import formula_graph_batch_state as batch_state


@pytest.fixture(autouse=True)
def _reset_jobs():
    """Clear the module-level jobs dict before each test."""
    batch_state.jobs.clear()
    yield
    batch_state.jobs.clear()


class TestCleanupOldJobs:
    def test_no_op_when_under_limit(self):
        batch_state.jobs["a"] = {"status": "completed", "finished_at": "1"}
        batch_state._cleanup_old_jobs(max_keep=10)
        assert "a" in batch_state.jobs

    def test_evicts_oldest_completed(self):
        batch_state.jobs["old"] = {"status": "completed", "finished_at": "1"}
        batch_state.jobs["new"] = {"status": "completed", "finished_at": "2"}
        batch_state._cleanup_old_jobs(max_keep=1)
        assert "old" not in batch_state.jobs
        assert "new" in batch_state.jobs

    def test_preserves_running_jobs(self):
        batch_state.jobs["running"] = {"status": "running", "finished_at": ""}
        batch_state.jobs["done1"] = {"status": "completed", "finished_at": "1"}
        batch_state.jobs["done2"] = {"status": "completed", "finished_at": "2"}
        batch_state._cleanup_old_jobs(max_keep=1)
        assert "running" in batch_state.jobs

    def test_evicts_by_finished_at_order(self):
        for i in range(5):
            batch_state.jobs[f"job{i}"] = {
                "status": "completed",
                "finished_at": str(i),
            }
        batch_state._cleanup_old_jobs(max_keep=2)
        remaining = sorted(batch_state.jobs.keys())
        assert remaining == ["job3", "job4"]

    def test_handles_partial_failed_status(self):
        batch_state.jobs["pf"] = {"status": "partial_failed", "finished_at": "1"}
        batch_state.jobs["ok"] = {"status": "completed", "finished_at": "2"}
        batch_state._cleanup_old_jobs(max_keep=1)
        assert "pf" not in batch_state.jobs
        assert "ok" in batch_state.jobs

    def test_handles_failed_status(self):
        batch_state.jobs["f"] = {"status": "failed", "finished_at": "1"}
        batch_state.jobs["ok"] = {"status": "completed", "finished_at": "2"}
        batch_state._cleanup_old_jobs(max_keep=1)
        assert "f" not in batch_state.jobs

    def test_empty_dict_no_op(self):
        batch_state._cleanup_old_jobs(max_keep=0)
        assert len(batch_state.jobs) == 0


class TestGetBatchStatus:
    @pytest.mark.asyncio
    async def test_returns_none_for_missing(self):
        result = await batch_state.get_batch_status("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_status_for_existing(self):
        batch_state.jobs["abc"] = {"status": "completed", "progress": 100}
        result = await batch_state.get_batch_status("abc")
        assert result is not None
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_returns_none_after_cleanup(self):
        batch_state.jobs["old"] = {"status": "completed", "finished_at": "1"}
        batch_state._cleanup_old_jobs(max_keep=0)
        result = await batch_state.get_batch_status("old")
        assert result is None
