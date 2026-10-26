"""Late-bound projection ports and real asyncio cancellation characterization."""

import asyncio

import pytest

from app.services.practice import projection_reconciliation_service as service
from tests.practice.test_answer_projection_execution import STAGES
from tests.practice.test_answer_projection_execution import projection as projection
from tests.practice.test_answer_projection_execution import run as project_answer
from tests.practice.test_projection_reconciliation_execution import (
    reconciliation as reconciliation,
)
from tests.practice.test_projection_reconciliation_execution import run as reconcile
from tests.practice.test_projection_reconciliation_execution import stats


@pytest.mark.asyncio
async def test_behavior_can_replace_the_next_module_port_after_await(
    projection, monkeypatch
):
    from app.services import behavior_service, mastery_service

    async def behavior(**kwargs):
        projection.events.append("behavior")

        async def replacement(*args, **kwargs):
            projection.events.append("replaced-mastery")
            return {"mastery_after": 0}

        monkeypatch.setattr(
            mastery_service,
            "update_user_knowledge_state_after_answer",
            replacement,
        )

    monkeypatch.setattr(behavior_service, "record_answer_behavior", behavior)
    assert (await project_answer(projection))["processed"] is True
    assert projection.events[4:6] == ["behavior", "replaced-mastery"]
    assert projection.calls["mark_recommendation_answered"][1]["mastery_after"] == 0


@pytest.mark.asyncio
async def test_actual_task_cancellation_does_not_finish_or_commit(
    projection, monkeypatch
):
    from app.services import behavior_service

    started = asyncio.Event()

    async def behavior(**kwargs):
        started.set()
        await asyncio.Future()

    monkeypatch.setattr(behavior_service, "record_answer_behavior", behavior)
    task = asyncio.create_task(project_answer(projection))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert projection.events == STAGES[:4]


@pytest.mark.asyncio
async def test_savepoint_enter_can_replace_the_live_create_port(
    reconciliation, monkeypatch
):
    state = reconciliation
    original_savepoint = state.db.begin_nested

    async def replacement(db, **kwargs):
        assert db is state.db
        state.events.append("replacement")

    class Savepoint(original_savepoint):
        async def __aenter__(self):
            await super().__aenter__()
            monkeypatch.setattr(service, "create_outbox", replacement)

    state.db.begin_nested = Savepoint
    assert await reconcile(state) == stats(scheduled=1)
    assert "replacement" in state.events
    assert state.calls == []


@pytest.mark.asyncio
async def test_actual_task_cancellation_exits_savepoint_without_commit(
    reconciliation,
    monkeypatch,
):
    state = reconciliation
    started = asyncio.Event()

    async def create(db, **kwargs):
        started.set()
        await asyncio.Future()

    monkeypatch.setattr(service, "create_outbox", create)
    task = asyncio.create_task(reconcile(state))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert state.events[-1] == ("savepoint-exit", asyncio.CancelledError)
    assert "commit" not in state.events and "rollback" not in state.events
