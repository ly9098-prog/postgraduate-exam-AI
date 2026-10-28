"""Entry-point compatibility baseline for the durable task queue service.

Drives every Redis-touching entry point of ``DurableTaskQueue`` against a
recording Redis stand-in: the v1 pair (``enqueue``/``dequeue``) plus
``heartbeat``/``complete``/``fail``, the v2 pair plus
``complete_v2``/``fail_v2``, and the administrator ``retry_from_dead_v2``.

The assertions pin the Lua script names, key order, ARGV payloads, fallback
decisions, fencing rejections, metric counters, and error mapping.  They hold
for both the HEAD implementation and the split implementation, so they are a
behaviour baseline rather than a regression lock on one layout.
"""

from __future__ import annotations

import json
import time

import pytest
import redis.exceptions as redis_exc

from app.core.config import settings
from app.services.task_queue_contract import Task, TaskStatus
from app.services.task_queue_keys import (
    _HEARTBEAT_PREFIX,
    _IDEMPOTENCY_PREFIX,
    _TASK_PREFIX,
    _V2_FENCING_PREFIX,
    _V2_HEARTBEAT_PREFIX,
    _V2_TASK_PREFIX,
    _dead_key,
    _heartbeat_key,
    _p_key,
    _q_key,
    _retry_key,
    _v2_corrupt_key,
    _v2_dead_key,
    _v2_p_key,
    _v2_q_key,
    _v2_retry_key,
    _v2_task_hash_key,
)
from app.services.task_queue_service import (
    _COMPLETED_TTL,
    _DEAD_HASH_TTL,
    _FENCING_TOMBSTONE_TTL,
    _IDEMPOTENT_TTL,
    DurableTaskQueue,
    TaskQueueUnavailableError,
    _get_max_ready,
    queue_metrics,
)

pytestmark = pytest.mark.asyncio


class NoScriptedResponse(RuntimeError):
    """The harness was asked for a response it never scripted."""


class FakePipeline:
    """Records queued commands; the client log keeps the command order."""

    def __init__(self, client: FakeClient) -> None:
        self._client = client
        self.commands: list[tuple] = []

    def lrem(self, key: str, count: int, value: str) -> FakePipeline:
        self.commands.append(("lrem", key, count, value))
        return self

    def hset(self, key: str, mapping: dict | None = None, **kwargs) -> FakePipeline:
        self.commands.append(("hset", key, dict(mapping or {})))
        return self

    def rpush(self, key: str, value: str) -> FakePipeline:
        self.commands.append(("rpush", key, value))
        return self

    async def execute(self):
        self._client.log.append(("pipeline_execute", tuple(self.commands)))
        error = self._client.pop("pipeline_execute", "pipeline_execute")
        if error is not None:
            raise error
        return [1] * len(self.commands)


class FakeClient:
    """Minimal Redis stand-in with scripted responses and an ordered log."""

    def __init__(self, responses: dict[str, list] | None = None) -> None:
        self.responses = {
            key: list(values) for key, values in (responses or {}).items()
        }
        self.log: list[tuple] = []
        self.closed = 0

    def pop(self, kind: str, what: str = ""):
        queue = self.responses.setdefault(kind, [])
        if not queue:
            raise NoScriptedResponse(f"no scripted response for {kind}:{what}")
        return queue.pop(0)

    def pending(self) -> dict[str, list]:
        return {key: values for key, values in self.responses.items() if values}

    async def aclose(self) -> None:
        self.closed += 1
        self.log.append(("aclose",))

    async def hget(self, key: str, field: str):
        self.log.append(("hget", key, field))
        return self.pop("hget", key)

    async def lrem(self, key: str, count: int, value: str) -> int:
        self.log.append(("lrem", key, count, value))
        return int(self.pop("lrem", key) or 0)

    async def expire(self, key: str, ttl: int) -> bool:
        self.log.append(("expire", key, ttl))
        return bool(self.pop("expire", key))

    def pipeline(self, transaction: bool = False) -> FakePipeline:
        self.log.append(("pipeline", transaction))
        return FakePipeline(self)


