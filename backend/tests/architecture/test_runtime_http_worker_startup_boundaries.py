"""HTTP worker startup owns only task references, not a second task protocol."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"


def test_http_worker_startup_dependencies_and_budgets():
    graph, _ = scan_application(APP)
    assert graph["app.services.runtime_http_worker_startup"] == {
        "app.services.task_queue_worker", "app.services.ai_prewarm_worker",
    }
    assert "app.services.runtime_http_worker_startup" in graph["app.main"]
    source = (APP / "services/runtime_http_worker_startup.py").read_text()
    assert len(source.splitlines()) <= 300
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50
    main = (APP / "main.py").read_text()
    assert len(main.splitlines()) <= 523
    life = next(node for node in ast.parse(main).body if getattr(node, "name", None) == "lifespan")
    assert life.end_lineno - life.lineno + 1 <= 232


def test_lifespan_uses_real_state_and_helper_with_original_ports_and_position():
    from app import main
    from app.services import runtime_http_worker_startup

    assert main.HttpWorkerTasks is runtime_http_worker_startup.HttpWorkerTasks
    assert main.start_http_worker_tasks is runtime_http_worker_startup.start_http_worker_tasks
    tree = ast.parse((APP / "main.py").read_text())
    life = next(node for node in tree.body if getattr(node, "name", None) == "lifespan")
    calls = [node for node in ast.walk(life) if isinstance(node, ast.Call)]
    allocation = [node for node in calls if getattr(node.func, "id", None) == "HttpWorkerTasks"]
    startup = [node for node in calls if getattr(node.func, "id", None) == "start_http_worker_tasks"]
    assert len(allocation) == len(startup) == 1
    assert not allocation[0].args and not allocation[0].keywords
    assert [ast.unparse(arg) for arg in startup[0].args] == [
        "_worker_tasks", "_production_mode", "logger", "report_http_startup_failure",
    ]
    assert not startup[0].keywords
    owner = next(node for node in life.body if isinstance(node, ast.If) and startup[0] in ast.walk(node))
    assert ast.unparse(owner.test) == "role in ('worker', 'all')"
    local = next(node for node in life.body if isinstance(node, ast.If)
                 and any("Local web export processor started" in ast.unparse(child)
                         for child in ast.walk(node)))
    scheduler = next(node for node in life.body if isinstance(node, ast.If)
                     and ast.unparse(node.test) == "role in ('scheduler', 'all')")
    assert local.lineno < owner.lineno < scheduler.lineno
    shutdown = next(node for node in calls if getattr(node.func, "id", None) == "cancel_and_wait_runtime_tasks")
    labels = [ast.literal_eval(item.elts[0]) for item in shutdown.args[0].elts]
    values = [ast.unparse(item.elts[1]) for item in shutdown.args[0].elts]
    assert values[labels.index("pipeline-dispatcher-v2")] == "_worker_tasks.pipeline_worker_task"
    assert values[labels.index("task-reaper-v2")] == "_worker_tasks.reaper_task"
    assert not any(
        isinstance(node, ast.ImportFrom)
        and node.module in {"app.services.task_queue_worker", "app.services.ai_prewarm_worker"}
        for node in ast.walk(life)
    )
    assert not any(hasattr(runtime_http_worker_startup, name)
                   for name in ["TaskRegistry", "create", "cancel", "wait_all", "register"])


def test_worker_startup_import_is_inert_and_does_not_create_tasks():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError('worker startup import must not create tasks')
asyncio.create_task = forbidden
from app.services.runtime_http_worker_startup import HttpWorkerTasks, start_http_worker_tasks
tasks = HttpWorkerTasks()
assert tasks.pipeline_worker_task is tasks.reaper_task is None
assert callable(start_http_worker_tasks)
assert before == dict(os.environ)
for name in ('app.main', 'app.core.config', 'app.core.database',
             'app.services.task_queue_worker', 'app.services.ai_prewarm_worker'):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent, capture_output=True,
        text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stderr
