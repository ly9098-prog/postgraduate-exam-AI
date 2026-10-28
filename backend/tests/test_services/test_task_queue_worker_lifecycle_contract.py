"""Contract baseline for the worker enqueue fallback, shutdown, and v2 complete.

Covers three Redis-touching entry points:

* ``task_queue_v2_transition_redis_contract.execute_v2_complete`` — the fenced
  complete script, its payload sources, and its result mapping.
* ``task_queue_worker._enqueue_v2_with_local_fallback`` — staging retention
  checks before enqueue and the local-development fallback decision.
* ``task_queue_worker.graceful_shutdown_v2`` — drain, shield, cancel, stop.

Every assertion holds for the HEAD implementation and for the split one.
"""

from __future__ import annotations

import asyncio
import json
import logging

import pytest

from app.core import config as config_module
from app.services.task_queue_contract import Task, TaskStatus
from app.services.task_queue_keys import (
    _V2_FENCING_PREFIX,
    _V2_HEARTBEAT_PREFIX,
    _V2_TASK_PREFIX,
    _v2_p_key,
    _v2_retry_key,
    _v2_task_hash_key,
)
from app.services.task_queue_service import EnqueueResult, queue_metrics

import app.services.task_queue_v2_transition_redis_contract as transition
import app.services.task_queue_worker as worker

pytestmark = pytest.mark.asyncio


class WorkerLogCapture:
    """Capture task-worker log records directly, independent of caplog plumbing.

    ``app.core.logging_config.setup_logging`` can leave ``postgraduate-ai`` with
    its own handlers and ``propagate=False``, so a root-attached caplog handler
    may see nothing depending on test order.  Attaching to the worker logger
    itself keeps this contract stable either way.
    """

    def __init__(self, name: str = "postgraduate-ai.task-worker") -> None:
        self.logger = logging.getLogger(name)
        self.records: list[str] = []

    def __enter__(self) -> WorkerLogCapture:
        self._handler = logging.Handler()
        self._handler.emit = lambda record: self.records.append(record.getMessage())
        self._level = self.logger.level
        self._propagate = self.logger.propagate
        self.logger.addHandler(self._handler)
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = True
        return self

    def __exit__(self, *exc) -> bool:
        self.logger.removeHandler(self._handler)
        self.logger.setLevel(self._level)
        self.logger.propagate = self._propagate
        return False


class ScriptClient:
    """Recording Redis client for the complete transition."""

    def __init__(self, responses: dict[str, list] | None = None) -> None:
        self.responses = {key: list(value) for key, value in (responses or {}).items()}
        self.log: list[tuple] = []
        self.closed = 0

    def pop(self, kind: str):
        queue = self.responses.setdefault(kind, [])
        if not queue:
            raise AssertionError(f"no scripted response for {kind}")
        return queue.pop(0)

    def pending(self) -> dict[str, list]:
        return {key: value for key, value in self.responses.items() if value}

    async def hget(self, key: str, field: str):
        self.log.append(("hget", key, field))
        return self.pop("hget")

    async def aclose(self) -> None:
        self.closed += 1
        self.log.append(("aclose",))


def make_task(
    *,
    task_id: str = "t-1",
    task_type: str = "import_pipeline",
    status: TaskStatus = TaskStatus.PROCESSING,
) -> Task:
    return Task(
        task_id=task_id,
        task_type=task_type,
        payload={"pipeline_id": "p-1"},
        status=status,
        owner_token="owner-1",
    )


class TransitionHarness:
    def __init__(self, responses: dict[str, list] | None = None) -> None:
        self.client = ScriptClient(responses)
        self.scripts: list[tuple] = []
        self.loads: list[object] = []

    async def get_client(self):
        return self.client

    async def load_scripts(self, client) -> None:
        self.loads.append(client)

    async def evalsha(self, client, script_name: str, num_keys: int, *args):
        self.scripts.append((script_name, num_keys, args))
        outcome = self.client.pop("script:" + script_name)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    async def complete(self, task_or_id, *, task_id="t-1", task_type="import_pipeline"):
        return await transition.execute_v2_complete(
            self.get_client,
            self.load_scripts,
            self.evalsha,
            task_or_id,
            task_id=task_id,
            task_type=task_type,
            owner_token="owner-1",
            completed_ttl=86400,
            tombstone_ttl=604800,
            metrics=queue_metrics,
        )


