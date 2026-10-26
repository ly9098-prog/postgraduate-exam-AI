"""Actual private Redis SIGKILL/restart acceptance, without external services."""

from __future__ import annotations

import asyncio
import time

import pytest
from redis.exceptions import NoScriptError

from app.core.config import settings
from app.services.task_queue_keys import (
    _v2_fencing_key,
    _v2_heartbeat_key,
    _v2_p_key,
    _v2_q_key,
    _v2_task_hash_key,
)
from app.services.task_queue_script_bindings import SCRIPT_BINDINGS
from app.services.task_queue_service import (
    DurableTaskQueue,
    QueueHealthError,
    TaskQueueUnavailableError,
)
from tests.integration.owned_redis import OwnedRedis

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
TASK_TYPE = "owned_recovery"
PAYLOAD = {"synthetic": True, "nested": {"question_ids": [1, 2]}}


@pytest.fixture(params=["explicit", "inferred"])
def owned_queue(request, monkeypatch):
    # Exercise valid explicit and APP_ENV-inferred production/cloud configurations.
    profile = "cloud_api" if request.param == "explicit" else ""
    monkeypatch.setenv("DEPLOYMENT_PROFILE", profile)
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "DEPLOYMENT_PROFILE", profile)
    monkeypatch.setattr(settings, "DEPLOY_PROFILE", "")
    monkeypatch.setattr(settings, "ALLOW_IN_MEMORY_TASK_QUEUE", True)
    server = OwnedRedis()
    try:
        server.start()
        queue = DurableTaskQueue(redis_url=server.url)
        assert queue._is_restricted and not queue._allow_local_fallback
        yield server, queue
    finally:
        server.stop()
        print(f"Retained owned Redis evidence: {server.directory}")


async def seed(queue, task_id, lease_sec=None):
    result = await queue.enqueue_v2(TASK_TYPE, PAYLOAD, task_id=task_id)
    assert result.accepted and result.task_id == task_id
    if lease_sec is None:
        assert await queue.dequeue_v2("empty_recovery") is None
        return None
    task = await queue.dequeue_v2(TASK_TYPE, lease_sec=lease_sec)
    assert task is not None and task.payload == PAYLOAD
    return task


async def assert_outage(queue):
    for enqueue in (queue.enqueue_v2, queue.enqueue):
        result = await enqueue(
            TASK_TYPE, PAYLOAD, task_id=f"rejected-{enqueue.__name__}"
        )
        assert not result.accepted and result.task_id is None
        assert result.reason == "redis_unavailable" and result.retry_after == 30
    with pytest.raises(TaskQueueUnavailableError) as unavailable:
        await queue.dequeue_v2(TASK_TYPE)
    assert unavailable.value.retry_after == 30
    with pytest.raises(QueueHealthError):
        await queue.queue_length_v2(TASK_TYPE)
    with pytest.raises(QueueHealthError):
        await queue.get_task_v2("ready")
    assert queue._local_tasks == {}


async def assert_completed(server, queue, task):
    assert await queue.complete_v2(task) == 1
    state = await queue.get_task_v2(task.task_id)
    assert state["status"] == "completed"
    assert await queue.has_idempotency_v2(task.task_id)
    duplicate = await queue.enqueue_v2(TASK_TYPE, PAYLOAD, task_id=task.task_id)
    assert duplicate.accepted
    assert await retry_after_restart(server, queue.dequeue_v2, TASK_TYPE) is None
    client = await queue._get_client()
    assert await client.zcard(_v2_p_key(TASK_TYPE)) == 0
    assert await client.llen(_v2_q_key(TASK_TYPE)) == 0


async def observe_reload(queue, monkeypatch):
    client = await queue._get_client()
    assert client is not None
    original = type(client).evalsha
    misses = []

    async def observed(instance, *args, **kwargs):
        try:
            return await original(instance, *args, **kwargs)
        except NoScriptError:
            misses.append(args[0])
            raise

    monkeypatch.setattr(type(client), "evalsha", observed)
    return client, misses


async def retry_after_restart(server, operation, *args, **kwargs):
    # redis-py may surface one stale socket failure before reconnecting on next call.
    for attempt in range(3):
        try:
            return await operation(*args, **kwargs)
        except (QueueHealthError, TaskQueueUnavailableError) as error:
            server.record(
                "reconnect-error",
                operation=operation.__name__,
                attempt=attempt + 1,
                error=type(error).__name__,
            )
            if attempt == 2:
                raise
            await asyncio.sleep(0.05)


async def lease_snapshot(client, task):
    state = {
        "hash": await client.hgetall(_v2_task_hash_key(task.task_id)),
        "processing": await client.zscore(_v2_p_key(TASK_TYPE), task.task_id),
        "owner": await client.get(_v2_heartbeat_key(task.task_id)),
        "fencing": await client.hgetall(_v2_fencing_key(task.task_id)),
    }
    state["ttl_start"] = time.monotonic()
    state["ttl"] = await client.pttl(_v2_heartbeat_key(task.task_id))
    state["ttl_end"] = time.monotonic()
    return state