class QueueHarness:
    """A DurableTaskQueue whose Redis surface is fully scripted."""

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        enabled: bool,
        restricted: bool,
        allow_fallback: bool,
        responses: dict[str, list] | None,
        client: FakeClient | None,
    ) -> None:
        monkeypatch.setattr(
            settings, "ALLOW_IN_MEMORY_TASK_QUEUE", allow_fallback, raising=False
        )
        self.queue = DurableTaskQueue("redis://queue-harness:6379/0" if enabled else "")
        self.queue._is_restricted = restricted
        self.client = client if client is not None else FakeClient(responses)
        self.script_log: list[tuple[str, int, tuple]] = []
        self.loads: list[object] = []
        self.queue._get_script_client = self._get_script_client
        self.queue._get_client = self._get_script_client
        self.queue._load_scripts = self._load_scripts
        self.queue._evalsha_or_reload = self._evalsha

    async def _get_script_client(self):
        return self.client

    async def _load_scripts(self, client) -> None:
        self.loads.append(client)

    async def _evalsha(self, client, script_name: str, num_keys: int, *args):
        self.script_log.append((script_name, num_keys, args))
        outcome = self.client.pop("script:" + script_name, script_name)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def scripts(self) -> list[str]:
        return [name for name, _num_keys, _args in self.script_log]

    def metrics(self) -> dict[str, int]:
        return dict(queue_metrics)


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch):
    clients: list[FakeClient] = []

    def build(
        *,
        enabled: bool = True,
        restricted: bool = False,
        allow_fallback: bool = False,
        responses: dict[str, list] | None = None,
        client: FakeClient | None = None,
    ) -> QueueHarness:
        built = QueueHarness(
            monkeypatch,
            enabled=enabled,
            restricted=restricted,
            allow_fallback=allow_fallback,
            responses=responses,
            client=client,
        )
        clients.append(built.client)
        return built

    yield build

    drain_report = {id(client): client.pending() for client in clients}
    unconsumed = {key: value for key, value in drain_report.items() if value}
    assert unconsumed == {}, f"scripted responses left unconsumed: {unconsumed}"


def make_task(
    *,
    task_id: str = "task-1",
    task_type: str = "ocr_pipeline",
    owner_token: str = "owner-1",
    retry_count: int = 0,
    max_retries: int = 3,
    status: TaskStatus = TaskStatus.PROCESSING,
) -> Task:
    return Task(
        task_id=task_id,
        task_type=task_type,
        payload={"pipeline_id": "p-1"},
        status=status,
        retry_count=retry_count,
        max_retries=max_retries,
        owner_token=owner_token,
    )


