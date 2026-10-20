"""Periodic implementations have one owner and retain task creation owners."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"
HELPERS = ["run_token_cleanup", "run_staging_cleanup", "run_export_cleanup", "run_export_processor_loop"]


def test_periodic_module_dependencies_and_budgets():
    graph, _ = scan_application(APP)
    assert graph["app.services.runtime_periodic_tasks"] == {
        "app.services.system_task_service", "app.services.export.processor",
    }
    for module in ["app.main", "app.core.bootstrap"]:
        assert "app.services.runtime_periodic_tasks" in graph[module]
    source = (APP / "services/runtime_periodic_tasks.py").read_text()
    assert len(source.splitlines()) <= 300
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50


def test_runtime_entries_consume_shared_functions_and_keep_original_task_names():
    from app import main
    from app.core import bootstrap
    from app.services import runtime_periodic_tasks

    for module in [main, bootstrap]:
        for name in HELPERS:
            assert getattr(module, name) is getattr(runtime_periodic_tasks, name)
        assert not hasattr(module, "_run_registered_periodic_task")
        assert not any(hasattr(module, "_periodic_" + name) for name in [
            "token_cleanup", "staging_cleanup", "export_cleanup", "export_processor",
        ])
        tree = ast.parse(Path(module.__file__).read_text())
        calls = [
            node for node in ast.walk(tree) if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name) and node.func.id in HELPERS
        ]
        for call in calls:
            assert not call.keywords
            assert [ast.unparse(arg) for arg in call.args] == (
                ["logger"] if call.func.id == "run_export_processor_loop" else []
            )
        assert sorted(call.func.id for call in calls) == sorted(
            HELPERS + (["run_export_processor_loop"] if module is main else [])
        )
        for label in ["token-cleanup", "staging-cleanup", "export-processor", "export-cleanup"]:
            assert f'"{label}"' in Path(module.__file__).read_text()
    assert 'name="export-processor-local"' in Path(main.__file__).read_text()


def test_periodic_import_does_not_load_services_or_start_tasks():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError('import must not create tasks')
asyncio.create_task = forbidden
from app.services import runtime_periodic_tasks
assert all(callable(getattr(runtime_periodic_tasks, name)) for name in (
    'run_token_cleanup', 'run_staging_cleanup', 'run_export_cleanup', 'run_export_processor_loop',
))
assert before == dict(os.environ)
for name in (
    'app.main', 'app.core.bootstrap', 'app.core.config', 'app.core.database',
    'app.services.system_task_service', 'app.services.export.processor',
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent, capture_output=True,
        text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stderr
