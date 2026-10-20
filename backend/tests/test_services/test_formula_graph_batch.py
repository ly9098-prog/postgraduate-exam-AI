"""Characterize batch state, queue rejection, per-card transactions and retries."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import formula_graph_batch_runner as runner
from app.services import formula_graph_batch_service as batch
from app.services import formula_graph_batch_state as state
from app.services.task_queue_service import EnqueueResult, Task


@pytest.fixture(autouse=True)
def isolated_jobs(monkeypatch):
    monkeypatch.setattr(state, "jobs", {})


def job():
    return {
        "status": "running", "processed": 0, "succeeded": 0, "failed": 0,
        "skipped": 0, "errors": [], "progress": 0.0,
    }


def card(card_id=1, **overrides):
    return SimpleNamespace(**{
        "id": card_id, "title": f"card-{card_id}", "deleted_at": None,
        "graph_status": "missing", "graph_spec": {"template": "single_function"},
        "version": 7, **overrides,
    })


def install_sessions(monkeypatch, cards):
    from app.core import database

    trace = []
    values = iter(cards)

    @asynccontextmanager
    async def transaction():
        trace.append("begin")
        try:
            yield
        except BaseException:
            trace.append("rollback")
            raise
        else:
            trace.append("commit")

    @asynccontextmanager
    async def session():
        trace.append("open")
        db = SimpleNamespace(get=AsyncMock(return_value=next(values)), begin=transaction)
        try:
            yield db
        finally:
            trace.append("close")

    monkeypatch.setattr(database, "async_session", session)
    return trace


@pytest.mark.asyncio
async def test_start_enqueues_snapshot_and_status_is_same_job(monkeypatch):
    from app.services import task_queue_worker

    cards = [card(2), card(5)]
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: cards),
    )))
    enqueue = AsyncMock(return_value=EnqueueResult(True, "queued", "accepted"))
    monkeypatch.setattr(task_queue_worker, "enqueue_formula_batch", enqueue)
    jid = await batch.start_batch_generate(db, 31)
    enqueue.assert_awaited_once_with(jid, [2, 5], 31)
    status = await state.get_batch_status(jid)
    assert status is state.jobs[jid]
    assert (status["status"], status["total"], status["processed"]) == ("running", 2, 0)
    assert status["finished_at"] is None


@pytest.mark.asyncio
async def test_running_job_rejects_before_database_query():
    state.jobs["previous"] = job()
    db = SimpleNamespace(execute=AsyncMock())
    with pytest.raises(ValueError, match="already running"):
        await batch.start_batch_generate(db, 31)
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_queue_rejection_marks_existing_job_failed(monkeypatch):
    from app.services import task_queue_worker

    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: []),
    )))
    enqueue = AsyncMock(return_value=EnqueueResult(False, None, "queue_full"))
    monkeypatch.setattr(task_queue_worker, "enqueue_formula_batch", enqueue)
    with pytest.raises(RuntimeError, match="queue_full"):
        await batch.start_batch_generate(db, 31)
    assert len(state.jobs) == 1
    assert next(iter(state.jobs.values()))["status"] == "failed"


@pytest.mark.asyncio
async def test_runner_uses_fresh_card_and_commits_after_confirm(monkeypatch):
    fresh = card()
    trace = install_sessions(monkeypatch, [fresh])
    preview = AsyncMock(return_value={"preview_token": "synthetic-token"})
    confirm = AsyncMock()
    monkeypatch.setattr(runner, "generate_preview", preview)
    monkeypatch.setattr(runner, "confirm_preview", confirm)
    state.jobs["job"] = job()
    await runner.process_batch("job", [card()], 31)
    assert trace == ["open", "begin", "commit", "close"]
    assert preview.call_args.args[1:] == (fresh, fresh.graph_spec, 31)
    assert confirm.call_args.args[1:] == (fresh, "synthetic-token")
    assert confirm.call_args.kwargs == {
        "card_version": 7, "accept_warnings": True, "admin_id": 31,
    }
    result = state.jobs["job"]
    assert (result["status"], result["succeeded"], result["processed"]) == ("completed", 1, 1)
    assert result["progress"] == 1.0
    assert result["finished_at"]


@pytest.mark.asyncio
@pytest.mark.parametrize("fresh", [
    None, card(deleted_at="deleted"), card(graph_status="ready"), card(graph_spec=None),
])
async def test_skipped_cards_keep_original_counter_semantics(monkeypatch, fresh):
    trace = install_sessions(monkeypatch, [fresh])
    preview = AsyncMock()
    monkeypatch.setattr(runner, "generate_preview", preview)
    state.jobs["job"] = job()
    await runner.process_batch("job", [card()], 31)
    preview.assert_not_awaited()
    assert trace == ["open", "begin", "commit", "close"]
    result = state.jobs["job"]
    assert (result["status"], result["skipped"], result["processed"]) == ("completed", 1, 0)
    assert result["progress"] == 0.0


@pytest.mark.asyncio
async def test_value_error_retries_four_times_then_rolls_back(monkeypatch):
    trace = install_sessions(monkeypatch, [card()])
    preview = AsyncMock(side_effect=ValueError("invalid preview"))
    sleep = AsyncMock()
    monkeypatch.setattr(runner, "generate_preview", preview)
    monkeypatch.setattr(runner.asyncio, "sleep", sleep)
    state.jobs["job"] = job()
    await runner.process_batch("job", [card()], 31)
    assert preview.await_count == 4
    assert sleep.await_count == 3
    assert trace == ["open", "begin", "rollback", "close"]
    result = state.jobs["job"]
    assert (result["status"], result["failed"], result["processed"]) == ("failed", 1, 1)
    assert result["errors"] == [{"card_id": 1, "title": "card-1", "error": "invalid preview"}]


@pytest.mark.asyncio
async def test_non_value_error_continues_next_card_in_new_transaction(monkeypatch):
    trace = install_sessions(monkeypatch, [card(), card(2)])
    preview = AsyncMock(side_effect=[RuntimeError("renderer stopped"), {"preview_token": "ok"}])
    confirm = AsyncMock()
    monkeypatch.setattr(runner, "generate_preview", preview)
    monkeypatch.setattr(runner, "confirm_preview", confirm)
    state.jobs["job"] = job()
    await runner.process_batch("job", [card(), card(2)], 31)
    assert trace == ["open", "begin", "rollback", "close", "open", "begin", "commit", "close"]
    result = state.jobs["job"]
    assert (result["status"], result["failed"], result["succeeded"]) == ("partial_failed", 1, 1)
    assert result["processed"] == 2
    confirm.assert_awaited_once()


def test_cleanup_keeps_running_and_newest_completed_jobs():
    state.jobs.update({
        f"done-{i}": {"status": "completed", "finished_at": f"{i:02d}"}
        for i in range(12)
    })
    state.jobs["running"] = job()
    state._cleanup_old_jobs()
    assert set(state.jobs) == {"running", *(f"done-{i}" for i in range(2, 12))}


@pytest.mark.asyncio
async def test_confirm_failure_retries_preview_within_same_transaction(monkeypatch):
    trace = install_sessions(monkeypatch, [card()])
    preview = AsyncMock(return_value={"preview_token": "retry-token"})
    confirm = AsyncMock(side_effect=[ValueError("stale preview"), None])
    sleep = AsyncMock()
    monkeypatch.setattr(runner, "generate_preview", preview)
    monkeypatch.setattr(runner, "confirm_preview", confirm)
    monkeypatch.setattr(runner.asyncio, "sleep", sleep)
    state.jobs["job"] = job()
    await runner.process_batch("job", [card()], 31)
    assert trace == ["open", "begin", "commit", "close"]
    assert preview.await_count == confirm.await_count == 2
    sleep.assert_awaited_once_with(1)
    assert (state.jobs["job"]["succeeded"], state.jobs["job"]["failed"]) == (1, 0)


@pytest.mark.asyncio
async def test_cancel_propagates_and_leaves_job_running(monkeypatch):
    trace = install_sessions(monkeypatch, [card()])
    monkeypatch.setattr(runner, "generate_preview", AsyncMock(side_effect=asyncio.CancelledError))
    state.jobs["job"] = job()
    with pytest.raises(asyncio.CancelledError):
        await runner.process_batch("job", [card()], 31)
    assert trace == ["open", "begin", "rollback", "close"]
    assert state.jobs["job"] == job()


@pytest.mark.asyncio
async def test_unknown_job_does_not_open_session(monkeypatch):
    from app.core import database

    factory = AsyncMock()
    monkeypatch.setattr(database, "async_session", factory)
    await runner.process_batch("missing", [card()], 31)
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_empty_batch_finishes_without_card_transaction(monkeypatch):
    from app.core import database

    factory = AsyncMock()
    monkeypatch.setattr(database, "async_session", factory)
    state.jobs["job"] = job()
    await runner.process_batch("job", [], 31)
    factory.assert_not_called()
    assert state.jobs["job"]["status"] == "completed"
    assert state.jobs["job"]["finished_at"]
    assert state.jobs["job"]["processed"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("dispatch", ["legacy", "v2"])
async def test_actual_enqueue_to_worker_to_runner_uses_same_job(monkeypatch, dispatch):
    from app.core import database
    from app.services import task_queue_worker as worker

    cards = [card()]
    result_rows = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: cards))
    db = SimpleNamespace(execute=AsyncMock(return_value=result_rows))
    enqueue = AsyncMock(return_value=EnqueueResult(True, "queued", "accepted"))
    monkeypatch.setattr(worker.task_queue, "enqueue_v2", enqueue)
    jid = await batch.start_batch_generate(db, 31)
    args = enqueue.call_args
    assert args.args == ("formula_batch", {"job_id": jid, "card_ids": [1], "admin_id": 31})
    assert args.kwargs == {"task_id": f"formula_batch:{jid}", "max_retries": 2}
    trace = install_sessions(monkeypatch, cards)
    card_session = database.async_session

    @asynccontextmanager
    async def dispatch_session():
        trace.append("dispatch-open")
        yield db
        trace.append("dispatch-close")

    factories = iter([dispatch_session, card_session])
    monkeypatch.setattr(database, "async_session", lambda: next(factories)())
    preview = AsyncMock(return_value={"preview_token": "worker-token"})
    monkeypatch.setattr(runner, "generate_preview", preview)
    monkeypatch.setattr(runner, "confirm_preview", AsyncMock())
    task = Task(task_id=f"formula_batch:{jid}", task_type=args.args[0], payload=args.args[1])
    process = worker._process_task if dispatch == "legacy" else worker._process_task_v2
    await process(task)
    assert trace == ["dispatch-open", "dispatch-close", "open", "begin", "commit", "close"]
    assert state.jobs[jid]["status"] == "completed"
    assert state.jobs[jid]["succeeded"] == 1