class TestV1EnqueueEntry:
    async def test_idempotent_script_shape_and_duplicate_result(self, harness):
        built = harness(
            responses={"script:_lua_enqueue": ["__duplicate__"]},
        )
        before = built.metrics()

        result = await built.queue.enqueue(
            "ocr_pipeline", {"pipeline_id": "p-1"}, task_id="t-1"
        )

        assert result.accepted is True
        assert result.task_id == "t-1"
        assert result.reason == "duplicate"
        name, num_keys, args = built.script_log[0]
        assert name == "_lua_enqueue"
        assert num_keys == 3
        assert args[0] == _q_key("ocr_pipeline")
        assert args[1] == _TASK_PREFIX
        assert args[2] == _IDEMPOTENCY_PREFIX
        assert args[3] == "t-1"
        assert json.loads(args[4])["task_type"] == "ocr_pipeline"
        assert args[5] == str(_IDEMPOTENT_TTL)
        assert args[6] == str(_get_max_ready("ocr_pipeline"))
        assert built.metrics()["duplicate_enqueue_prevented"] == (
            before["duplicate_enqueue_prevented"] + 1
        )
        assert built.client.closed == 1

    async def test_non_idempotent_script_shape_when_id_is_generated(self, harness):
        built = harness(responses={"script:_lua_enqueue_non_idempotent": ["OK"]})

        result = await built.queue.enqueue("ocr_pipeline", {})

        assert result.accepted is True
        assert result.task_id is not None
        name, num_keys, args = built.script_log[0]
        assert name == "_lua_enqueue_non_idempotent"
        assert num_keys == 2
        assert args[:2] == (_q_key("ocr_pipeline"), _TASK_PREFIX)
        assert args[2] == result.task_id
        assert args[4] == str(_get_max_ready("ocr_pipeline"))

    async def test_queue_full_result_is_not_downgraded_to_local_queue(self, harness):
        built = harness(
            allow_fallback=True,
            responses={"script:_lua_enqueue": ["__queue_full__"]},
        )
        before = built.metrics()

        result = await built.queue.enqueue("ocr_pipeline", {}, task_id="t-1")

        assert result.accepted is False
        assert result.reason == "queue_full"
        assert result.retry_after == 30
        assert built.queue._local_tasks == {}
        assert built.metrics()["enqueue_rejected"] == (before["enqueue_rejected"] + 1)

    async def test_connection_error_without_fallback_is_structural_rejection(
        self, harness
    ):
        built = harness(
            responses={"script:_lua_enqueue": [redis_exc.ConnectionError("down")]}
        )
        before = built.metrics()

        result = await built.queue.enqueue(
            "ocr_pipeline", {"pipeline_id": "p-1"}, task_id="t-1"
        )

        assert result.accepted is False
        assert result.task_id is None
        assert result.reason == "redis_unavailable"
        assert result.retry_after == 30
        assert built.metrics()["enqueue_rejected"] == (before["enqueue_rejected"] + 1)

    async def test_connection_error_with_fallback_lands_in_local_queue(self, harness):
        built = harness(
            allow_fallback=True,
            responses={"script:_lua_enqueue": [redis_exc.ConnectionError("down")]},
        )

        result = await built.queue.enqueue(
            "ocr_pipeline", {"pipeline_id": "p-1"}, task_id="t-1"
        )

        assert result.accepted is True
        assert result.task_id == "t-1"
        assert list(built.queue._local_tasks) == ["t-1"]

    async def test_internal_error_without_fallback_reports_enqueue_failed(
        self, harness
    ):
        built = harness(responses={"script:_lua_enqueue": [RuntimeError("boom")]})
        before = built.metrics()

        result = await built.queue.enqueue("ocr_pipeline", {}, task_id="t-1")

        assert result.accepted is False
        assert result.reason == "enqueue_failed"
        assert result.retry_after == 30
        assert built.metrics()["enqueue_rejected"] == (before["enqueue_rejected"] + 1)

    async def test_missing_script_client_returns_unavailable_result(self, harness):
        built = harness()
        built.queue._get_script_client = _none_client

        result = await built.queue.enqueue("ocr_pipeline", {}, task_id="t-1")

        assert result.accepted is False
        assert result.reason == "redis_unavailable"
        assert result.retry_after == 30
        assert built.queue._local_tasks == {}


async def _none_client():
    return None


