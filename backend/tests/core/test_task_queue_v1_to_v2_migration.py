from __future__ import annotations

import json
from collections.abc import AsyncIterator

import fakeredis.aioredis
import pytest
import pytest_asyncio

from app.services import task_queue_service
from app.services.task_queue_keys import (
    _TASK_PREFIX,
    _q_key,
    _v2_corrupt_key,
    _v2_idempotent_key,
    _v2_q_key,
    _v2_task_hash_key,
)
from app.services.task_queue_service import DurableTaskQueue


@pytest_asyncio.fixture
async def rig(monkeypatch) -> AsyncIterator[tuple[DurableTaskQueue, object]]:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    queue = DurableTaskQueue(redis_url="redis://unused")
    queue._redis_enabled = True

    async def script_client():
        return client

    monkeypatch.setattr(queue, "_get_script_client", script_client)
    yield queue, client
    await client.aclose()


def task_json(task_id: str, task_type: str) -> str:
    return json.dumps(
        {
            "task_id": task_id,
            "task_type": task_type,
            "payload": {"source": "v1"},
            "status": "pending",
        }
    )


async def seed_v1_task(client, task_id: str, task_type: str) -> None:
    await client.hset(
        f"{_TASK_PREFIX}:{task_id}",
        mapping={"data": task_json(task_id, task_type), "status": "pending"},
    )
    await client.rpush(_q_key(task_type), task_id)


@pytest.mark.asyncio
async def test_drain_moves_one_task_atomically(rig):
    queue, client = rig
    await seed_v1_task(client, "task-1", "demo")

    migrated = await queue.drain_v1_to_v2("demo", batch_size=1)

    assert migrated == 1
    assert await client.lrange(_q_key("demo"), 0, -1) == []
    assert await client.lrange(_v2_q_key("demo"), 0, -1) == ["task-1"]
    assert await client.exists(_v2_idempotent_key("task-1")) == 1
    assert (await client.hgetall(_v2_task_hash_key("task-1")))["status"] == "pending"


@pytest.mark.asyncio
async def test_full_v2_queue_keeps_unmigrated_v1_entries(rig, monkeypatch):
    queue, client = rig
    await seed_v1_task(client, "task-1", "demo")
    await seed_v1_task(client, "task-2", "demo")
    monkeypatch.setattr(task_queue_service, "_get_max_ready", lambda _: 1)

    migrated = await queue.drain_v1_to_v2("demo", batch_size=2)

    assert migrated == 1
    assert await client.lrange(_v2_q_key("demo"), 0, -1) == ["task-1"]
    assert await client.lrange(_q_key("demo"), 0, -1) == ["task-2"]
    assert await client.exists(_v2_idempotent_key("task-2")) == 0


@pytest.mark.asyncio
async def test_missing_payload_is_preserved_as_v2_corrupt(rig):
    queue, client = rig
    await client.rpush(_q_key("demo"), "missing-task")

    migrated = await queue.drain_v1_to_v2("demo", batch_size=1)

    assert migrated == 0
    assert await client.lrange(_q_key("demo"), 0, -1) == []
    assert await client.zrange(_v2_corrupt_key("demo"), 0, -1) == ["missing-task"]
    payload = await client.hgetall(_v2_task_hash_key("missing-task"))
    assert payload["status"] == "corrupt"
    assert payload["error"] == "missing task payload during v1 migration"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw", "expected_error"),
    [
        (task_json("different-task-id", "demo"), "task id mismatch during v1 migration"),
        (task_json("wrong-id", "other"), "task type mismatch during v1 migration"),
        ("{invalid-json", "invalid task payload during v1 migration"),
    ],
)
async def test_invalid_payload_preserves_raw_as_corrupt(
    rig, raw, expected_error
):
    queue, client = rig
    await client.hset(
        f"{_TASK_PREFIX}:wrong-id",
        mapping={"data": raw, "status": "pending"},
    )
    await client.rpush(_q_key("demo"), "wrong-id")

    migrated = await queue.drain_v1_to_v2("demo", batch_size=1)

    assert migrated == 0
    payload = await client.hgetall(_v2_task_hash_key("wrong-id"))
    assert payload["status"] == "corrupt"
    assert payload["data"] == raw
    assert payload["error"] == expected_error


@pytest.mark.asyncio
async def test_existing_v2_identity_only_removes_stale_v1_position(rig):
    queue, client = rig
    await client.rpush(_q_key("demo"), "already-v2")
    await client.set(_v2_idempotent_key("already-v2"), "1")

    migrated = await queue.drain_v1_to_v2("demo", batch_size=1)

    assert migrated == 0
    assert await client.lrange(_q_key("demo"), 0, -1) == []
    assert await client.lrange(_v2_q_key("demo"), 0, -1) == []


@pytest.mark.asyncio
async def test_partial_v2_hash_keeps_v1_position_for_review(rig):
    queue, client = rig
    await seed_v1_task(client, "partial-task", "demo")
    await client.hset(_v2_task_hash_key("partial-task"), "status", "pending")

    migrated = await queue.drain_v1_to_v2("demo", batch_size=1)

    assert migrated == 0
    assert await client.lrange(_q_key("demo"), 0, -1) == ["partial-task"]
    assert await client.exists(_v2_idempotent_key("partial-task")) == 0


@pytest.mark.asyncio
async def test_failed_v2_writer_rolls_back_partial_state_and_keeps_v1(rig, monkeypatch):
    queue, client = rig
    await seed_v1_task(client, "writer-fails", "demo")
    connection = await client.connection_pool.get_connection("HSET")
    socket = connection._sock
    await client.connection_pool.release(connection)
    original_send = socket.sendall
    calls = 0

    def failing_send(data):
        nonlocal calls
        if b"HSET" in data and b"lease_expires_at" in data:
            calls += 1
            raise RuntimeError("simulated writer failure")
        return original_send(data)

    monkeypatch.setattr(socket, "sendall", failing_send)

    migrated = await queue.drain_v1_to_v2("demo", batch_size=1)

    assert migrated == 0
    assert calls == 1
    assert await client.lrange(_q_key("demo"), 0, -1) == ["writer-fails"]
    assert await client.lrange(_v2_q_key("demo"), 0, -1) == []
    assert await client.exists(_v2_idempotent_key("writer-fails")) == 0
    assert await client.exists(_v2_task_hash_key("writer-fails")) == 0


@pytest.mark.asyncio
async def test_recovered_writer_failure_can_retry_migration(rig, monkeypatch):
    queue, client = rig
    await seed_v1_task(client, "retry-writer", "demo")
    connection = await client.connection_pool.get_connection("HSET")
    socket = connection._sock
    await client.connection_pool.release(connection)
    original_send = socket.sendall
    calls = 0

    def failing_once_send(data):
        nonlocal calls
        if b"HSET" in data and b"lease_expires_at" in data:
            calls += 1
            if calls == 1:
                raise RuntimeError("simulated transient writer failure")
        return original_send(data)

    monkeypatch.setattr(socket, "sendall", failing_once_send)
    first_attempt = await queue.drain_v1_to_v2("demo", batch_size=1)
    assert first_attempt == 0
    monkeypatch.setattr(socket, "sendall", original_send)

    migrated = await queue.drain_v1_to_v2("demo", batch_size=1)

    assert migrated == 1
    assert await client.lrange(_q_key("demo"), 0, -1) == []
    assert await client.lrange(_v2_q_key("demo"), 0, -1) == ["retry-writer"]
    assert await client.exists(_v2_idempotent_key("retry-writer")) == 1
