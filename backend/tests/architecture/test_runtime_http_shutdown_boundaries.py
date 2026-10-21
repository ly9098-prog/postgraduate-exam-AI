"""HTTP prerun task shutdown stays lazy and at the original lifespan position."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"
HELPERS = ["stop_lag_monitor", "stop_export_processor", "raise_after_http_shutdown"]


def test_http_shutdown_dependencies_and_function_budgets():
    graph, _ = scan_application(APP)
    assert graph["app.core.runtime_http_shutdown"] == {
        "app.services.export.processor",
    }
    assert "app.core.runtime_http_shutdown" in graph["app.main"]
    source = (APP / "core/runtime_http_shutdown.py").read_text()
    assert len(source.splitlines()) <= 300
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50


def test_lifespan_uses_real_helpers_in_original_shutdown_order():
    from app import main
    from app.core import runtime_http_shutdown

    for name in HELPERS:
        assert getattr(main, name) is getattr(runtime_http_shutdown, name)
    source = (APP / "main.py").read_text()
    calls = [
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id in HELPERS
    ]
    assert {node.func.id for node in calls} == set(HELPERS)
    positions = [source.index(fragment) for fragment in [
        "await drain_queue_for_role(role)",
        "await stop_lag_monitor(lag_monitor_task)",
        "await stop_export_processor(role)",
        "await cancel_and_wait_runtime_tasks(",
        "raise_after_http_shutdown(shutdown_error)",
    ]]
    assert positions == sorted(positions)


def test_http_shutdown_import_does_not_load_application_or_start_tasks():
    probe = """
import asyncio
import sys
def forbidden(*args, **kwargs):
    raise AssertionError('import must not create a task')
asyncio.create_task = forbidden
from app.core import runtime_http_shutdown
for name in ('stop_lag_monitor', 'stop_export_processor', 'raise_after_http_shutdown'):
    assert callable(getattr(runtime_http_shutdown, name))
for name in (
    'app.main', 'app.core.config', 'app.core.database',
    'app.services.export.processor',
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