async def assert_stale_owner_fenced(queue, old, current):
    client = await queue._get_client()
    for operation, args in (
        (queue.heartbeat_v2, (old,)),
        (queue.complete_v2, (old,)),
        (queue.fail_v2, (old, "stale synthetic owner")),
    ):
        before = await lease_snapshot(client, current)
        assert await operation(*args) in (0, -1)
        after = await lease_snapshot(client, current)
        for field in ("hash", "processing", "owner", "fencing"):
            assert after[field] == before[field], (operation.__name__, field)
        elapsed_ms = (after["ttl_end"] - before["ttl_start"]) * 1000
        assert 0 < before["ttl"] - elapsed_ms - 100 <= after["ttl"] <= before["ttl"]


async def assert_lease_renewed(server, queue, task):
    client = await queue._get_client()
    # Reconnect a dormant persistent socket before measuring actual Redis state.
    assert await retry_after_restart(server, queue.dequeue_v2, "empty_recovery") is None
    before = await lease_snapshot(client, task)
    start = (await client.time())[0]
    renewal_started = time.monotonic()
    assert await queue.heartbeat_v2(task, lease_sec=300) == 1
    after = await lease_snapshot(client, task)
    end = (await client.time())[0]
    assert start + 300 <= after["processing"] <= end + 300
    assert after["processing"] > before["processing"] + 150
    assert float(after["hash"]["lease_expires_at"]) == after["processing"]
    elapsed_ms = (after["ttl_end"] - renewal_started) * 1000
    assert after["ttl"] + elapsed_ms > before["ttl"] + 150_000
    assert 0 < after["ttl"] <= 300_000
    assert after["ttl"] >= 300_000 - elapsed_ms - 100
    assert after["owner"] == before["owner"] == task.owner_token
    assert after["fencing"] == before["fencing"]
    assert {k: v for k, v in after["hash"].items() if k != "lease_expires_at"} == {
        k: v for k, v in before["hash"].items() if k != "lease_expires_at"
    }


async def test_ready_reconnects_and_reloads_real_scripts(owned_queue, monkeypatch):
    server, queue = owned_queue
    try:
        await seed(queue, "ready")
        client, misses = await observe_reload(queue, monkeypatch)
        pool = queue._pool
        cached = [getattr(queue, attr) for attr, _ in SCRIPT_BINDINGS]
        assert all(cached) and await client.script_exists(*cached) == [True] * len(
            cached
        )
        server.crash()
        await assert_outage(queue)
        await server.restart()
        assert await client.script_exists(*cached) == [False] * len(cached)
        assert [getattr(queue, attr) for attr, _ in SCRIPT_BINDINGS] == cached
        assert await client.lrange(_v2_q_key(TASK_TYPE), 0, -1) == ["ready"]
        task = await queue.dequeue_v2(TASK_TYPE)
        assert task is not None and task.task_id == "ready" and task.payload == PAYLOAD
        assert await client.llen(_v2_q_key(TASK_TYPE)) == 0
        assert misses == [queue._lua_claim_v2]
        assert await client.script_exists(*cached) == [True] * len(cached)
        assert queue._redis is client and queue._pool is pool
        assert await queue.get_task_v2("rejected-enqueue_v2") is None
        assert await client.exists("taskq:task:rejected-enqueue") == 0
        await assert_completed(server, queue, task)
        next_task = await seed(queue, "after-restart", lease_sec=120)
        await assert_completed(server, queue, next_task)
        server.record("verified", scenario="ready-reconnect", noscript=misses)
    finally:
        await queue.close()


async def test_live_processing_owner_survives_restart(owned_queue):
    server, queue = owned_queue
    try:
        task = await seed(queue, "live", lease_sec=120)
        before = await queue.get_task_v2(task.task_id)
        server.crash()
        await server.restart()
        after = await retry_after_restart(server, queue.get_task_v2, task.task_id)
        assert after == before
        assert await queue._reclaim_expired_v2(TASK_TYPE) == 0
        await assert_lease_renewed(server, queue, task)
        await assert_completed(server, queue, task)
        server.record("verified", scenario="live-owner", generation=task.generation)
    finally:
        await queue.close()


async def test_expired_owner_is_fenced_after_recovery(owned_queue):
    server, queue = owned_queue
    try:
        old = await seed(queue, "expired", lease_sec=1)
        server.crash()
        await server.restart(minimum_downtime=2.1)
        state = await retry_after_restart(server, queue.get_task_v2, old.task_id)
        assert state["status"] == "processing"
        assert await queue._reclaim_expired_v2(TASK_TYPE) == 1
        assert await queue._reclaim_expired_v2(TASK_TYPE) == 0
        new = await retry_after_restart(
            server, queue.dequeue_v2, TASK_TYPE, lease_sec=120
        )
        assert new is not None and new.task_id == old.task_id and new.payload == PAYLOAD
        assert new.generation > old.generation and new.owner_token != old.owner_token
        before = await queue.get_task_v2(new.task_id)
        await assert_stale_owner_fenced(queue, old, new)
        assert await queue.get_task_v2(new.task_id) == before
        assert before["data"]["payload"] == PAYLOAD
        await assert_lease_renewed(server, queue, new)
        await assert_completed(server, queue, new)
        server.record(
            "verified",
            scenario="expired-owner",
            old_generation=old.generation,
            new_generation=new.generation,
        )
    finally:
        await queue.close()
