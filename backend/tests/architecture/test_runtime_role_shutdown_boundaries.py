"""Role shutdown protocols retain their dependencies and lifespan positions."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"


def test_role_shutdown_dependencies_and_function_budgets():
    graph, _ = scan_application(APP)
    assert graph["app.core.runtime_role_shutdown"] == {
        "app.services.task_queue_worker", "app.services.audit_cleanup_scheduler",
        "app.services.recommendation_metrics_scheduler", "app.services.ai_prewarm_worker",
    }
    assert "app.core.runtime_role_shutdown" in graph["app.main"]
    for path in ["core/runtime_role_shutdown.py", "core/runtime_resource_shutdown.py"]:
        source = (APP / path).read_text()
        assert len(source.splitlines()) <= 300
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.end_lineno - node.lineno + 1 <= 50


def test_lifespan_keeps_role_protocols_and_formula_pool_in_original_positions():
    from app import main
    from app.core.runtime_resource_shutdown import shutdown_formula_pool
    from app.core.runtime_role_shutdown import drain_queue_for_role, stop_role_services

    assert main.drain_queue_for_role is drain_queue_for_role
    assert main.stop_role_services is stop_role_services
    assert main.shutdown_formula_pool is shutdown_formula_pool
    source = (APP / "main.py").read_text()
    calls = [
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id in {"drain_queue_for_role", "stop_role_services", "shutdown_formula_pool"}
    ]
    assert len(calls) == 3
    for node in calls:
        assert not node.keywords
        if node.func.id != "shutdown_formula_pool":
            assert [ast.dump(arg) for arg in node.args] == [ast.dump(ast.Name(id="role", ctx=ast.Load()))]
    positions = [source.index(fragment) for fragment in [
        "await drain_queue_for_role(role)", "_lag_monitor_task.cancel()",
        "await stop_processor()", "await cancel_and_wait_runtime_tasks",
        "await stop_role_services(role)", "await shutdown_formula_pool()",
        "await shutdown_ocr_executor()", "await shutdown_render_resources()",
    ]]
    assert positions == sorted(positions)


def test_role_protocol_import_does_not_load_resources_or_create_tasks():
    probe = """
import asyncio
import sys
def forbidden(*args, **kwargs):
    raise AssertionError('import must not create a task')
asyncio.create_task = forbidden
from app.core.runtime_role_shutdown import drain_queue_for_role, stop_role_services
from app.core.runtime_resource_shutdown import shutdown_formula_pool
assert all(callable(fn) for fn in (drain_queue_for_role, stop_role_services, shutdown_formula_pool))
for name in (
    'app.main', 'app.core.config', 'app.core.database', 'app.services.task_queue_worker',
    'app.services.audit_cleanup_scheduler', 'app.services.recommendation_metrics_scheduler',
    'app.services.ai_prewarm_worker', 'app.services.formula_graph_spec_renderer',
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
