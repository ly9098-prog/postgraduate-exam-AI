"""Keep resource startup lazy, directed and at its original lifespan positions."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"
HELPERS = ["initialize_role_executors", "start_resource_reconciler", "ensure_http_runtime_directories"]


def test_resource_startup_dependencies_and_function_budgets():
    graph, _ = scan_application(APP)
    assert graph["app.core.runtime_resource_startup"] == {
        "app.core.config",
        "app.core.deployment_profile", "app.core.executor_registry",
        "app.core.executors", "app.core.resource_guard",
    }
    assert "app.core.runtime_resource_startup" in graph["app.main"]
    source = (APP / "core/runtime_resource_startup.py").read_text()
    assert len(source.splitlines()) <= 300
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50


def test_main_calls_real_helpers_with_original_failure_owner_and_positions():
    from app import main
    from app.core import runtime_resource_startup

    for name in HELPERS:
        assert getattr(main, name) is getattr(runtime_resource_startup, name)
    tree = ast.parse((APP / "main.py").read_text())
    life = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan")
    calls = [node for node in ast.walk(life) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
    helpers = {name: [node for node in calls if node.func.id == name] for name in HELPERS}
    assert all(len(nodes) == 1 for nodes in helpers.values())
    executor = helpers["initialize_role_executors"][0]
    orphan = helpers["start_resource_reconciler"][0]
    assert [ast.unparse(arg) for arg in executor.args] == ["role"]
    assert not executor.keywords and not orphan.args and not orphan.keywords
    owner = next(node for node in life.body if isinstance(node, ast.Try) and any(item is executor for item in ast.walk(node)))
    assert len(owner.handlers) == 1 and ast.unparse(owner.handlers[0].type) == "Exception"
    assert ast.unparse(owner.handlers[0].body[0]) == "report_http_startup_failure('Executors', e, _production_mode)"
    seed = next(node for node in calls if node.func.id == "log_ai_model_configuration")
    lag = next(node for node in calls if node.func.id == "monitor_event_loop_lag")
    serving = next(node for node in ast.walk(life) if isinstance(node, ast.Yield))
    assert seed.lineno < executor.lineno < lag.lineno < orphan.lineno < serving.lineno
    assert all(not (isinstance(node, ast.Name) and node.id == "init_executors_for_role") for node in ast.walk(life))


def test_resource_startup_import_does_not_load_resources_or_start_tasks():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError('import must not create tasks')
asyncio.create_task = forbidden
os.makedirs = forbidden
from app.core import runtime_resource_startup
assert callable(runtime_resource_startup.initialize_role_executors)
assert callable(runtime_resource_startup.start_resource_reconciler)
assert callable(runtime_resource_startup.ensure_http_runtime_directories)
assert dict(os.environ) == before
for name in (
    'app.main', 'app.core.config', 'app.core.database', 'app.core.executor_registry',
    'app.core.executors', 'app.core.resource_guard', 'app.core.deployment_profile',
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent,
        capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stderr