class TestExecuteV2Complete:
    async def test_missing_client_returns_zero(self):
        harness = TransitionHarness()

        async def no_client():
            return None

        result = await transition.execute_v2_complete(
            no_client,
            harness.load_scripts,
            harness.evalsha,
            make_task(),
            task_id="t-1",
            task_type="import_pipeline",
            owner_token="owner-1",
            completed_ttl=86400,
            tombstone_ttl=604800,
            metrics=queue_metrics,
        )

        assert result == 0
        assert harness.scripts == []
        assert harness.client.closed == 0

    async def test_task_payload_path_never_reads_the_hash(self):
        task = make_task()
        harness = TransitionHarness({"script:_lua_complete_v2": [1]})

        result = await harness.complete(task)

        assert result == 1
        assert not any(entry[0] == "hget" for entry in harness.client.log)
        name, num_keys, args = harness.scripts[0]
        assert name == "_lua_complete_v2"
        assert num_keys == 5
        assert args[:5] == (
            _v2_p_key("import_pipeline"),
            _v2_retry_key("import_pipeline"),
            _V2_TASK_PREFIX,
            _V2_HEARTBEAT_PREFIX,
            _V2_FENCING_PREFIX,
        )
        assert args[5] == "t-1"
        assert args[6] == "owner-1"
        assert args[8] == "86400"
        assert args[9] == "604800"
        assert task.status is TaskStatus.COMPLETED
        assert task.error == ""
        assert task.lease_expires_at == 0.0
        assert harness.client.closed == 1
        assert harness.client.pending() == {}

    async def test_bare_id_reads_and_merges_the_current_hash(self):
        current = json.dumps({"task_id": "t-1", "payload": {"pipeline_id": "p-1"}})
        harness = TransitionHarness({"hget": [current], "script:_lua_complete_v2": [0]})
        before = dict(queue_metrics)

        result = await harness.complete("t-1")

        assert result == 0
        assert ("hget", _v2_task_hash_key("t-1"), "data") in harness.client.log
        payload = json.loads(harness.scripts[0][2][7])
        assert payload["task_id"] == "t-1"
        assert payload["status"] == TaskStatus.COMPLETED.value
        assert queue_metrics["owner_fencing_rejected"] == (
            before["owner_fencing_rejected"] + 1
        )

    async def test_generation_mismatch_and_aclose_on_failure(self):
        harness = TransitionHarness({"script:_lua_complete_v2": [-1]})
        before = dict(queue_metrics)

        assert await harness.complete(make_task()) == -1

        assert queue_metrics["owner_fencing_rejected"] == (
            before["owner_fencing_rejected"] + 1
        )

        failing = TransitionHarness(
            {"script:_lua_complete_v2": [RuntimeError("redis down")]}
        )

        with pytest.raises(RuntimeError):
            await failing.complete(make_task())

        assert failing.client.closed == 1


class EnqueueStubs:
    def __init__(self, result: EnqueueResult, *, touch: dict | None = None) -> None:
        self.result = result
        self.touch_outcomes = dict(touch or {})
        self.touched: list[str] = []
        self.enqueued: list[dict] = []
        self.scheduled: list[dict] = []
        self.fallback_allowed = True

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def async_touch_object(object_id: str):
            self.touched.append(object_id)
            outcome = self.touch_outcomes.get(object_id, True)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        class FakeQueue:
            async def enqueue_v2(
                self, task_type, payload, *, task_id=None, max_retries=2
            ):
                self_outer.enqueued.append(
                    {
                        "task_type": task_type,
                        "payload": payload,
                        "task_id": task_id,
                        "max_retries": max_retries,
                    }
                )
                return self_outer.result

        self_outer = self
        monkeypatch.setattr(worker, "async_touch_object", async_touch_object)
        monkeypatch.setattr(worker, "task_queue", FakeQueue())
        monkeypatch.setattr(
            worker,
            "_can_use_local_execution_fallback",
            lambda: self.fallback_allowed,
        )

        def schedule_local_fallback(*, task_type, payload, task_id, max_retries):
            self.scheduled.append(
                {
                    "task_type": task_type,
                    "payload": payload,
                    "task_id": task_id,
                    "max_retries": max_retries,
                }
            )
            return EnqueueResult(
                accepted=True, task_id=task_id or "local", reason="local_fallback"
            )

        monkeypatch.setattr(worker, "_schedule_local_fallback", schedule_local_fallback)


def rejection(reason: str, retry_after: int = 30) -> EnqueueResult:
    return EnqueueResult(
        accepted=False, task_id=None, reason=reason, retry_after=retry_after
    )


