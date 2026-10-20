"""Exercise the complete standalone scheduler initializer with real tasks."""

import asyncio

import pytest

from app.core import bootstrap, deployment_profile
from tests.core.scheduler_runtime_ports import scheduler as scheduler

TASKS = [
    "scheduler-heartbeat", "token-cleanup", "staging-cleanup", "export-processor",
    "export-cleanup", "outbox-dispatcher", "outbox-reconciler",
    "answer-projection-reconciler", "async-task-health-monitor",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("cloud", [False, True])
async def test_complete_scheduler_startup_owns_original_tasks_and_outbox_contract(scheduler, cloud):
    if cloud:
        scheduler.profile = deployment_profile.DeploymentProfile.CLOUD_API
    await bootstrap._init_scheduler_dependencies(scheduler.registry)
    assert scheduler.events == ["audit", "metrics"]
    assert [managed.name for managed in scheduler.registry._tasks] == TASKS
    assert all(not managed._task.done() for managed in scheduler.registry._tasks)
    assert await scheduler.enqueue("synthetic-id", "synthetic-kind", {"value": 1}, 3) == "synthetic-enqueued"
    assert scheduler.events[-1] == (
        "enqueue", ("synthetic-kind", {"value": 1}), {"task_id": "synthetic-id", "schema_version": 3},
    )
    scheduler.logger.warning.assert_not_called()
    scheduler.logger.critical.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", ["audit", "metrics"])
@pytest.mark.parametrize("cloud", [False, True])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_scheduler_preserves_fatal_nonfatal_and_cancelled_startup_boundaries(
    scheduler, failed, cloud, error_type,
):
    if cloud:
        scheduler.profile = deployment_profile.DeploymentProfile.CLOUD_API
    error = error_type("synthetic standalone scheduler failure")
    scheduler.failures[failed] = error
    fatal = cloud or error_type is asyncio.CancelledError
    if fatal:
        wrapped = error_type is RuntimeError
        with pytest.raises(SystemError if wrapped else error_type) as caught:
            await bootstrap._init_scheduler_dependencies(scheduler.registry)
        assert (caught.value.__cause__ if wrapped else caught.value) is error
        assert [managed.name for managed in scheduler.registry._tasks] == TASKS[:1]
        assert scheduler.events == (["audit"] if failed == "audit" else ["audit", "metrics"])
        assert scheduler.enqueue is None
        assert scheduler.logger.critical.call_count == int(wrapped)
    else:
        await bootstrap._init_scheduler_dependencies(scheduler.registry)
        assert [managed.name for managed in scheduler.registry._tasks] == TASKS
        assert scheduler.events == ["audit", "metrics"]
        assert scheduler.enqueue is not None
        scheduler.logger.warning.assert_called_once()
