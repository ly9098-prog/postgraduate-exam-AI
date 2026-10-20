"""Complete scheduler startup preserves independent optional task failures."""

import asyncio
import builtins
import sys

import pytest

from app.core import bootstrap, deployment_profile
from tests.core.scheduler_runtime_ports import scheduler as scheduler
from tests.core.test_standalone_scheduler_startup import TASKS

COMPONENTS = [
    ("outbox-dispatcher", "app.services.outbox_service", "run_outbox_dispatcher"),
    ("outbox-reconciler", "app.services.outbox_service", "run_outbox_reconciler"),
    ("answer-projection-reconciler", "app.services.practice.projection_reconciliation_service", "run_answer_projection_reconciler"),
    ("async-task-health-monitor", "app.services.task_observability_service", "run_task_health_monitor"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("label,module,operation", COMPONENTS)
@pytest.mark.parametrize("error_type", [RuntimeError, ImportError, asyncio.CancelledError])
async def test_optional_factory_failure_keeps_prior_tasks_and_independent_following_components(
    scheduler, monkeypatch, label, module, operation, error_type,
):
    scheduler.profile = deployment_profile.DeploymentProfile.CLOUD_API
    error = error_type("synthetic optional task factory failure")

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(sys.modules[module], operation, fail)
    if error_type is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError) as caught:
            await bootstrap._init_scheduler_dependencies(scheduler.registry)
        assert caught.value is error
        expected = TASKS[:TASKS.index(label)]
        scheduler.logger.warning.assert_not_called()
    else:
        await bootstrap._init_scheduler_dependencies(scheduler.registry)
        omitted = {"outbox-dispatcher", "outbox-reconciler"} if label == "outbox-dispatcher" else {label}
        expected = [name for name in TASKS if name not in omitted]
        scheduler.logger.warning.assert_called_once()
    assert [managed.name for managed in scheduler.registry._tasks] == expected
    assert all(not managed._task.done() for managed in scheduler.registry._tasks)
    if label == "outbox-reconciler":
        assert scheduler.enqueue is not None
    scheduler.logger.critical.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("module,missing", [
    ("app.services.outbox_service", ["outbox-dispatcher", "outbox-reconciler"]),
    ("app.services.practice.projection_reconciliation_service", ["answer-projection-reconciler"]),
    ("app.services.task_observability_service", ["async-task-health-monitor"]),
])
@pytest.mark.parametrize("error_type", [ImportError, asyncio.CancelledError])
async def test_optional_import_error_is_nonfatal_but_cancellation_skips_later_components(
    scheduler, monkeypatch, module, missing, error_type,
):
    scheduler.profile = deployment_profile.DeploymentProfile.CLOUD_API
    error = error_type("synthetic optional task import failure")
    original = builtins.__import__
    attempts = []

    def guarded(name, *args, **kwargs):
        if name == module:
            attempts.append(name)
            raise error
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    if error_type is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError) as caught:
            await bootstrap._init_scheduler_dependencies(scheduler.registry)
        assert caught.value is error
        expected = TASKS[:TASKS.index(missing[0])]
        scheduler.logger.warning.assert_not_called()
    else:
        await bootstrap._init_scheduler_dependencies(scheduler.registry)
        expected = [name for name in TASKS if name not in missing]
        scheduler.logger.warning.assert_called_once()
    assert attempts == [module]
    assert [managed.name for managed in scheduler.registry._tasks] == expected
    assert all(not managed._task.done() for managed in scheduler.registry._tasks)