class TestV1DequeueEntry:
    async def test_ready_claim_binds_lease_expiry_and_generation(self, harness):
        task = make_task(task_id="t-ready", owner_token="")
        built = harness(
            responses={
                "script:_lua_claim": [
                    (json.dumps(task.to_dict()), "", ""),
                ]
            }
        )

        claimed = await built.queue._dequeue_from_redis(
            built.client, "ocr_pipeline", 300
        )

        assert claimed is not None
        assert claimed.task_id == "t-ready"
        assert claimed.status is TaskStatus.PROCESSING
        name, num_keys, args = built.script_log[0]
        assert name == "_lua_claim"
        assert num_keys == 4
        assert args[:4] == (
            _q_key("ocr_pipeline"),
            _p_key("ocr_pipeline"),
            _HEARTBEAT_PREFIX,
            _TASK_PREFIX,
        )
        assert abs(float(args[4]) - (time.time() + 300)) < 5
        assert args[5] == "300"
        assert len(args[6]) == 32
        assert abs(int(args[7]) - time.time() * 1000) < 5000
        assert claimed.owner_token == args[6]
        assert claimed.lease_expires_at == float(args[4])
        assert built.scripts() == ["_lua_claim"]

    async def test_empty_ready_queue_falls_through_to_retry_claim(self, harness):
        built = harness(
            responses={
                "script:_lua_claim": [None],
                "script:_lua_retry_claim": [None],
            }
        )

        claimed = await built.queue._dequeue_from_redis(
            built.client, "ocr_pipeline", 300
        )

        assert claimed is None
        assert built.scripts() == ["_lua_claim", "_lua_retry_claim"]
        ready_args = built.script_log[0][2]
        retry_args = built.script_log[1][2]
        assert abs(int(ready_args[7]) / 1000 - float(retry_args[4])) < 5
        assert retry_args[8] == ready_args[7]
        assert built.script_log[1][1] == 4
        assert retry_args[:4] == (
            _retry_key("ocr_pipeline"),
            _p_key("ocr_pipeline"),
            _HEARTBEAT_PREFIX,
            _TASK_PREFIX,
        )

    async def test_retry_claim_materializes_processing_task(self, harness):
        task = make_task(task_id="t-retry", owner_token="")
        built = harness(
            responses={
                "script:_lua_claim": [None],
                "script:_lua_retry_claim": [
                    ["t-retry", "", "", json.dumps(task.to_dict())],
                ],
            }
        )

        claimed = await built.queue._dequeue_from_redis(
            built.client, "ocr_pipeline", 300
        )

        assert claimed is not None
        assert claimed.task_id == "t-retry"
        assert claimed.status is TaskStatus.PROCESSING
        assert claimed.owner_token == built.script_log[1][2][7]


class TestV1HeartbeatEntry:
    async def test_empty_identity_is_rejected_without_redis(self, harness):
        built = harness()

        assert await built.queue.heartbeat("") is False

        assert built.script_log == []
        assert built.client.log == []

    async def test_fenced_heartbeat_updates_task_lease(self, harness):
        task = make_task()
        built = harness(responses={"script:_lua_heartbeat": [1]})

        accepted = await built.queue.heartbeat(task, lease_sec=120)

        assert accepted is True
        name, num_keys, args = built.script_log[0]
        assert name == "_lua_heartbeat"
        assert num_keys == 2
        assert args[0] == _p_key("ocr_pipeline")
        assert args[1] == _HEARTBEAT_PREFIX
        assert args[2] == "task-1"
        assert args[4] == "120"
        assert args[5] == "owner-1"
        assert task.lease_expires_at == float(args[3])
        assert built.client.closed == 1

    async def test_fenced_heartbeat_rejection_counts_fencing_metrics(self, harness):
        task = make_task()
        built = harness(responses={"script:_lua_heartbeat": [0]})
        before = built.metrics()

        accepted = await built.queue.heartbeat(task)

        assert accepted is False
        assert built.metrics()["lease_renewal_failure"] == (
            before["lease_renewal_failure"] + 1
        )
        assert built.metrics()["owner_fencing_rejected"] == (
            before["owner_fencing_rejected"] + 1
        )

    async def test_legacy_heartbeat_extends_ttl_without_lua(self, harness):
        built = harness(responses={"expire": [True]})

        accepted = await built.queue.heartbeat("t-legacy", task_type="demo")

        assert accepted is True
        assert built.script_log == []
        assert ("expire", _heartbeat_key("t-legacy"), 300) in built.client.log
        assert built.client.closed == 1

    async def test_redis_error_is_swallowed_as_false(self, harness):
        built = harness(
            responses={"script:_lua_heartbeat": [redis_exc.ConnectionError("down")]}
        )

        assert await built.queue.heartbeat(make_task()) is False


