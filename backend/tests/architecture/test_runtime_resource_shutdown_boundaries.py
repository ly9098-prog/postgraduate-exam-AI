"""Shared-resource shutdown stays lazy and at the original lifespan position."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"
HELPERS = [
    "shutdown_http_ocr_gateway", "shutdown_render_resources",
    "close_runtime_connections", "stop_resource_reconciler", "log_active_children",
]


def test_resource_shutdown_dependencies_and_function_budgets():
    graph, _ = scan_application(APP)
    assert graph["app.core.runtime_resource_shutdown"] == {
        "app.core.executor_registry", "app.core.executors", "app.core.ai_runtime_guard",
        "app.core.database", "app.core.resource_guard", "app.features.token_budget",
        "app.services.pdf_renderer_service", "app.services.task_queue_service",
        "app.services.formula_graph_spec_renderer",
        "app.core.deployment_profile", "app.services.ocr_executor_service",
        "app.features.ocr_gateway",
        "app.services.runtime_ocr_startup",
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
    positions = [source.index(fragment) for fragment in [
        "await shutdown_ocr_executor()",
        "await shutdown_http_ocr_gateway(ocr_resources)",
        "await shutdown_render_resources()",
        "await close_runtime_connections()",
        "await stop_resource_reconciler()",
        'logger.info("=== Shutdown sequence completed',
        "log_active_children()",
    ]]
    assert positions == sorted(positions)


def test_resource_shutdown_import_does_not_load_resources_or_start_tasks():
    probe = """
import asyncio
import sys
def forbidden(*args, **kwargs):
    raise AssertionError('import must not create a task')
asyncio.create_task = forbidden
from app.core import runtime_resource_shutdown
for name in (
    'shutdown_render_resources', 'close_runtime_connections', 'stop_resource_reconciler',
    'shutdown_http_ocr_gateway', 'log_active_children',
):
    assert callable(getattr(runtime_resource_shutdown, name))
for name in (
    'app.main', 'app.core.config', 'app.core.database', 'app.core.executor_registry',
    'app.core.executors', 'app.core.resource_guard', 'app.core.ai_runtime_guard',
    'app.features.token_budget', 'app.services.pdf_renderer_service',
    'app.services.task_queue_service',
    'app.features.ocr_gateway', 'app.services.runtime_ocr_startup', 'multiprocessing',
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
