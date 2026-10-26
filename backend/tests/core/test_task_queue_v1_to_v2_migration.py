from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock

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


@pytest.fixture
def inject_writer_failure(request):
    async def inject(client, *, fail_on=1, message="simulated writer failure"):
        connection = await client.connection_pool.get_connection("EVALSHA")
        socket = connection._sock
        await client.connection_pool.release(connection)
        runtime = socket._get_server_runtime(socket._server)
        redis = runtime.globals()[b"redis"]
        original_call = redis[b"call"]
        state = runtime.table_from({b"writes": 0})
        # A native Lua error lets pcall exercise rollback with a string error reply.
        redis[b"call"] = runtime.eval(
            b"""
            function(original_call, state, fail_on, message)
                return function(op, ...)
                    if op == "SETEX" then
                        state.writes = state.writes + 1
                        if state.writes == fail_on then
                            error(message, 0)
                        end
                    end
                    return original_call(op, ...)
                end
            end
            """
        )(original_call, state, fail_on, message.encode())
        request.addfinalizer(lambda: redis.__setitem__(b"call", original_call))
        return state

    return inject


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
async def test_failed_v2_writer_rolls_back_partial_state_and_keeps_v1(rig, inject_writer_failure):
    queue, client = rig
    await seed_v1_task(client, "writer-fails", "demo")
    failure = await inject_writer_failure(client)

    migrated = await queue.drain_v1_to_v2("demo", batch_size=1)

    assert migrated == 0
    assert failure[b"writes"] == 1
    assert await client.lrange(_q_key("demo"), 0, -1) == ["writer-fails"]
    assert await client.lrange(_v2_q_key("demo"), 0, -1) == []
    assert await client.exists(_v2_idempotent_key("writer-fails")) == 0
    assert await client.exists(_v2_task_hash_key("writer-fails")) == 0


@pytest.mark.asyncio
async def test_recovered_writer_failure_can_retry_migration(rig, inject_writer_failure):
    queue, client = rig
    await seed_v1_task(client, "retry-writer", "demo")
    failure = await inject_writer_failure(client)
    first_attempt = await queue.drain_v1_to_v2("demo", batch_size=1)
    assert first_attempt == 0
    assert failure[b"writes"] == 1

    migrated = await queue.drain_v1_to_v2("demo", batch_size=1)

    assert migrated == 1
    assert failure[b"writes"] == 2
    assert await client.lrange(_q_key("demo"), 0, -1) == []
    assert await client.lrange(_v2_q_key("demo"), 0, -1) == ["retry-writer"]
    assert await client.exists(_v2_idempotent_key("retry-writer")) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("close_fails", [False, True])
async def test_second_writer_failure_returns_partial_count_and_can_retry(
    rig, inject_writer_failure, monkeypatch, caplog, close_fails,
):
    queue, client = rig
    await seed_v1_task(client, "first", "demo")
    await seed_v1_task(client, "second", "demo")
    failure = await inject_writer_failure(client, fail_on=2, message="second writer failed")
    close = AsyncMock(side_effect=RuntimeError("close failed") if close_fails else None)
    with monkeypatch.context() as patch:
        patch.setattr(client, "aclose", close)
        with caplog.at_level("INFO", logger="postgraduate-ai.task-queue"):
            assert await queue.drain_v1_to_v2("demo", batch_size=2) == 1

    close.assert_awaited_once()
    assert failure[b"writes"] == 2
    assert await client.lrange(_q_key("demo"), 0, -1) == ["second"]
    assert await client.lrange(_v2_q_key("demo"), 0, -1) == ["first"]
    assert await client.exists(_v2_idempotent_key("second")) == 0
    assert await client.exists(_v2_task_hash_key("second")) == 0
    assert [(r.name, r.levelname, r.getMessage()) for r in caplog.records] == [
        ("postgraduate-ai.task-queue", "WARNING",
         "v1→v2 drain failed for demo: second writer failed"),
    ]
    assert await queue.drain_v1_to_v2("demo", batch_size=2) == 1
    assert await client.lrange(_q_key("demo"), 0, -1) == []
    assert await client.lrange(_v2_q_key("demo"), 0, -1) == ["first", "second"]


@pytest.fixture
def drain_ports(monkeypatch):
    client = SimpleNamespace(aclose=AsyncMock())
    queue = DurableTaskQueue(redis_url="redis://unused")
    queue._redis_enabled = True
    get_client = AsyncMock(return_value=client)
    load_scripts = AsyncMock()
    evalsha = AsyncMock(side_effect=[["migrated", "first"], ["empty", ""]])
    monkeypatch.setattr(queue, "_get_script_client", get_client)
    monkeypatch.setattr(queue, "_load_scripts", load_scripts)
    monkeypatch.setattr(queue, "_evalsha_or_reload", evalsha)
    return SimpleNamespace(
        queue=queue, client=client, connect=get_client, load=load_scripts, eval=evalsha,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["connect", "load", "eval"])