class TestV1CompleteEntry:
    async def test_success_and_rejection_paths(self, harness):
        task = make_task()
        ok = harness(responses={"script:_lua_complete": [1]})

        assert await ok.queue.complete(task) is True
        name, num_keys, args = ok.script_log[0]
        assert name == "_lua_complete"
        assert num_keys == 4
        assert args[:4] == (
            _p_key("ocr_pipeline"),
            _retry_key("ocr_pipeline"),
            _TASK_PREFIX,
            _HEARTBEAT_PREFIX,
        )
        assert args[4] == "task-1"
        assert args[5] == "owner-1"
        assert args[6] == str(_COMPLETED_TTL)

        rejected = harness(responses={"script:_lua_complete": [0]})
        before = rejected.metrics()

        assert await rejected.queue.complete(make_task()) is False
        assert rejected.metrics()["owner_fencing_rejected"] == (
            before["owner_fencing_rejected"] + 1
        )

    async def test_bare_id_still_targets_lua_with_empty_token(self, harness):
        built = harness(responses={"script:_lua_complete": [1]})

        assert await built.queue.complete("t-bare", task_type="demo") is True
        assert built.script_log[0][2][5] == ""

    async def test_local_fallback_pops_the_task(self, harness):
        task = make_task(task_id="t-local")
        built = harness(enabled=False, allow_fallback=True)
        built.queue._local_tasks["t-local"] = task

        assert await built.queue.complete(task) is True

        assert built.queue._local_tasks == {}
        assert built.script_log == []


class TestV1FailEntry:
    async def test_retry_budget_uses_retry_script(self, harness):
        task = make_task(retry_count=0, max_retries=3)
        built = harness(responses={"script:_lua_fail_retry": [1]})

        assert await built.queue.fail(task, "boom") is True

        name, num_keys, args = built.script_log[0]
        assert name == "_lua_fail_retry"
        assert num_keys == 4
        assert args[4] == "task-1"
        assert json.loads(args[6])["retry_count"] == 1
        assert args[7] == "owner-1"
        assert args[8] == "1"
        assert args[9] == "boom"
        assert task.retry_count == 1
        assert task.status is TaskStatus.FAILED

    async def test_exhausted_budget_moves_to_dead_letter(self, harness):
        task = make_task(retry_count=3, max_retries=3, owner_token="owner-1")
        built = harness(responses={"script:_lua_fail_dead": [1]})

        assert await built.queue.fail(task, "fatal") is True

        name, num_keys, args = built.script_log[0]
        assert name == "_lua_fail_dead"
        assert num_keys == 4
        assert args[:4] == (
            _p_key("ocr_pipeline"),
            _dead_key("ocr_pipeline"),
            _TASK_PREFIX,
            _HEARTBEAT_PREFIX,
        )
        assert args[4] == "task-1"
        assert json.loads(args[5])["status"] == "processing"
        assert args[6] == "owner-1"
        assert args[7] == "1000"
        assert task.retry_count == 4

    async def test_bare_id_skips_retry_tracking(self, harness):
        built = harness(responses={"script:_lua_fail_dead": [1]})

        assert await built.queue.fail("t-bare", "boom", task_type="demo") is True

        assert built.scripts() == ["_lua_fail_dead"]
        assert built.script_log[0][2][4] == "t-bare"

    async def test_dead_letter_redis_error_returns_false(self, harness):
        task = make_task(retry_count=3)
        built = harness(responses={"script:_lua_fail_dead": [RuntimeError("boom")]})

        assert await built.queue.fail(task, "fatal") is False


