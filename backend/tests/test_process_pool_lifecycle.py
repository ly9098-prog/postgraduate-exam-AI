"""Tests for process pool lifecycle management.

Covers:
1. Formula render pool (lazy init, shutdown, timeout recycle, idempotency)
2. OCR process pool (shutdown, reset, crash recovery, new-submission rejection)
3. Multiprocessing resource leak detection (active_children after shutdown)
"""

from __future__ import annotations

import concurrent.futures
import multiprocessing
import os
import signal
import threading
import time
from unittest.mock import MagicMock, PropertyMock, patch

import pytest


# Module-level helper for ProcessPoolExecutor (must be picklable)
def _return_42():
    return 42


def _sleep_forever():
    while True:
        time.sleep(10)


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _reset_formula_pool_state():
    """Reset formula render pool global state before each test.

    Ensures tests are isolated from each other even though the
    pool is a module-level singleton.
    """
    import app.services.formula_graph_spec_renderer as rnd

    rnd._process_pool = None
    rnd._pool_stopping = False
    rnd._pool_generation = 0
    yield
    # Teardown: shut down any pool that was created
    if rnd._process_pool is not None:
        rnd.shutdown_formula_render_pool(wait=False, cancel_futures=True)
    rnd._process_pool = None
    rnd._pool_stopping = False


# ═══════════════════════════════════════════════════════════════
# Formula render pool lifecycle tests
# ═══════════════════════════════════════════════════════════════

class TestFormulaRenderPoolLifecycle:
    """Test lazy init, shutdown, and timeout handling."""

    def test_pool_not_created_on_import(self):
        """Pool is NOT created when module is imported."""
        import app.services.formula_graph_spec_renderer as rnd

        assert rnd._process_pool is None

    def test_pool_created_on_first_get(self):
        """Pool is created when get_formula_render_pool() is first called."""
        import app.services.formula_graph_spec_renderer as rnd

        pool = rnd.get_formula_render_pool()

        assert pool is not None
        assert isinstance(pool, concurrent.futures.ProcessPoolExecutor)
        assert rnd._process_pool is pool
        assert rnd._pool_generation == 1

    def test_get_returns_same_pool(self):
        """Multiple calls to get_formula_render_pool return the same pool."""
        import app.services.formula_graph_spec_renderer as rnd

        pool1 = rnd.get_formula_render_pool()
        pool2 = rnd.get_formula_render_pool()

        assert pool1 is pool2
        assert rnd._pool_generation == 1

    def test_concurrent_get_creates_one_pool(self):
        """Concurrent calls to get_formula_render_pool create only one pool."""
        import app.services.formula_graph_spec_renderer as rnd

        results = []
        errors = []

        def _get():
            try:
                p = rnd.get_formula_render_pool()
                results.append(id(p))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_get) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(set(results)) == 1
        assert rnd._pool_generation == 1

    def test_shutdown_sets_pool_to_none(self):
        """After shutdown, _process_pool is None."""
        import app.services.formula_graph_spec_renderer as rnd

        rnd.get_formula_render_pool()
        rnd.shutdown_formula_render_pool(wait=False, cancel_futures=True)

        assert rnd._process_pool is None

    def test_shutdown_is_idempotent(self):
        """Calling shutdown twice does not raise."""
        import app.services.formula_graph_spec_renderer as rnd

        rnd.get_formula_render_pool()
        rnd.shutdown_formula_render_pool(wait=False, cancel_futures=True)
        rnd.shutdown_formula_render_pool(wait=False, cancel_futures=True)

    def test_new_pool_after_shutdown_and_reset(self):
        """After shutdown + reset, a new pool can be created."""
        import app.services.formula_graph_spec_renderer as rnd

        pool1 = rnd.get_formula_render_pool()
        rnd.shutdown_formula_render_pool(wait=False, cancel_futures=True)
        rnd.reset_formula_render_pool()

        pool2 = rnd.get_formula_render_pool()
        assert pool2 is not pool1
        assert rnd._pool_generation == 2

    def test_shutdown_blocks_new_submissions(self):
        """After shutdown without reset, get_formula_render_pool raises."""
        import app.services.formula_graph_spec_renderer as rnd

        rnd.get_formula_render_pool()
        rnd.shutdown_formula_render_pool(wait=False, cancel_futures=True)

        with pytest.raises(RuntimeError, match="shutting down"):
            rnd.get_formula_render_pool()

    def test_no_active_children_after_shutdown(self):
        """After pool shutdown, no child processes remain."""
        import app.services.formula_graph_spec_renderer as rnd

        rnd.get_formula_render_pool()
        pool = rnd.get_formula_render_pool()

        # Submit a module-level function (picklable) to start a worker
        future = pool.submit(_return_42)
        assert future.result(timeout=10) == 42

        rnd.shutdown_formula_render_pool(wait=True, cancel_futures=True)

        children = multiprocessing.active_children()
        assert len(children) == 0


# ═══════════════════════════════════════════════════════════════
# OCR process pool lifecycle tests
# ═══════════════════════════════════════════════════════════════

