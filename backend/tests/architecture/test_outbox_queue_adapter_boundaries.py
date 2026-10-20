"""Outbox argument adaptation is shared without moving runtime ownership."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"


def test_outbox_adapter_dependencies_and_budgets():
    graph, _ = scan_application(APP)
    assert graph["app.services.outbox_queue_adapter"] == {"app.services.task_queue_service"}
    for module in ["app.main", "app.core.bootstrap"]:
        assert "app.services.outbox_queue_adapter" in graph[module]
    source = (APP / "services/outbox_queue_adapter.py").read_text()
    assert len(source.splitlines()) <= 300
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50


def test_both_runtimes_capture_original_queue_after_import_before_dispatcher_creation():
    from app import main
    from app.core import bootstrap
    from app.services.outbox_queue_adapter import build_outbox_enqueue

    for module, filename, function in [
        (main, "main.py", "lifespan"),
        (bootstrap, "core/bootstrap.py", "_init_scheduler_dependencies"),
    ]:
        assert module.build_outbox_enqueue is build_outbox_enqueue
        tree = ast.parse((APP / filename).read_text())
        runtime = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == function)
        calls = [node for node in ast.walk(runtime) if isinstance(node, ast.Call)]
        builds = [node for node in calls if getattr(node.func, "id", None) == "build_outbox_enqueue"]
        assert len(builds) == 1
        assert [ast.unparse(arg) for arg in builds[0].args] == ["task_queue"]
        assert not builds[0].keywords
        owner = next(node for node in ast.walk(runtime) if isinstance(node, ast.Try) and any(item is builds[0] for item in ast.walk(node)))
        queue_import = next(node for node in owner.body if isinstance(node, ast.ImportFrom) and node.module == "app.services.task_queue_service")
        dispatcher = next(node for node in calls if getattr(node.func, "id", None) == "run_outbox_dispatcher")
        reconciler = next(node for node in calls if getattr(node.func, "id", None) == "run_outbox_reconciler")
        assert queue_import.lineno < builds[0].lineno < dispatcher.lineno < reconciler.lineno
        assert len(owner.handlers) == 1 and ast.unparse(owner.handlers[0].type) == "Exception"
        assert not any(isinstance(node, ast.AsyncFunctionDef) and node.name == "_enqueue_from_outbox" for node in ast.walk(runtime))


def test_adapter_import_does_not_load_queue_config_or_create_resources():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError('import must not create tasks')
asyncio.create_task = forbidden
from app.services.outbox_queue_adapter import build_outbox_enqueue
assert callable(build_outbox_enqueue)
assert before == dict(os.environ)
for name in (
    'app.main', 'app.core.bootstrap', 'app.core.config', 'app.core.database',
    'app.services.task_queue_service', 'app.services.outbox_service',
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent, capture_output=True,
        text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stderr