class TestV2EnqueueEntry:
    async def test_redis_disabled_returns_structural_unavailable(self, harness):
        built = harness(enabled=False)

        result = await built.queue.enqueue_v2("ocr_pipeline", {})

        assert result.accepted is False
        assert result.reason == "redis_unavailable"
        assert result.retry_after == 30

    async def test_idempotent_script_shape_and_duplicate_mapping(self, harness):
        built = harness(responses={"script:_lua_enqueue_v2": ["__duplicate__"]})
        before = built.metrics()

        result = await built.queue.enqueue_v2(
            "ocr_pipeline", {"pipeline_id": "p-1"}, task_id="t-1"
        )

        assert result.accepted is True
        assert result.reason == "duplicate"
        as_duplicate = result.task_id
        name, num_keys, args = built.script_log[0]
        assert name == "_lua_enqueue_v2"
        assert num_keys == 3
        assert args[0] == _v2_q_key("ocr_pipeline")
        assert args[3] == as_duplicate
        assert args[5] == str(_IDEMPOTENT_TTL)
        assert args[6] == str(_get_max_ready("ocr_pipeline"))
        assert built.metrics()["duplicate_enqueue_prevented"] == (
            before["duplicate_enqueue_prevented"] + 1
        )

    async def test_queue_full_mapping_and_non_idempotent_script(self, harness):
        full = harness(responses={"script:_lua_enqueue_v2": ["__queue_full__"]})

        result = await full.queue.enqueue_v2("ocr_pipeline", {}, task_id="t-1")

        assert result.accepted is False
        assert result.reason == "queue_full"

        generated = harness(responses={"script:_lua_enqueue_non_idempotent_v2": ["OK"]})

        accepted = await generated.queue.enqueue_v2("ocr_pipeline", {})

        assert accepted.accepted is True
        assert generated.script_log[0][0] == "_lua_enqueue_non_idempotent_v2"
        assert generated.script_log[0][1] == 2

    async def test_timeout_maps_to_structural_unavailable(self, harness):
        built = harness(
            responses={"script:_lua_enqueue_v2": [redis_exc.TimeoutError("slow")]}
        )

        result = await built.queue.enqueue_v2("ocr_pipeline", {}, task_id="t-1")

        assert result.accepted is False
        assert result.reason == "redis_unavailable"
        assert result.retry_after == 30


class TestV2DequeueEntry:
    async def test_claim_binds_corrupt_and_tombstone_budgets(self, harness):
        task = make_task(task_id="t-v2", owner_token="")
        built = harness(
            responses={
                "script:_lua_claim_v2": [
                    [
                        "t-v2",
                        json.dumps(task.to_dict()),
                        "tok-v2",
                        "7",
                        "999",
                    ],
                ]
            }
        )

        claimed = await built.queue.dequeue_v2("ocr_pipeline", lease_sec=300)

        assert claimed is not None
        assert claimed.task_id == "t-v2"
        assert claimed.owner_token == "tok-v2"
        assert claimed.generation == 7
        name, num_keys, args = built.script_log[0]
        assert name == "_lua_claim_v2"
        assert num_keys == 6
        assert args[:6] == (
            _v2_q_key("ocr_pipeline"),
            _v2_p_key("ocr_pipeline"),
            _V2_HEARTBEAT_PREFIX,
            _V2_TASK_PREFIX,
            _V2_FENCING_PREFIX,
            _v2_corrupt_key("ocr_pipeline"),
        )
        assert args[6] == "300"
        assert len(args[7]) == 32
        assert args[8] == str(settings.TASK_QUEUE_CORRUPT_MAX)
        assert args[9] == str(_DEAD_HASH_TTL)

    async def test_empty_ready_queue_falls_through_to_retry(self, harness):
        built = harness(
            responses={
                "script:_lua_claim_v2": [None],
                "script:_lua_retry_claim_v2": [None],
            }
        )

        assert await built.queue.dequeue_v2("ocr_pipeline") is None

        assert built.scripts() == ["_lua_claim_v2", "_lua_retry_claim_v2"]
        assert built.script_log[1][2][:6] == (
            _v2_retry_key("ocr_pipeline"),
            _v2_p_key("ocr_pipeline"),
            _V2_HEARTBEAT_PREFIX,
            _V2_TASK_PREFIX,
            _V2_FENCING_PREFIX,
            _v2_corrupt_key("ocr_pipeline"),
        )

    async def test_corrupt_claim_is_quarantined(self, harness):
        built = harness(
            responses={
                "script:_lua_claim_v2": [
                    ["t-bad", "{not-json", "tok", "1", "0"],
                ],
                "script:_lua_mark_corrupt_v2": [1],
            }
        )

        claimed = await built.queue.dequeue_v2("ocr_pipeline")

        assert claimed is None
        assert built.scripts() == ["_lua_claim_v2", "_lua_mark_corrupt_v2"]
        corrupt_args = built.script_log[1][2]
        assert corrupt_args[5] == "t-bad"

    async def test_timeout_raises_unavailable_error(self, harness):
        built = harness(
            responses={"script:_lua_claim_v2": [redis_exc.TimeoutError("slow")]}
        )

        with pytest.raises(TaskQueueUnavailableError) as excinfo:
            await built.queue.dequeue_v2("ocr_pipeline")

        assert excinfo.value.retry_after == 30
        assert "Redis unavailable during dequeue" in str(excinfo.value)