@pytest.mark.parametrize("close_fails", [False, True])
async def test_drain_failure_returns_zero_warns_and_closes_acquired_client(
    drain_ports, caplog, stage, close_fails,
):
    ports = drain_ports
    getattr(ports, stage).side_effect = RuntimeError(f"{stage} failed")
    if close_fails:
        ports.client.aclose.side_effect = RuntimeError("close failed")
    with caplog.at_level("INFO", logger="postgraduate-ai.task-queue"):
        assert await ports.queue.drain_v1_to_v2("demo", batch_size=2) == 0

    assert [(r.name, r.levelname, r.getMessage()) for r in caplog.records] == [
        ("postgraduate-ai.task-queue", "WARNING", f"v1→v2 drain failed for demo: {stage} failed"),
    ]
    assert ports.client.aclose.await_count == (0 if stage == "connect" else 1)
    if stage in {"connect", "load"}:
        ports.eval.assert_not_awaited()


@pytest.mark.asyncio
async def test_drain_without_client_returns_zero_without_close_or_summary(drain_ports, caplog):
    ports = drain_ports
    ports.connect.return_value = None
    with caplog.at_level("INFO", logger="postgraduate-ai.task-queue"):
        assert await ports.queue.drain_v1_to_v2("demo") == 0
    ports.load.assert_not_awaited()
    ports.eval.assert_not_awaited()
    ports.client.aclose.assert_not_awaited()
    assert not caplog.records


@pytest.mark.asyncio
@pytest.mark.parametrize("close_fails", [False, True])
async def test_successful_drain_keeps_result_and_summary_despite_close_failure(
    drain_ports, caplog, close_fails,
):
    ports = drain_ports
    if close_fails:
        ports.client.aclose.side_effect = RuntimeError("close failed")
    with caplog.at_level("INFO", logger="postgraduate-ai.task-queue"):
        assert await ports.queue.drain_v1_to_v2("demo", batch_size=2) == 1
    ports.client.aclose.assert_awaited_once()
    assert [(r.name, r.levelname, r.getMessage()) for r in caplog.records] == [
        ("postgraduate-ai.task-queue", "INFO", "v1→v2 drain: migrated 1 tasks for demo"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["connect", "load", "eval", "second_eval", "close"])
@pytest.mark.parametrize("close_fails", [False, True])
async def test_drain_cancellation_propagates_and_closes_acquired_client(
    drain_ports, caplog, stage, close_fails,
):
    ports = drain_ports
    cancelled = asyncio.CancelledError(f"{stage} cancelled")
    if close_fails:
        ports.client.aclose.side_effect = RuntimeError("close failed")
    if stage == "second_eval":
        ports.eval.side_effect = [["migrated", "first"], cancelled]
    elif stage == "close":
        ports.client.aclose.side_effect = cancelled
    else:
        getattr(ports, stage).side_effect = cancelled

    with caplog.at_level("INFO", logger="postgraduate-ai.task-queue"):
        with pytest.raises(asyncio.CancelledError) as caught:
            await ports.queue.drain_v1_to_v2("demo", batch_size=2)
    assert caught.value is cancelled
    assert ports.client.aclose.await_count == (0 if stage == "connect" else 1)
    if stage == "second_eval":
        assert ports.eval.await_count == 2
    assert not caplog.records


@pytest.mark.asyncio
@pytest.mark.parametrize("close_fails", [False, True])
async def test_running_drain_task_cancellation_closes_client(drain_ports, caplog, close_fails):
    ports = drain_ports
    evaluating = asyncio.Event()
    if close_fails:
        ports.client.aclose.side_effect = RuntimeError("close failed")

    async def wait_for_cancel(*args):
        evaluating.set()
        await asyncio.Future()

    ports.eval.side_effect = wait_for_cancel
    with caplog.at_level("INFO", logger="postgraduate-ai.task-queue"):
        task = asyncio.create_task(ports.queue.drain_v1_to_v2("demo"))
        await asyncio.wait_for(evaluating.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    ports.client.aclose.assert_awaited_once()
    assert task.cancelled()
    assert not caplog.records


@pytest.mark.asyncio
async def test_caller_configuration_failure_returns_zero_before_connecting(
    drain_ports, monkeypatch, caplog,
):
    def invalid_limit(task_type):
        raise ValueError("invalid ready limit")

    monkeypatch.setattr(task_queue_service, "_get_max_ready", invalid_limit)
    with caplog.at_level("INFO", logger="postgraduate-ai.task-queue"):
        assert await drain_ports.queue.drain_v1_to_v2("demo") == 0

    drain_ports.connect.assert_not_awaited()
    drain_ports.client.aclose.assert_not_awaited()
    assert [(r.name, r.levelname, r.getMessage()) for r in caplog.records] == [
        ("postgraduate-ai.task-queue", "WARNING",
         "v1→v2 drain failed for demo: invalid ready limit"),
    ]
