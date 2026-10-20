"""Runtime task cancellation stays separate from app assembly and role IO."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"
TASK_NAMES = [
    "token-cleanup", "pipeline-dispatcher-v2", "task-reaper-v2", "staging-cleanup",
    "export-processor", "export-cleanup", "scheduler-heartbeat",
    "outbox-dispatcher", "outbox-reconciler",
]


def test_shutdown_module_is_neutral_and_within_budget():
    graph, _ = scan_application(APP)
    assert graph["app.core.runtime_task_shutdown"] == set()
    assert "app.core.runtime_task_shutdown" in graph["app.main"]
    source = (APP / "core/runtime_task_shutdown.py").read_text()
    assert len(source.splitlines()) <= 300
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50


def test_lifespan_keeps_original_labels_order_and_shutdown_position():
    from app import main
    from app.core.runtime_task_shutdown import cancel_and_wait_runtime_tasks

    assert main.cancel_and_wait_runtime_tasks is cancel_and_wait_runtime_tasks
    source = (APP / "main.py").read_text()
    calls = [
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "cancel_and_wait_runtime_tasks"
    ]
    assert len(calls) == 1
    assert [ast.literal_eval(item.elts[0]) for item in calls[0].args[0].elts] == TASK_NAMES
    position = source.index("await cancel_and_wait_runtime_tasks")
    assert source.index("await stop_processor()") < position
    assert position < source.index("await stop_role_services(role)")


def test_shutdown_import_does_not_load_application_or_start_tasks():
    probe = """
import asyncio
import sys
def forbidden(*args, **kwargs):
    raise AssertionError('import must not create a task')
asyncio.create_task = forbidden
from app.core.runtime_task_shutdown import cancel_and_wait_runtime_tasks
assert callable(cancel_and_wait_runtime_tasks)
for name in ('app.main', 'app.core.config', 'app.core.database'):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