class TestV2CompleteEntry:
    async def test_bare_id_can_never_satisfy_v2_fencing(self, harness):
        built = harness()

        assert await built.queue.complete_v2("t-bare", task_type="demo") == 0

        assert built.script_log == []

    async def test_success_updates_task_and_binds_ttls(self, harness):
        task = make_task()
        built = harness(responses={"script:_lua_complete_v2": [1]})

        assert await built.queue.complete_v2(task) == 1

        name, num_keys, args = built.script_log[0]
        assert name == "_lua_complete_v2"
        assert num_keys == 5
        assert args[:5] == (
            _v2_p_key("ocr_pipeline"),
            _v2_retry_key("ocr_pipeline"),
            _V2_TASK_PREFIX,
            _V2_HEARTBEAT_PREFIX,
            _V2_FENCING_PREFIX,
        )
        assert args[5] == "task-1"
        assert args[6] == "owner-1"
        assert args[8] == str(_COMPLETED_TTL)
        assert args[9] == str(_FENCING_TOMBSTONE_TTL)
        assert task.status is TaskStatus.COMPLETED
        assert task.error == ""

    async def test_generation_and_owner_mismatches_count_fencing(self, harness):
        for raw, expected in ((0, 0), (-1, -1)):
            built = harness(responses={"script:_lua_complete_v2": [raw]})
            before = built.metrics()
            task = make_task()

            assert await built.queue.complete_v2(task) == expected

            assert built.metrics()["owner_fencing_rejected"] == (
                before["owner_fencing_rejected"] + 1
            )
            assert task.status is TaskStatus.PROCESSING

    async def test_timeout_raises_with_retry_after_two(self, harness):
        built = harness(
            responses={"script:_lua_complete_v2": [redis_exc.TimeoutError("slow")]}
        )

        with pytest.raises(TaskQueueUnavailableError) as excinfo:
            await built.queue.complete_v2(make_task())

        assert excinfo.value.retry_after == 2


class TestV2FailEntry:
    async def test_task_with_budget_uses_retry_script(self, harness):
        task = make_task(retry_count=0, max_retries=3)
        built = harness(responses={"script:_lua_fail_retry_v2": [1]})

        assert await built.queue.fail_v2(task, "boom") == 1

        name, num_keys, args = built.script_log[0]
        assert name == "_lua_fail_retry_v2"
        assert num_keys == 6
        assert args[:6] == (
            _v2_p_key("ocr_pipeline"),
            _v2_retry_key("ocr_pipeline"),
            _v2_dead_key("ocr_pipeline"),
            _V2_TASK_PREFIX,
            _V2_HEARTBEAT_PREFIX,
            _V2_FENCING_PREFIX,
        )
        assert args[6] == "task-1"
        assert args[7] == "10"
        assert args[9] == "owner-1"
        assert args[10] == "1"
        assert args[11] == "boom"
        assert args[12] == str(settings.TASK_QUEUE_RETRY_MAX)
        assert args[13] == str(settings.TASK_QUEUE_DEAD_MAX)
        assert args[14] == str(_FENCING_TOMBSTONE_TTL)
        assert task.status is TaskStatus.FAILED

    async def test_exhausted_budget_uses_dead_script(self, harness):
        task = make_task(retry_count=3, max_retries=3)
        built = harness(responses={"script:_lua_fail_dead_v2": [2]})

        assert await built.queue.fail_v2(task, "fatal") == 2

        name, num_keys, args = built.script_log[0]
        assert name == "_lua_fail_dead_v2"
        assert num_keys == 5
        assert args[5] == "task-1"
        assert args[7] == "owner-1"
        assert args[8] == str(settings.TASK_QUEUE_DEAD_MAX)
        assert args[9] == str(_FENCING_TOMBSTONE_TTL)

    async def test_bare_id_can_never_satisfy_v2_fail_fencing(self, harness):
        built = harness()

        assert await built.queue.fail_v2("t-bare", "boom", task_type="demo") == 0

        assert built.script_log == []

    async def test_timeout_raises_with_retry_after_two(self, harness):
        built = harness(
            responses={"script:_lua_fail_retry_v2": [redis_exc.TimeoutError("slow")]}
        )

        with pytest.raises(TaskQueueUnavailableError) as excinfo:
            await built.queue.fail_v2(make_task(), "boom")

        assert excinfo.value.retry_after == 2
        assert "Redis unavailable during fail transition" in str(excinfo.value)


