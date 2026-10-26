"""Unmodified worker_main, private migrated PostgreSQL and Redis, actual signals."""

from __future__ import annotations

import asyncio
import signal
import time
from contextlib import AsyncExitStack

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.services.task_queue_contract import Task, TaskStatus
from app.services.task_queue_keys import _v2_heartbeat_key, _v2_p_key
from app.services.task_queue_service import DurableTaskQueue
from tests.integration.owned_worker import OwnedWorker
from tests.integration.worker_projection_data import (
    FIRST,
    SECOND,
    assert_pending,
    assert_projected,
    database_engine,
    observe,
    seed_records,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
TASK_TYPE = "answer_projection"


@pytest_asyncio.fixture
async def worker_env():
    runtime = OwnedWorker()
    async with AsyncExitStack() as resources:
        resources.push_async_callback(runtime.stop)
        await runtime.start_services()
        engine = database_engine(runtime)
        resources.push_async_callback(engine.dispose)
        queue = DurableTaskQueue(redis_url=runtime.redis.url)
        resources.push_async_callback(queue.close)
        await seed_records(engine)
        try:
            yield runtime, engine, queue
        finally:
            print(f"Retained full worker evidence: {runtime.directory}")


async def enqueue_record(queue, identity, task_id=None):
    task_id = task_id or f"owned-projection-{identity}"
    result = await queue.enqueue_v2(
        TASK_TYPE,
        {"practice_record_id": identity},
        task_id=task_id,
    )
    assert result.accepted and result.task_id == task_id
    return task_id


async def wait_state(runtime, queue, task_id, expected):
    async def predicate():
        state = await queue.get_task_v2(task_id)
        return state if state and state["status"] == expected else None

    return await runtime.until(predicate)


async def held_claim(runtime, queue, child, lock, task_id):
    async def blocked():
        assert child.poll() is None, f"Worker exited; evidence: {runtime.directory}"
        await lock.execute(text("SELECT pg_stat_clear_snapshot()"))
        row = (
            (
                await lock.execute(
                    text(
                        "SELECT pid, query FROM pg_stat_activity WHERE "
                        "pg_backend_pid() = ANY(pg_blocking_pids(pid)) "
                        "AND wait_event_type = 'Lock'",
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row else None

    blocked_state = await runtime.until(blocked)
    assert "practice_records" in blocked_state["query"]
    assert child.poll() is None
    state = await wait_state(runtime, queue, task_id, "processing")
    runtime.record("blocked-real-projection", worker_pid=child.pid, **blocked_state)
    return Task(
        task_id=task_id,
        task_type=TASK_TYPE,
        payload=state["data"]["payload"],
        status=TaskStatus.PROCESSING,
        owner_token=state["owner_token"],
        generation=int(state["generation"]),
    )


async def lock_record(connection, identity):
    await connection.execute(
        text("SELECT id FROM practice_records WHERE id = :id FOR UPDATE"),
        {"id": identity},
    )


async def finish_and_replay(runtime, engine, queue, task_id, identity):
    await wait_state(runtime, queue, task_id, "completed")
    before = await observe(engine, identity)
    assert_projected(before, identity)
    duplicate = await enqueue_record(queue, identity, task_id=f"redelivery-{identity}")
    await wait_state(runtime, queue, duplicate, "completed")
    assert await observe(engine, identity) == before
    assert await queue.has_idempotency_v2(task_id)
    runtime.record("verified-projection", record_id=identity, state=before)


async def test_sigterm_drains_real_projection_and_preserves_pending(worker_env):
    runtime, engine, queue = worker_env
    first_id = await enqueue_record(queue, FIRST)
    async with engine.begin() as lock:
        await lock_record(lock, FIRST)
        child = runtime.spawn()
        await held_claim(runtime, queue, child, lock, first_id)
        second_id = await enqueue_record(queue, SECOND)
        assert_pending(await observe(engine, FIRST))
        child.send_signal(signal.SIGTERM)
        await runtime.log_contains(child, "v2 Graceful shutdown: draining set")
        assert (await queue.get_task_v2(second_id))["status"] == "pending"
    await runtime.wait_exit(child, 0)
    await wait_state(runtime, queue, first_id, "completed")
    assert_projected(await observe(engine, FIRST), FIRST)
    assert_pending(await observe(engine, SECOND))
    assert (await queue.get_task_v2(second_id))["status"] == "pending"
    replacement = runtime.spawn()
    await finish_and_replay(runtime, engine, queue, second_id, SECOND)
    await finish_and_replay(runtime, engine, queue, first_id, FIRST)
    replacement.send_signal(signal.SIGTERM)
    await runtime.wait_exit(replacement, 0)
    runtime.record("verified", scenario="sigterm-drain")


async def wait_natural_expiry(runtime, queue, old):
    client = await queue._get_client()
    deadline = time.monotonic() + 660
    next_report = 0
    while time.monotonic() < deadline:
        state = await queue.get_task_v2(old.task_id)
        remaining = await client.pttl(_v2_heartbeat_key(old.task_id))
        score = await client.zscore(_v2_p_key(TASK_TYPE), old.task_id)
        now = (await client.time())[0]
        assert state["status"] == "processing" and score is not None
        if remaining == -2 and score <= now:
            runtime.record("natural-lease-expiry", score=score, redis_time=now)
            return
        if time.monotonic() >= next_report:
            runtime.record("waiting-real-lease", remaining_ms=remaining, score=score)
            print(f"Real worker lease remaining: {remaining}ms", flush=True)
            next_report = time.monotonic() + 30
        await asyncio.sleep(1)
    raise AssertionError(f"Lease did not expire; evidence: {runtime.directory}")


async def recover_after_kill(runtime, engine, queue, old):
    await wait_natural_expiry(runtime, queue, old)
    async with engine.begin() as lock:
        await lock_record(lock, FIRST)
        replacement = runtime.spawn()
        new = await held_claim(runtime, queue, replacement, lock, old.task_id)
        assert new.generation > old.generation and new.owner_token != old.owner_token
        before = await queue.get_task_v2(old.task_id)
        client = await queue._get_client()
        score = await client.zscore(_v2_p_key(TASK_TYPE), old.task_id)
        for method, args in (
            (queue.heartbeat_v2, (old,)),
            (queue.complete_v2, (old,)),
            (queue.fail_v2, (old, "killed synthetic owner")),
        ):
            assert await method(*args) in (0, -1)
            assert await queue.get_task_v2(old.task_id) == before
            assert await client.zscore(_v2_p_key(TASK_TYPE), old.task_id) == score
        assert_pending(await observe(engine, FIRST))
    await finish_and_replay(runtime, engine, queue, old.task_id, FIRST)
    replacement.send_signal(signal.SIGTERM)
    await runtime.wait_exit(replacement, 0)
    runtime.record(
        "verified",
        scenario="sigkill-recovery",
        old_generation=old.generation,
        new_generation=new.generation,
    )


async def test_sigkill_recovers_after_real_default_lease(worker_env):
    runtime, engine, queue = worker_env
    first_id = await enqueue_record(queue, FIRST)
    async with engine.begin() as lock:
        await lock_record(lock, FIRST)
        child = runtime.spawn()
        old = await held_claim(runtime, queue, child, lock, first_id)
        assert_pending(await observe(engine, FIRST))
        child.kill()
        await runtime.wait_exit(child, -signal.SIGKILL)
        assert_pending(await observe(engine, FIRST))
    await recover_after_kill(runtime, engine, queue, old)
