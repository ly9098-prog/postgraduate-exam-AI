"""Shared-resource shutdown stays lazy and at the original lifespan position."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"
HELPERS = ["shutdown_render_resources", "close_runtime_connections", "stop_resource_reconciler"]


def test_resource_shutdown_dependencies_and_function_budgets():
    graph, _ = scan_application(APP)
    assert graph["app.core.runtime_resource_shutdown"] == {
        "app.core.executor_registry", "app.core.executors", "app.core.ai_runtime_guard",
        "app.core.database", "app.core.resource_guard", "app.features.token_budget",
        "app.services.pdf_renderer_service", "app.services.task_queue_service",
    }
    assert "app.core.runtime_resource_shutdown" in graph["app.main"]
    source = (APP / "core/runtime_resource_shutdown.py").read_text()
    assert len(source.splitlines()) <= 300
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50


def test_lifespan_uses_real_helpers_in_original_shutdown_order():
    from app import main
    from app.core import runtime_resource_shutdown

    for name in HELPERS:
        assert getattr(main, name) is getattr(runtime_resource_shutdown, name)
    source = (APP / "main.py").read_text()
    calls = [
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id in HELPERS
    ]
    assert sorted(node.func.id for node in calls) == sorted(HELPERS)
    positions = [source.index(f"await {name}()") for name in HELPERS]
    assert positions == sorted(positions)
    assert source.index("await _ocr_shared_http_client.aclose()") < positions[0]
    assert positions[-1] < source.index('logger.info("=== Shutdown sequence completed')


def test_resource_shutdown_import_does_not_load_resources_or_start_tasks():
    probe = """
import asyncio
import sys
def forbidden(*args, **kwargs):
    raise AssertionError('import must not create a task')
asyncio.create_task = forbidden
from app.core import runtime_resource_shutdown
for name in ('shutdown_render_resources', 'close_runtime_connections', 'stop_resource_reconciler'):
    assert callable(getattr(runtime_resource_shutdown, name))
for name in (
    'app.main', 'app.core.config', 'app.core.database', 'app.core.executor_registry',
    'app.core.executors', 'app.core.resource_guard', 'app.core.ai_runtime_guard',
    'app.features.token_budget', 'app.services.pdf_renderer_service',
    'app.services.task_queue_service',
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