class TestWorkerEnqueueFallback:
    async def test_staging_ids_are_touched_once_in_order(self, monkeypatch):
        stubs = EnqueueStubs(EnqueueResult(accepted=True, task_id="t-1"))
        stubs.install(monkeypatch)

        result = await worker._enqueue_v2_with_local_fallback(
            "import_pipeline",
            {
                "staging_object_id": "obj-a",
                "staging_object_ids": ["obj-b", "obj-a", "", 7],
            },
            task_id="t-1",
            max_retries=4,
        )

        assert stubs.touched == ["obj-a", "obj-b"]
        assert stubs.enqueued == [
            {
                "task_type": "import_pipeline",
                "payload": {
                    "staging_object_id": "obj-a",
                    "staging_object_ids": ["obj-b", "obj-a", "", 7],
                },
                "task_id": "t-1",
                "max_retries": 4,
            }
        ]
        assert result.accepted is True
        assert stubs.scheduled == []

    async def test_touch_failure_rejects_without_enqueueing(self, monkeypatch):
        stubs = EnqueueStubs(
            EnqueueResult(accepted=True),
            touch={"obj-a": RuntimeError("staging down")},
        )
        stubs.install(monkeypatch)

        result = await worker._enqueue_v2_with_local_fallback(
            "import_pipeline", {"staging_object_id": "obj-a"}, task_id="t-1"
        )

        assert result.accepted is False
        assert result.reason == "staging_unavailable"
        assert result.retry_after == 30
        assert stubs.enqueued == []

    async def test_missing_object_rejects_without_retry_after(self, monkeypatch):
        stubs = EnqueueStubs(
            EnqueueResult(accepted=True),
            touch={"obj-a": False},
        )
        stubs.install(monkeypatch)

        result = await worker._enqueue_v2_with_local_fallback(
            "import_pipeline", {"staging_object_id": "obj-a"}, task_id="t-1"
        )

        assert result.accepted is False
        assert result.reason == "staging_object_missing"
        assert result.retry_after == 0
        assert stubs.enqueued == []

    async def test_accepted_result_is_returned_unchanged(self, monkeypatch):
        accepted = EnqueueResult(accepted=True, task_id="t-9")
        stubs = EnqueueStubs(accepted)
        stubs.install(monkeypatch)

        result = await worker._enqueue_v2_with_local_fallback(
            "import_pipeline", {}, task_id="t-9"
        )

        assert result is accepted
        assert stubs.scheduled == []

    async def test_undeclared_reason_never_uses_local_fallback(self, monkeypatch):
        full = rejection("queue_full")
        stubs = EnqueueStubs(full)
        stubs.install(monkeypatch)

        result = await worker._enqueue_v2_with_local_fallback(
            "import_pipeline", {}, task_id="t-9"
        )

        assert result is full
        assert stubs.scheduled == []

    async def test_declared_reason_schedules_local_fallback_when_allowed(
        self, monkeypatch
    ):
        unavailable = rejection("redis_unavailable")
        stubs = EnqueueStubs(unavailable)
        stubs.install(monkeypatch)

        result = await worker._enqueue_v2_with_local_fallback(
            "import_pipeline",
            {"staging_object_id": "obj-a"},
            task_id="t-9",
            max_retries=1,
        )

        assert result.reason == "local_fallback"
        assert stubs.scheduled == [
            {
                "task_type": "import_pipeline",
                "payload": {"staging_object_id": "obj-a"},
                "task_id": "t-9",
                "max_retries": 1,
            }
        ]

    async def test_declared_reason_is_returned_when_fallback_is_denied(
        self, monkeypatch
    ):
        unavailable = rejection("redis_unavailable")
        stubs = EnqueueStubs(unavailable)
        stubs.install(monkeypatch)
        stubs.fallback_allowed = False

        result = await worker._enqueue_v2_with_local_fallback(
            "import_pipeline", {}, task_id="t-9"
        )

        assert result is unavailable
        assert stubs.scheduled == []


class ShutdownStubs:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.events: list[str] = []
        self.active: set = set()
        monkeypatch.setattr(worker, "_v2_active_processing", self.active)

        async def set_draining_v2() -> None:
            self.events.append("draining")

        async def stop_worker_v2() -> None:
            self.events.append("stop")

        monkeypatch.setattr(worker, "set_draining_v2", set_draining_v2)
        monkeypatch.setattr(worker, "stop_worker_v2", stop_worker_v2)


class TestGracefulShutdownV2:
    async def test_no_active_tasks_stops_immediately(self, monkeypatch):
        stubs = ShutdownStubs(monkeypatch)
        # Resolve settings through its module: the worker imports the same
        # module path inside the function, so this targets the live object even
        # when a peer test replaced ``app.core.config.settings`` earlier.
        monkeypatch.setattr(
            config_module.settings,
            "WORKER_SHUTDOWN_GRACE_SEC",
            7,
            raising=False,
        )

        with WorkerLogCapture() as capture:
            await worker.graceful_shutdown_v2()

        assert stubs.events == ["draining", "stop"]
        assert any("waiting up to 7s" in message for message in capture.records)
        assert any("no active tasks" in message for message in capture.records)

    async def test_explicit_grace_is_floored_at_five_seconds(self, monkeypatch):
        stubs = ShutdownStubs(monkeypatch)

        with WorkerLogCapture() as capture:
            await worker.graceful_shutdown_v2(grace_sec=1)

        assert any("waiting up to 5s" in message for message in capture.records)
        assert stubs.events == ["draining", "stop"]

    async def test_active_tasks_complete_within_grace(self, monkeypatch):
        stubs = ShutdownStubs(monkeypatch)
        finished = asyncio.Event()

        async def quick_task() -> None:
            await asyncio.sleep(0)
            finished.set()

        stubs.active.add(asyncio.create_task(quick_task()))

        await worker.graceful_shutdown_v2(grace_sec=30)

        assert finished.is_set()
        assert stubs.events == ["draining", "stop"]

    async def test_grace_expiry_cancels_remaining_tasks(self, monkeypatch):
        stubs = ShutdownStubs(monkeypatch)

        async def never_finishes() -> None:
            await asyncio.sleep(300)

        pending = asyncio.create_task(never_finishes())
        stubs.active.add(pending)

        await worker.graceful_shutdown_v2(grace_sec=1)

        assert pending.cancelled()
        assert stubs.events == ["draining", "stop"]
