"""Both runtime entries consume the same lazy scheduler startup services."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"
HELPERS = ["start_audit_cleanup_scheduler", "start_recommendation_metrics_scheduler"]


def test_scheduler_startup_dependencies_and_function_budgets():
    graph, _ = scan_application(APP)
    assert graph["app.services.runtime_scheduler_startup"] == {
        "app.services.audit_cleanup_scheduler", "app.services.recommendation_metrics_scheduler",
        "app.core.runtime_task_registry", "app.services.outbox_queue_adapter",
        "app.services.outbox_service", "app.services.task_queue_service",
        "app.services.practice.projection_reconciliation_service", "app.services.task_observability_service",
    }
    for module in ["app.main", "app.core.bootstrap"]:
        assert "app.services.runtime_scheduler_startup" in graph[module]
    source = (APP / "services/runtime_scheduler_startup.py").read_text()
    assert len(source.splitlines()) <= 300
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50


def test_both_entries_use_real_helpers_caller_logger_and_original_error_handlers():
    from app import main
    from app.core import bootstrap
    from app.services import runtime_scheduler_startup

    for module, filename, function, report in [
        (main, "main.py", "lifespan", "report_http_startup_failure"),
        (bootstrap, "core/bootstrap.py", "_init_scheduler_dependencies", "_report"),
    ]:
        tree = ast.parse((APP / filename).read_text())
        runtime = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == function)
        calls = sorted([
            node for node in ast.walk(runtime) if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name) and node.func.id in HELPERS
        ], key=lambda node: node.lineno)
        assert [node.func.id for node in calls] == HELPERS
        for call, label in zip(calls, ["Audit log cleanup scheduler", "Recommendation metrics scheduler"], strict=True):
            assert getattr(module, call.func.id) is getattr(runtime_scheduler_startup, call.func.id)
            assert [ast.unparse(arg) for arg in call.args] == ["logger"] and not call.keywords
            owner = next(node for node in ast.walk(runtime) if isinstance(node, ast.Try) and any(item is call for item in ast.walk(node)))
            assert len(owner.handlers) == 1 and ast.unparse(owner.handlers[0].type) == "Exception"
            handler = owner.handlers[0].body[0].value
            assert handler.func.id == report and ast.literal_eval(handler.args[0]) == label
        assert calls[0].lineno < calls[1].lineno


def test_standalone_scheduler_passes_original_registry_logger_to_independent_optional_tasks():
    from app.core import bootstrap
    from app.services import runtime_scheduler_startup

    helpers = [
        "start_scheduler_outbox_tasks", "start_answer_projection_task",
        "start_scheduler_health_task",
    ]
    runtime = next(
        node for node in ast.parse((APP / "core/bootstrap.py").read_text()).body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_init_scheduler_dependencies"
    )
    calls = [
        node for node in ast.walk(runtime) if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) in helpers
    ]
    assert [node.func.id for node in calls] == helpers
    for call in calls:
        assert getattr(bootstrap, call.func.id) is getattr(runtime_scheduler_startup, call.func.id)
        assert [ast.unparse(arg) for arg in call.args] == ["registry", "logger"]
        assert not call.keywords
    assert runtime.end_lineno - runtime.lineno + 1 <= 50
    helper_tree = ast.parse((APP / "services/runtime_scheduler_startup.py").read_text())
    for name in helpers:
        function = next(node for node in helper_tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
        assert len(function.body) == 1 and isinstance(function.body[0], ast.Try)
        assert len(function.body[0].handlers) == 1
        assert ast.unparse(function.body[0].handlers[0].type) == "Exception"


def test_importing_scheduler_startup_does_not_load_services_config_or_start_tasks():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError('import must not create tasks')
asyncio.create_task = forbidden
from app.services import runtime_scheduler_startup
assert callable(runtime_scheduler_startup.start_audit_cleanup_scheduler)
assert callable(runtime_scheduler_startup.start_recommendation_metrics_scheduler)
assert before == dict(os.environ)
for name in (
    'app.main', 'app.core.bootstrap', 'app.core.config', 'app.core.database',
    'app.services.audit_cleanup_scheduler', 'app.services.recommendation_metrics_scheduler',
    'app.core.runtime_task_registry', 'app.services.task_queue_service', 'app.services.outbox_service',
    'app.services.practice.projection_reconciliation_service', 'app.services.task_observability_service',
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent, capture_output=True,
        text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stderr