class TestOcrProcessPoolLifecycle:
    """Test OCR process pool shutdown, reset, and crash recovery.

    These tests focus on the pool's Python-level lifecycle logic
    (ensure, shutdown, reset, _shutdown_nonblocking) rather than
    actual subprocess execution, since mock objects cannot be
    pickled across process boundaries.
    """

    @pytest.fixture(autouse=True)
    def _reset_ocr_pool(self):
        import app.core.ocr_process_pool as opp

        opp.ocr_process_pool.shutdown()
        opp.ocr_process_pool._shut_down = False
        opp.ocr_process_pool._executor = None
        opp.ocr_process_pool._spawn_count = 0
        yield

    def test_no_executor_before_first_submit(self):
        import app.core.ocr_process_pool as opp

        assert opp.ocr_process_pool._executor is None

    def test_ensure_creates_executor(self):
        import app.core.ocr_process_pool as opp

        executor = opp.ocr_process_pool._ensure()
        assert executor is not None
        assert opp.ocr_process_pool._spawn_count == 1

    def test_shutdown_sets_shut_down_and_none_executor(self):
        import app.core.ocr_process_pool as opp

        opp.ocr_process_pool._ensure()
        opp.ocr_process_pool.shutdown()

        assert opp.ocr_process_pool._shut_down is True
        assert opp.ocr_process_pool._executor is None

    def test_ensure_after_shutdown_raises(self):
        import app.core.ocr_process_pool as opp

        opp.ocr_process_pool._ensure()
        opp.ocr_process_pool.shutdown()

        with pytest.raises(RuntimeError, match="has been shut down"):
            opp.ocr_process_pool._ensure()

    def test_reset_reenables_ensure(self):
        import app.core.ocr_process_pool as opp

        opp.ocr_process_pool._ensure()
        opp.ocr_process_pool.shutdown()
        opp.ocr_process_pool.reset()

        assert opp.ocr_process_pool._shut_down is False
        executor = opp.ocr_process_pool._ensure()
        assert executor is not None

    def test_shutdown_nonblocking_clears_executor_no_shut_down(self):
        import app.core.ocr_process_pool as opp

        opp.ocr_process_pool._ensure()
        opp.ocr_process_pool._shutdown_nonblocking()

        assert opp.ocr_process_pool._executor is None
        assert opp.ocr_process_pool._shut_down is False
        # Re-creation is allowed
        executor = opp.ocr_process_pool._ensure()
        assert executor is not None

    def test_shutdown_idempotent(self):
        import app.core.ocr_process_pool as opp

        opp.ocr_process_pool.shutdown()
        opp.ocr_process_pool.shutdown()

    def test_stats_after_operations(self):
        import app.core.ocr_process_pool as opp

        opp.ocr_process_pool._ensure()
        opp.ocr_process_pool.shutdown()

        stats = opp.ocr_process_pool.stats
        assert stats["spawn_count"] == 1
        assert stats["alive"] is False

    def test_submit_after_shutdown_raises(self):
        """Direct test: submit() raises RuntimeError after shutdown."""
        import app.core.ocr_process_pool as opp

        opp.ocr_process_pool._ensure()
        opp.ocr_process_pool.shutdown()

        with pytest.raises(RuntimeError, match="has been shut down"):
            opp.ocr_process_pool.submit(b"dummy")


# ═══════════════════════════════════════════════════════════════
# OCR executor service tests
# ═══════════════════════════════════════════════════════════════

class TestOcrExecutorServiceShutdown:
    """Test that ocr_executor.shutdown() actually calls the pool."""

    @pytest.mark.asyncio
    @patch("app.services.ocr_executor_service.asyncio.to_thread")
    async def test_shutdown_calls_pool_shutdown(self, mock_to_thread):
        from app.services.ocr_executor_service import ocr_executor

        ocr_executor._shutdown = False
        await ocr_executor.shutdown(wait=True)

        assert ocr_executor._shutdown is True
        mock_to_thread.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.services.ocr_executor_service.asyncio.to_thread")
    async def test_shutdown_sets_flag(self, mock_to_thread):
        from app.services.ocr_executor_service import ocr_executor

        ocr_executor._shutdown = False
        await ocr_executor.shutdown(wait=True)

        assert ocr_executor._shutdown is True

    @pytest.mark.asyncio
    @patch("app.services.ocr_executor_service.asyncio.to_thread")
    async def test_shutdown_idempotent(self, mock_to_thread):
        from app.services.ocr_executor_service import ocr_executor

        await ocr_executor.shutdown(wait=True)
        await ocr_executor.shutdown(wait=True)


# ═══════════════════════════════════════════════════════════════
# Resource leak detection helpers
# ═══════════════════════════════════════════════════════════════

class TestActiveChildrenCheck:
    """Diagnostic helpers: multiprocessing.active_children() should be empty."""

    def test_active_children_empty_after_clean_shutdown(self):
        import app.services.formula_graph_spec_renderer as rnd

        # Create pool and submit a simple picklable task
        pool = rnd.get_formula_render_pool()
        future = pool.submit(_return_42)
        assert future.result(timeout=10) == 42

        rnd.shutdown_formula_render_pool(wait=True, cancel_futures=True)

        children = multiprocessing.active_children()
        assert len(children) == 0
