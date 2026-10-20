"""Characterize lag measurement and ResourceGuard consumption before migration."""

import asyncio
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import event_loop_health as health
from app.core.resource_guard import ResourceGuard


@pytest.mark.asyncio
@pytest.mark.parametrize("interval,actual,expected", [
    (1.0, 11.125678, 125.68), (0.25, 10.249, -1.0), (0.0, 10.01, 10.0),
])
async def test_monitor_publishes_after_sleep_and_keeps_last_sample_on_cancel(
    monkeypatch, interval, actual, expected
):
    monkeypatch.setattr(health.event_loop_health, "lag_ms", 7.0)
    ticks = iter([10.0, actual, 20.0])
    monkeypatch.setattr(health, "time", SimpleNamespace(perf_counter=lambda: next(ticks)))
    observations = []

    async def sleep(delay):
        observations.append((delay, health.event_loop_health.lag_ms))
        if len(observations) == 2:
            raise asyncio.CancelledError()

    monkeypatch.setattr(health, "asyncio", SimpleNamespace(sleep=sleep))
    with pytest.raises(asyncio.CancelledError):
        await health.monitor_event_loop_lag(health.event_loop_health, interval)
    assert observations == [(interval, 7.0), (interval, expected)]
    assert health.event_loop_health.lag_ms == expected


@pytest.mark.asyncio
async def test_monitor_sleep_failure_does_not_publish_a_new_value(monkeypatch):
    monkeypatch.setattr(health.event_loop_health, "lag_ms", 12.0)
    monkeypatch.setattr(health, "time", SimpleNamespace(perf_counter=lambda: 10.0))
    failure = RuntimeError("synthetic sleep failure")

    async def sleep(_delay):
        raise failure

    monkeypatch.setattr(health, "asyncio", SimpleNamespace(sleep=sleep))
    with pytest.raises(RuntimeError) as caught:
        await health.monitor_event_loop_lag(health.event_loop_health)
    assert caught.value is failure
    assert health.event_loop_health.lag_ms == 12.0


@pytest.mark.parametrize("lag", [0.0, 123.45, 501.0])
def test_resource_guard_reads_the_published_lag(monkeypatch, lag):
    monkeypatch.setattr(health.event_loop_health, "lag_ms", lag)
    monkeypatch.setattr(ResourceGuard, "_managed_temp_paths", lambda: ([], "/tmp"))
    assert ResourceGuard._collect_system_metrics().event_loop_lag_ms == lag


def test_resource_guard_defaults_to_zero_without_http_module(monkeypatch):
    monkeypatch.delitem(sys.modules, "app.main", raising=False)
    monkeypatch.setattr(health.event_loop_health, "lag_ms", 0.0)
    monkeypatch.setattr(ResourceGuard, "_managed_temp_paths", lambda: ([], "/tmp"))
    assert ResourceGuard._collect_system_metrics().event_loop_lag_ms == 0.0


@pytest.mark.asyncio
async def test_real_task_cancellation_preserves_last_sample_and_does_not_spawn_tasks(monkeypatch):
    state = health.EventLoopHealth()
    monkeypatch.setattr(health.event_loop_health, "lag_ms", 0.0)
    ticks = iter([10.0, 11.25, 20.0])
    monkeypatch.setattr(health, "time", SimpleNamespace(perf_counter=lambda: next(ticks)))
    sampled = asyncio.Event()
    blocker = asyncio.Event()
    sleeps = []

    async def sleep(delay):
        sleeps.append(delay)
        if len(sleeps) == 2:
            sampled.set()
            await blocker.wait()

    monkeypatch.setattr(health, "asyncio", SimpleNamespace(sleep=sleep))
    before = asyncio.all_tasks()
    task = asyncio.create_task(health.monitor_event_loop_lag(state), name="synthetic-lag-monitor")
    try:
        await asyncio.wait_for(sampled.wait(), timeout=1)
        assert state.lag_ms == 250.0
        assert ResourceGuard._collect_system_metrics().event_loop_lag_ms != state.lag_ms
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert state.lag_ms == 250.0
        assert sleeps == [1.0, 1.0]
        assert asyncio.all_tasks() <= before
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


def test_resource_guard_import_without_http_application_uses_zero_sample():
    probe = """
import sys
from app.core.resource_guard import ResourceGuard
from app.core.event_loop_health import event_loop_health
assert 'app.main' not in sys.modules
ResourceGuard._managed_temp_paths = staticmethod(lambda: ([], '/tmp'))
assert event_loop_health.lag_ms == 0.0
assert ResourceGuard._collect_system_metrics().event_loop_lag_ms == 0.0
assert 'app.main' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=Path(__file__).resolve().parents[2],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
