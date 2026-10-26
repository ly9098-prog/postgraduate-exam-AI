"""Failure-path safety of the private service harness, using only owned children."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy.engine import make_url

from tests.integration import owned_worker as worker_module
from tests.integration.owned_process import (
    capture_owned_children,
    private_environment,
    stop_owned_group,
)
from tests.integration.owned_worker import OwnedWorker

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def services(monkeypatch):
    monkeypatch.setenv("PARENT_SENTINEL_CREDENTIAL", "synthetic-parent-only")
    monkeypatch.setenv("PGPASSWORD", "synthetic-parent-only")
    runtime = OwnedWorker()
    try:
        await runtime.start_services()
        yield runtime
    finally:
        await runtime.stop()


def assert_no_parent_credentials(child):
    entries = Path(f"/proc/{child.pid}/environ").read_bytes().split(b"\0")
    assert not any(
        entry.startswith((b"PARENT_SENTINEL_CREDENTIAL=", b"PGPASSWORD="))
        for entry in entries
    )


async def test_stopped_pg_backend_is_removed_even_when_fast_stop_fails(services):
    runtime = services
    pg = runtime.postgres
    assert_no_parent_credentials(pg.process)
    assert_no_parent_credentials(runtime.redis.process)
    url = make_url(pg.url)
    connection = await asyncpg.connect(
        host=str(pg.socket),
        user=url.username,
        database=url.database,
        timeout=2,
    )
    try:
        backend = await connection.fetchval("SELECT pg_backend_pid()")
        assert backend in capture_owned_children(pg.process)
        os.kill(backend, signal.SIGSTOP)
        with pytest.raises(subprocess.CalledProcessError):
            await asyncio.to_thread(pg.stop)
        assert pg.process.poll() is not None
        assert capture_owned_children(pg.process) == []
        runtime.record(
            "verified", scenario="stopped-pg-backend-cleanup", backend=backend
        )
    finally:
        connection.terminate()


async def test_cleanup_continues_after_first_worker_force_wait_error(
    services, monkeypatch
):
    runtime = services
    first, second = runtime.spawn(), runtime.spawn()
    for child in (first, second):
        await runtime.log_contains(child, "v2 Dispatcher started:")
        assert_no_parent_credentials(child)
    original = worker_module.stop_owned_group
    visited = []

    def force_wait_error(child):
        original(child)
        visited.append(child.pid)
        if child is first and visited.count(first.pid) == 1:
            raise subprocess.TimeoutExpired("synthetic-owned-wait", 5)

    with monkeypatch.context() as patch:
        patch.setattr(worker_module, "stop_owned_group", force_wait_error)
        with pytest.raises(BaseExceptionGroup):
            await runtime.stop()
    assert visited == [first.pid, second.pid]
    assert first.poll() is not None and second.poll() == 0
    assert all(not capture_owned_children(child) for child in (first, second))
    runtime.record("verified", scenario="all-workers-cleaned-after-force-wait-error")


async def test_unowned_process_group_is_rejected():
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        env=private_environment(),
    )
    try:
        with pytest.raises(RuntimeError, match="unowned process group"):
            stop_owned_group(child)
        assert child.poll() is None
    finally:
        child.terminate()
        await asyncio.to_thread(child.wait, timeout=5)
