"""Pin repair scheduling, savepoint failures and cancellation boundaries."""

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy.exc import IntegrityError

from app.services.practice import projection_reconciliation_service as service

NOW = datetime(2026, 10, 26, 12)


@pytest.fixture
def reconciliation(monkeypatch):
    state = SimpleNamespace(
        ids=[11],
        originals={},
        repairs={},
        calls=[],
        payloads=[],
        failure=None,
        failure_at="create",
        events=[],
        statements=[],
    )

    class Savepoint:
        async def __aenter__(self):
            state.events.append("savepoint-enter")
            if state.failure_at == "enter" and state.failure:
                raise state.failure

        async def __aexit__(self, *error):
            state.events.append(("savepoint-exit", error[0]))
            if state.failure_at == "exit" and state.failure:
                raise state.failure

    async def execute(stmt):
        state.events.append("scan")
        state.statements.append(stmt)
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: state.ids))

    async def scalar(stmt):
        state.statements.append(stmt)
        task_id = stmt.compile().params["task_id_1"]
        original = task_id.startswith("answer_projection:")
        state.events.append("original" if original else "existing-repair")
        return (state.originals if original else state.repairs).get(task_id)

    async def commit():
        state.events.append("commit")

    async def rollback():
        state.events.append("rollback")

    async def create(db, **kwargs):
        assert db is state.db
        state.events.append("create")
        state.calls.append(kwargs)
        state.payloads.append(kwargs["payload"])
        if state.failure_at == "create" and state.failure:
            raise state.failure

    state.db = SimpleNamespace(
        execute=execute,
        scalar=scalar,
        begin_nested=Savepoint,
        commit=commit,
        rollback=rollback,
    )
    state.logger = Mock()
    monkeypatch.setattr(service, "create_outbox", create)
    monkeypatch.setattr(service, "logger", state.logger)
    return state


async def run(state, **kwargs):
    return await service.reconcile_answer_projections(state.db, now=NOW, **kwargs)


def stats(**kwargs):
    return (
        dict(
            checked=1,
            scheduled=0,
            active_original=0,
            repair_already_scheduled=0,
            races=0,
            errors=0,
        )
        | kwargs
    )


@pytest.mark.asyncio
async def test_repair_uses_narrow_unlocked_scan_and_versioned_outbox(reconciliation):
    state = reconciliation
    state.originals["answer_projection:11"] = SimpleNamespace(
        status="completed",
        payload={
            "request_id": 42,
            "_trace": {"trace_id": "trace", "request_id": 0, "extra": "drop"},
        },
    )
    assert await run(state, batch_size=0, grace_sec=-3) == stats(scheduled=1)
    assert state.events == [
        "scan",
        "original",
        "existing-repair",
        "savepoint-enter",
        "create",
        ("savepoint-exit", None),
        "commit",
    ]
    stmt = state.statements[0]
    assert [column.key for column in stmt.selected_columns] == ["id"]
    assert stmt._for_update_arg is None
    assert stmt._limit_clause.value == 1
    assert stmt.compile().params["answered_at_1"] == NOW
    expected_id = service._repair_task_id(11, NOW)
    assert state.calls == [
        {
            "task_id": expected_id,
            "task_type": "answer_projection",
            "schema_version": 2,
            "payload": {
                "practice_record_id": 11,
                "request_id": "42",
                "reconciliation": {
                    "source": "practice_record_projection_pending",
                    "original_task_id": "answer_projection:11",
                },
                "_trace": {"trace_id": "trace", "request_id": "0"},
            },
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "leased"])
async def test_active_original_commits_scan_without_repair_lookup(
    reconciliation, status
):
    state = reconciliation
    state.originals["answer_projection:11"] = SimpleNamespace(status=status)
    assert await run(state) == stats(active_original=1)
    assert state.events == ["scan", "original", "commit"]


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", [0, 10])
async def test_any_existing_repair_identity_deduplicates(reconciliation, existing):
    state = reconciliation
    state.repairs[service._repair_task_id(11, NOW)] = existing
    assert await run(state) == stats(repair_already_scheduled=1)
    assert state.events == ["scan", "original", "existing-repair", "commit"]


@pytest.mark.asyncio
async def test_empty_scan_rolls_back_without_commit(reconciliation):
    reconciliation.ids = []
    assert await run(reconciliation) == stats(checked=0)
    assert reconciliation.events == ["scan", "rollback"]


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["enter", "create", "exit"])
@pytest.mark.parametrize("kind", ["race", "ordinary", "cancel"])
async def test_only_savepoint_failures_are_classified_and_cancel_propagates(
    reconciliation,
    stage,
    kind,
):
    state = reconciliation
    state.failure_at = stage
    error = {
        "race": IntegrityError("insert", {}, Exception("race")),
        "ordinary": RuntimeError("failed"),
        "cancel": asyncio.CancelledError("cancel"),
    }[kind]
    state.failure = error
    if kind == "cancel":
        with pytest.raises(asyncio.CancelledError) as caught:
            await run(state)
        assert caught.value is error
        assert "commit" not in state.events and "rollback" not in state.events
    else:
        assert await run(state) == stats(**{"races" if kind == "race" else "errors": 1})
        assert state.events[-1] == "commit"
        if kind == "race":
            state.logger.debug.assert_called_once_with(
                "answer projection repair raced: record_id=%s task_id=%s",
                11,
                service._repair_task_id(11, NOW),
            )
        else:
            state.logger.exception.assert_called_once_with(
                "answer projection repair scheduling failed: record_id=%s",
                11,
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("port", ["execute", "scalar", "commit", "rollback"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_failures_outside_savepoint_escape_without_compensation(
    reconciliation,
    port,
    cancel,
):
    state = reconciliation
    if port == "rollback":
        state.ids = []
    error = asyncio.CancelledError() if cancel else RuntimeError(port)

    async def fail(*args, **kwargs):
        raise error

    setattr(state.db, port, fail)
    with pytest.raises(type(error)) as caught:
        await run(state)
    assert caught.value is error
    state.logger.exception.assert_not_called()


@pytest.mark.asyncio
async def test_public_repair_and_payload_ports_remain_late_bound(
    reconciliation, monkeypatch
):
    state = reconciliation
    original = SimpleNamespace(status="failed", payload={})
    state.originals["answer_projection:11"] = original
    calls = []

    def repair(record_id, now):
        calls.append(("repair", record_id, now))
        return "repair-custom"

    def request(outbox):
        assert outbox is original
        calls.append(("request",))
        return "patched-request"

    def trace(outbox):
        assert outbox is original
        calls.append(("trace",))
        return {"trace_id": "patched"}

    monkeypatch.setattr(service, "_repair_task_id", repair)
    monkeypatch.setattr(service, "_payload_request_id", request)
    monkeypatch.setattr(service, "_payload_trace", trace)
    assert await run(state) == stats(scheduled=1)
    assert calls == [("repair", 11, NOW), ("request",), ("trace",)]
    assert state.calls[0]["task_id"] == "repair-custom"
    assert state.payloads[0]["_trace"] == {"trace_id": "patched"}


@pytest.mark.asyncio
async def test_batch_continues_after_per_record_failure_and_keeps_counts(
    reconciliation, monkeypatch
):
    state = reconciliation
    state.ids = [11, 12, 13]

    async def create(db, **kwargs):
        state.calls.append(kwargs)
        if kwargs["payload"]["practice_record_id"] == 12:
            raise RuntimeError("one failure")

    monkeypatch.setattr(service, "create_outbox", create)
    assert await run(state) == stats(checked=3, scheduled=2, errors=1)
    assert state.events[-1] == "commit"
