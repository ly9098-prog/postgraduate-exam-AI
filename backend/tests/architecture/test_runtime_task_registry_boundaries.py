"""Managed task mechanics stay independent of process bootstrapping."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"


def test_task_registry_has_no_application_dependencies_and_bounded_methods():
    graph, _ = scan_application(APP)
    assert graph["app.core.runtime_task_registry"] == set()
    assert "app.core.runtime_task_registry" in graph["app.core.bootstrap"]
    source = (APP / "core/runtime_task_registry.py").read_text()
    assert len(source.splitlines()) <= 300
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50


def test_bootstrap_uses_actual_registry_and_remains_task_owner():
    from app.core import bootstrap, runtime_task_registry

    assert bootstrap.TaskRegistry is runtime_task_registry.TaskRegistry
    tree = ast.parse((APP / "core/bootstrap.py").read_text())
    assert not any(isinstance(node, ast.ClassDef) and node.name in {"ManagedTask", "TaskRegistry"} for node in tree.body)
    runner = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "_run_role_async")
    constructors = [
        node for node in ast.walk(runner) if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name) and node.func.id == "TaskRegistry"
    ]
    assert len(constructors) == 1 and not constructors[0].args and not constructors[0].keywords
    for name in ["_init_worker_dependencies", "_init_scheduler_dependencies", "shutdown_role"]:
        assert any(isinstance(node, ast.Call) and getattr(node.func, "id", None) == name for node in ast.walk(runner))
    assert runtime_task_registry.logger.name == "postgraduate-ai.bootstrap"


def test_registry_import_does_not_load_configuration_resources_or_start_tasks():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError('import must not create tasks')
asyncio.create_task = forbidden
from app.core.runtime_task_registry import ManagedTask, TaskRegistry
assert len(TaskRegistry()) == 0
assert callable(ManagedTask.create)
assert before == dict(os.environ)
for name in ('app.main', 'app.core.bootstrap', 'app.core.config', 'app.core.database'):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent, capture_output=True,
        text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stderr