class TestRetryFromDeadEntry:
    async def test_redis_disabled_returns_false(self, harness):
        built = harness(enabled=False)

        assert await built.queue.retry_from_dead_v2("ocr_pipeline", "t-1") is False

    async def test_missing_hash_heals_duplicate_dead_entries(self, harness):
        built = harness(responses={"hget": [None], "lrem": [2]})

        assert await built.queue.retry_from_dead_v2("ocr_pipeline", "t-1") is False

        assert ("hget", _v2_task_hash_key("t-1"), "data") in built.client.log
        assert ("lrem", _v2_dead_key("ocr_pipeline"), 0, "t-1") in built.client.log
        assert built.client.closed == 1

    async def test_invalid_payload_is_rejected_without_pipeline(self, harness):
        built = harness(responses={"hget": ["{not-json"]})

        assert await built.queue.retry_from_dead_v2("ocr_pipeline", "t-1") is False

        assert built.client.pending().get("pipeline_execute") in (None, [])
        assert not any(entry[0] == "pipeline" for entry in built.client.log)

    async def test_identity_mismatch_payload_is_rejected(self, harness):
        other = make_task(task_id="t-other", status=TaskStatus.DEAD)
        built = harness(responses={"hget": [json.dumps(other.to_dict(), default=str)]})

        assert await built.queue.retry_from_dead_v2("ocr_pipeline", "t-1") is False

        assert not any(entry[0] == "pipeline" for entry in built.client.log)
        assert built.client.closed == 1

    async def test_happy_path_resets_hash_and_requeues(self, harness):
        dead_task = make_task(
            task_id="t-1",
            status=TaskStatus.DEAD,
            retry_count=3,
            max_retries=3,
        )
        dead_task.error = "fatal"
        built = harness(
            responses={
                "hget": [json.dumps(dead_task.to_dict(), default=str)],
                "pipeline_execute": [None],
            }
        )

        assert await built.queue.retry_from_dead_v2("ocr_pipeline", "t-1") is True

        pipeline_calls = [
            entry for entry in built.client.log if entry[0] == "pipeline_execute"
        ]
        assert len(pipeline_calls) == 1
        commands = pipeline_calls[0][1]
        assert commands[0] == ("lrem", _v2_dead_key("ocr_pipeline"), 0, "t-1")
        assert commands[1][0] == "hset"
        assert commands[1][1] == _v2_task_hash_key("t-1")
        mapping = commands[1][2]
        assert mapping["status"] == TaskStatus.PENDING.value
        assert mapping["retry_count"] == 0
        assert mapping["error"] == ""
        assert mapping["owner_token"] == ""
        assert json.loads(mapping["data"])["retry_count"] == 0
        assert commands[2] == ("rpush", _v2_q_key("ocr_pipeline"), "t-1")
        assert built.client.closed == 1

    async def test_pipeline_failure_returns_false(self, harness):
        dead_task = make_task(task_id="t-1", status=TaskStatus.DEAD)
        built = harness(
            responses={
                "hget": [json.dumps(dead_task.to_dict(), default=str)],
                "pipeline_execute": [RuntimeError("boom")],
            }
        )

        assert await built.queue.retry_from_dead_v2("ocr_pipeline", "t-1") is False

        assert built.client.closed == 1
