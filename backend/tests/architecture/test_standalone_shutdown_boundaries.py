"""Standalone resource shutdown stays lazy with one orchestration owner."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"
HELPERS = [
    "stop_standalone_worker_services", "stop_standalone_scheduler_services",
    "shutdown_standalone_formula_pool", "shutdown_standalone_ocr",
    "shutdown_standalone_render_resources", "close_standalone_runtime_connections",
]
ROLE_HELPERS = {HELPERS[0], HELPERS[1], HELPERS[3]}


def test_standalone_shutdown_dependencies_and_function_budgets():
    graph, _ = scan_application(APP)
    assert graph["app.core.standalone_runtime_shutdown"] == {
        "app.services.task_queue_worker", "app.services.ai_prewarm_worker",
        "app.services.audit_cleanup_scheduler", "app.services.recommendation_metrics_scheduler",
        "app.services.export.processor", "app.services.formula_graph_spec_renderer",
        "app.core.deployment_profile", "app.services.ocr_executor_service", "app.services.ocr_service",
        "app.core.executor_registry", "app.core.executors", "app.services.pdf_renderer_service",
        "app.services.task_queue_service", "app.core.database", "app.core.resource_guard",
    }
    assert "app.core.standalone_runtime_shutdown" in graph["app.core.bootstrap"]
    source = (APP / "core/standalone_runtime_shutdown.py").read_text()
    assert len(source.splitlines()) <= 300
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50


def test_bootstrap_uses_real_sections_around_one_original_registry_wait():
    from app.core import bootstrap, standalone_runtime_shutdown

    tree = ast.parse((APP / "core/bootstrap.py").read_text())
    shutdown = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "shutdown_role")
    assert shutdown.end_lineno - shutdown.lineno + 1 <= 50
    calls = sorted(
        [node for node in ast.walk(shutdown) if isinstance(node, ast.Call)],
        key=lambda node: node.lineno,
    )
    helpers = [node for node in calls if getattr(node.func, "id", None) in HELPERS]
    assert [node.func.id for node in helpers] == HELPERS
    for node in helpers:
        assert getattr(bootstrap, node.func.id) is getattr(standalone_runtime_shutdown, node.func.id)
        assert [ast.unparse(arg) for arg in node.args] == (
            ["role", "logger"] if node.func.id in ROLE_HELPERS else ["logger"]
        )
        assert not node.keywords
    waits = [node for node in calls if ast.unparse(node.func) == "registry.wait_all"]
    assert len(waits) == 1
    assert ast.unparse(waits[0]) == "registry.wait_all(timeout=settings.WORKER_SHUTDOWN_GRACE_SEC)"
    assert helpers[1].lineno < waits[0].lineno < helpers[2].lineno
    assert ast.unparse(shutdown.body[1]).startswith("logger.info('=== Shutdown sequence started")
    assert ast.unparse(shutdown.body[-1]).startswith("logger.info('=== Shutdown sequence completed")


def test_standalone_shutdown_import_does_not_load_configuration_or_resources():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError('import must not create tasks')
asyncio.create_task = forbidden
from app.core import standalone_runtime_shutdown
assert callable(standalone_runtime_shutdown.close_standalone_runtime_connections)
assert before == dict(os.environ)
for name in (
    'app.main', 'app.core.bootstrap', 'app.core.config', 'app.core.database',
    'app.services.task_queue_service', 'app.services.ocr_executor_service',
    'app.core.executor_registry', 'app.core.resource_guard',
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent, capture_output=True,
        text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stderr
