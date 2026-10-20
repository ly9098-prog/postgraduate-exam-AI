"""HTTP scheduler startup owns task references without a second task protocol."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"


def test_http_scheduler_startup_dependencies_and_budgets():
    graph, _ = scan_application(APP)
    assert graph["app.services.runtime_http_scheduler_startup"] == {
        "app.services.outbox_queue_adapter", "app.services.runtime_periodic_tasks",
        "app.services.runtime_scheduler_startup", "app.services.system_task_service",
        "app.services.outbox_service", "app.services.task_queue_service",
    }
    assert "app.services.runtime_http_scheduler_startup" in graph["app.main"]
    source = (APP / "services/runtime_http_scheduler_startup.py").read_text()
    assert len(source.splitlines()) <= 300
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50
    main = (APP / "main.py").read_text()
    assert len(main.splitlines()) <= 461
    life = next(node for node in ast.parse(main).body if getattr(node, "name", None) == "lifespan")
    assert life.end_lineno - life.lineno + 1 <= 174


def test_lifespan_uses_real_state_and_helper_with_original_ports_and_position():
    from app import main
    from app.services import runtime_http_scheduler_startup

    assert main.HttpSchedulerTasks is runtime_http_scheduler_startup.HttpSchedulerTasks
    assert main.start_http_scheduler_tasks is runtime_http_scheduler_startup.start_http_scheduler_tasks
    tree = ast.parse((APP / "main.py").read_text())
    life = next(node for node in tree.body if getattr(node, "name", None) == "lifespan")
    calls = [node for node in ast.walk(life) if isinstance(node, ast.Call)]
    allocation = [node for node in calls if getattr(node.func, "id", None) == "HttpSchedulerTasks"]
    startup = [node for node in calls if getattr(node.func, "id", None) == "start_http_scheduler_tasks"]
    assert len(allocation) == len(startup) == 1
    assert not allocation[0].args and not allocation[0].keywords
    assert [ast.unparse(arg) for arg in startup[0].args] == [
        "_scheduler_tasks", "_production_mode", "logger", "report_http_startup_failure",
    ]
    assert not startup[0].keywords
    owner = next(node for node in life.body if isinstance(node, ast.If) and startup[0] in ast.walk(node))
    assert ast.unparse(owner.test) == "role in ('scheduler', 'all')"
    worker = next(node for node in life.body if isinstance(node, ast.If)
                  and ast.unparse(node.test) == "role in ('worker', 'all')")
    reconciler = next(node for node in calls if getattr(node.func, "id", None) == "start_resource_reconciler")
    assert worker.lineno < owner.lineno < reconciler.lineno
    shutdown = next(node for node in calls if getattr(node.func, "id", None) == "cancel_and_wait_runtime_tasks")
    values = {ast.literal_eval(item.elts[0]): ast.unparse(item.elts[1]) for item in shutdown.args[0].elts}
    assert values["token-cleanup"] == "_scheduler_tasks.cleanup_task"
    assert values["staging-cleanup"] == "_scheduler_tasks.staging_cleanup_task"
    assert values["export-processor"] == "_scheduler_tasks.export_processor_task"
    assert values["export-cleanup"] == "_scheduler_tasks.export_cleanup_task"
    assert values["scheduler-heartbeat"] == "_scheduler_tasks.scheduler_heartbeat_task"
    assert values["outbox-dispatcher"] == "_scheduler_tasks.outbox_dispatcher_task"
    assert values["outbox-reconciler"] == "_scheduler_tasks.outbox_reconciler_task"
    assert not any(
        isinstance(node, ast.ImportFrom)
        and node.module in {"app.services.system_task_service", "app.services.outbox_service",
                            "app.services.task_queue_service"}
        for node in ast.walk(life)
    )
    assert not any(hasattr(runtime_http_scheduler_startup, name)
                   for name in ["TaskRegistry", "create", "cancel", "wait_all", "register"])


def test_scheduler_startup_import_is_inert_and_does_not_create_tasks():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError('scheduler startup import must not create tasks')
asyncio.create_task = forbidden
from app.services.runtime_http_scheduler_startup import HttpSchedulerTasks, start_http_scheduler_tasks
tasks = HttpSchedulerTasks()
assert tasks.scheduler_heartbeat_task is tasks.cleanup_task is tasks.outbox_reconciler_task is None
assert callable(start_http_scheduler_tasks)
assert before == dict(os.environ)
for name in ('app.main', 'app.core.config', 'app.core.database',
             'app.services.system_task_service', 'app.services.outbox_service',
             'app.services.task_queue_service'):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent, capture_output=True,
        text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stderr
