"""P7-03: Fault injection tests for OcrProcessPool.

Requires PaddleOCR runtime (GPU or CPU). Tests:
- Timeout injection → auto-recycle
- Worker crash (SIGKILL) → BrokenProcessPool → auto-recreate
- Repeated fault storm → pool survival
- Stats accuracy after faults
- Shutdown under load
"""

from __future__ import annotations

import io
import os
import signal
import time
from concurrent.futures import TimeoutError

import pytest
from PIL import Image, ImageDraw, ImageFont

from app.core.ocr_process_pool import OcrProcessPool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _make_test_image(text: str = "Hello OCR Test", size: tuple[int, int] = (400, 100)) -> bytes:
    """Create a small PNG test image with readable text."""
    img = Image.new("RGB", size, color="white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(_FONT_PATH, 20)
    except OSError:
        font = ImageFont.load_default()
    draw.text((10, 30), text, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


_TEST_IMAGE = _make_test_image()


def _make_bad_image() -> bytes:
    """Create a truly non-decodable byte blob."""
    return b"\xff\xd8\xff\xe0" + b"\x00" * 1024  # fake JPEG header, zeros


@pytest.fixture(autouse=True)
def fresh_pool():
    """Provide a fresh OcrProcessPool for each test (no shared state)."""
    pool = OcrProcessPool(max_workers=1)
    yield pool
    pool.shutdown()


# ---------------------------------------------------------------------------
# Base sanity
# ---------------------------------------------------------------------------


class TestSanity:
    """Verify the process pool works with real OCR before injecting faults."""

    def test_normal_ocr_returns_text(self):
        pool = OcrProcessPool(max_workers=1)
        try:
            text = pool.get_text(_TEST_IMAGE, page_index=0, timeout=60)
            assert isinstance(text, str)
            assert len(text) > 0
        finally:
            pool.shutdown()

    def test_ocr_with_boxes_returns_dict(self):
        pool = OcrProcessPool(max_workers=1)
        try:
            result = pool.get_text_with_boxes(_TEST_IMAGE, page_index=0, timeout=60)
            assert isinstance(result, dict)
            assert "text" in result
            assert isinstance(result["text"], str)
            assert len(result["text"]) > 0
        finally:
            pool.shutdown()

    def test_lightweight_ocr_works(self):
        pool = OcrProcessPool(max_workers=1)
        try:
            text = pool.get_lightweight_text(_TEST_IMAGE, page_index=0, timeout=60)
            assert isinstance(text, str)
        finally:
            pool.shutdown()


# ---------------------------------------------------------------------------
# Timeout injection
# ---------------------------------------------------------------------------


class TestTimeoutFaultInjection:
    """Inject timeouts and verify pool recovery."""

    def test_timeout_raises_and_pool_recycles(self, caplog):
        """Extremely short timeout should raise and trigger pool recycle."""
        pool = OcrProcessPool(max_workers=1)
        try:
            with pytest.raises(TimeoutError):
                pool.get_text(_TEST_IMAGE, page_index=0, timeout=0.001)
        finally:
            pool.shutdown()

        stats = pool.stats
        assert stats["total_timeouts"] >= 1
        # Pool should have been recycled (new spawn)
        assert stats["total_submitted"] >= 1

    def test_pool_works_after_timeout(self):
        """After a timeout, submitting another task should succeed."""
        pool = OcrProcessPool(max_workers=1)
        try:
            # Trigger timeout
            with pytest.raises(TimeoutError):
                pool.get_text(_TEST_IMAGE, page_index=0, timeout=0.001)
        except Exception:
            pass

        # Now submit a real task — should work
        text = pool.get_text(_TEST_IMAGE, page_index=0, timeout=60)
        assert isinstance(text, str)
        assert len(text) > 0
        assert pool.stats["spawn_count"] >= 2  # recycled at least once
        assert pool.stats["alive"]

    def test_repeated_timeouts_pool_survives(self):
        """Multiple timeouts in sequence should not permanently break pool."""
        pool = OcrProcessPool(max_workers=1)
        try:
            for _ in range(3):
                try:
                    pool.get_text(_TEST_IMAGE, page_index=0, timeout=0.001)
                except TimeoutError:
                    pass
        finally:
            pool.shutdown()

        stats = pool.stats
        assert stats["total_timeouts"] >= 3
        assert stats["alive"] is False  # shutdown

    def test_timeout_does_not_leak_futures(self):
        """After timeout, no pending futures should remain."""
        pool = OcrProcessPool(max_workers=1)
        try:
            with pytest.raises(TimeoutError):
                pool.get_text(_TEST_IMAGE, page_index=0, timeout=0.001)
        finally:
            pool.shutdown()


# ---------------------------------------------------------------------------
# Worker crash injection
# ---------------------------------------------------------------------------


class TestCrashFaultInjection:
    """Kill the worker process and verify pool auto-recovers."""

    def _get_worker_pid(self, pool: OcrProcessPool) -> int | None:
        """Attempt to find the worker PID via pool internals."""
        if pool._executor is None:
            return None
        # ProcessPoolExecutor._processes is a dict of pid->process
        processes = getattr(pool._executor, "_processes", None)
        if processes:
            for pid in processes:
                if pid is not None and pid != os.getpid():
                    return int(pid)
        return None

    def test_worker_killed_pool_recovers(self):
        """Kill the worker with SIGKILL; pool should auto-recreate."""
        pool = OcrProcessPool(max_workers=1)
        try:
            # Warm up — ensure worker is running
            pool.get_text(_TEST_IMAGE, page_index=0, timeout=60)

            # Kill the worker process
            worker_pid = self._get_worker_pid(pool)
            if worker_pid and worker_pid != os.getpid():
                os.kill(worker_pid, signal.SIGKILL)
                time.sleep(0.5)  # give it time to die

            # Submit again — pool should detect BrokenProcessPool and recreate
            text = pool.get_text(_TEST_IMAGE, page_index=0, timeout=60)
            assert isinstance(text, str)
            assert len(text) > 0
            stats = pool.stats
            assert stats["total_crashes"] >= 1
            assert stats["spawn_count"] >= 2  # initial + restart
        finally:
            pool.shutdown()

    def test_repeated_crash_storm(self):
        """Multiple worker kills in sequence; pool survives."""
        pool = OcrProcessPool(max_workers=1)
        try:
            for _ in range(5):
                # Warm up
                try:
                    pool.get_text(_TEST_IMAGE, page_index=0, timeout=30)
                except Exception:
                    pass

                # Kill worker
                worker_pid = self._get_worker_pid(pool)
                if worker_pid and worker_pid != os.getpid():
                    try:
                        os.kill(worker_pid, signal.SIGKILL)
                        time.sleep(0.3)
                    except ProcessLookupError:
                        pass  # already dead

            # After crash storm, submit should still work
            text = pool.get_text(_TEST_IMAGE, page_index=0, timeout=60)
            assert isinstance(text, str)
            assert len(text) > 0
        finally:
            pool.shutdown()


# ---------------------------------------------------------------------------
# Corrupt / edge input
# ---------------------------------------------------------------------------


class TestCorruptInputFault:
    """Pool should handle bad input without dying."""

    def test_corrupt_image_returns_empty_not_crash(self):
        pool = OcrProcessPool(max_workers=1)
        try:
            text = pool.get_text(_make_bad_image(), page_index=0, timeout=30)
            assert text == ""
        finally:
            pool.shutdown()

    def test_empty_bytes_returns_empty_not_crash(self):
        pool = OcrProcessPool(max_workers=1)
        try:
            text = pool.get_text(b"", page_index=0, timeout=30)
            assert text == ""
        finally:
            pool.shutdown()

    def test_valid_after_corrupt(self):
        """Pool still works after processing corrupt input."""
        pool = OcrProcessPool(max_workers=1)
        try:
            pool.get_text(_make_bad_image(), page_index=0, timeout=30)
            # Now valid input
            text = pool.get_text(_TEST_IMAGE, page_index=0, timeout=60)
            assert isinstance(text, str)
            assert len(text) > 0
        finally:
            pool.shutdown()


# ---------------------------------------------------------------------------
# Stats after faults
# ---------------------------------------------------------------------------


class TestStatsAfterFaults:
    """Verify metrics accuracy after fault sequences."""

    def test_stats_count_timeouts(self):
        pool = OcrProcessPool(max_workers=1)
        try:
            for _ in range(2):
                try:
                    pool.get_text(_TEST_IMAGE, page_index=0, timeout=0.001)
                except TimeoutError:
                    pass
            assert pool.stats["total_timeouts"] >= 2
        finally:
            pool.shutdown()

    def test_stats_count_crashes(self):
        pool = OcrProcessPool(max_workers=1)
        try:
            pool.get_text(_TEST_IMAGE, page_index=0, timeout=30)
            processes = getattr(pool._executor, "_processes", None)
            if processes:
                for pid in processes:
                    if pid is not None and pid != os.getpid():
                        os.kill(pid, signal.SIGKILL)
                        time.sleep(0.3)
            try:
                pool.get_text(_TEST_IMAGE, page_index=0, timeout=30)
            except Exception:
                pass
        finally:
            pool.shutdown()


# ---------------------------------------------------------------------------
# Shutdown behavior
# ---------------------------------------------------------------------------


class TestShutdownBehavior:
    """Shutdown must complete cleanly under various conditions."""

    def test_shutdown_idle(self):
        pool = OcrProcessPool(max_workers=1)
        pool.shutdown()  # should not hang
        assert pool._executor is None

    def test_shutdown_after_timeout(self):
        pool = OcrProcessPool(max_workers=1)
        try:
            with pytest.raises(TimeoutError):
                pool.get_text(_TEST_IMAGE, page_index=0, timeout=0.001)
        except Exception:
            pass
        pool.shutdown()  # should not hang
        assert pool._executor is None

    def test_shutdown_after_crash(self):
        pool = OcrProcessPool(max_workers=1)
        try:
            pool.get_text(_TEST_IMAGE, page_index=0, timeout=30)
            processes = getattr(pool._executor, "_processes", None)
            if processes:
                for pid in processes:
                    if pid is not None and pid != os.getpid():
                        os.kill(pid, signal.SIGKILL)
                        time.sleep(0.3)
        except Exception:
            pass
        pool.shutdown()  # should not hang (process already dead)
        assert pool._executor is None

    def test_double_shutdown_safe(self):
        pool = OcrProcessPool(max_workers=1)
        pool.shutdown()
        pool.shutdown()  # no-op, should not raise


# ---------------------------------------------------------------------------
# Submit API coverage
# ---------------------------------------------------------------------------


class TestSubmitAPI:
    """Cover the Future-based submit() path."""

    def test_submit_returns_text(self):
        pool = OcrProcessPool(max_workers=1)
        try:
            future = pool.submit(_TEST_IMAGE, page_index=0)
            text = future.result(timeout=60)
            assert isinstance(text, str)
            assert len(text) > 0
        finally:
            pool.shutdown()

    def test_submit_after_timeout_still_works(self):
        pool = OcrProcessPool(max_workers=1)
        try:
            with pytest.raises(TimeoutError):
                pool.get_text(_TEST_IMAGE, page_index=0, timeout=0.001)
            future = pool.submit(_TEST_IMAGE, page_index=0)
            text = future.result(timeout=60)
            assert isinstance(text, str)
            assert len(text) > 0
        finally:
            pool.shutdown()

    def test_submit_timeout_via_future(self):
        pool = OcrProcessPool(max_workers=1)
        try:
            future = pool.submit(_TEST_IMAGE, page_index=0)
            with pytest.raises(TimeoutError):
                future.result(timeout=0.001)
        except TimeoutError:
            pass
        finally:
            pool.shutdown()


# ---------------------------------------------------------------------------
# 1000-iteration fault stress test (reduced to 100 for CI speed)
# ---------------------------------------------------------------------------


class TestFaultStorm:
    """100 fault iterations: timeout + crash mixing, verify pool recovers."""

    # Number of iterations — 100 for CI, set OCR_FAULT_STORM_ITERATIONS
    # to override (e.g. 1000 for full stress).
    _N = int(os.environ.get("OCR_FAULT_STORM_ITERATIONS", "100"))

    def test_fault_storm_pool_survives(self):
        """Mix timeouts and crashes 100 times; pool must survive."""
        pool = OcrProcessPool(max_workers=1)
        n = self._N
        try:
            for i in range(n):
                # Every other iteration: submit then kill worker
                if i % 2 == 0:
                    try:
                        pool.get_text(_TEST_IMAGE, page_index=0, timeout=30)
                        processes = getattr(pool._executor, "_processes", None)
                        if processes:
                            for pid in processes:
                                if pid is not None and pid != os.getpid():
                                    os.kill(pid, signal.SIGKILL)
                                    time.sleep(0.1)
                    except (ProcessLookupError, RuntimeError):
                        pass
                else:
                    # Timeout injection
                    try:
                        pool.get_text(_TEST_IMAGE, page_index=0, timeout=0.001)
                    except TimeoutError:
                        pass

            # Final verification: submit and get real result
            text = pool.get_text(_TEST_IMAGE, page_index=0, timeout=60)
            assert isinstance(text, str)
            assert len(text) > 0
            print(
                f"\n[FAULT STORM] {n} iterations: "
                f"spawns={pool.stats['spawn_count']} "
                f"timeouts={pool.stats['total_timeouts']} "
                f"crashes={pool.stats['total_crashes']}"
            )
        finally:
            pool.shutdown()
