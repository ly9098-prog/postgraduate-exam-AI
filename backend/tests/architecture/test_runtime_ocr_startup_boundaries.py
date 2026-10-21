"""OCR resource assembly stays lazy and lifespan retains partial resources."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"


def test_ocr_startup_dependencies_and_budgets():
    graph, _ = scan_application(APP)
    assert graph["app.services.runtime_ocr_startup"] == {
        "app.core.ocr_runtime_config", "app.core.deployment_profile",
        "app.features.ocr_gateway", "app.services.ocr_worker_client",
        "app.services.ocr_service",
    }
    assert "app.services.runtime_ocr_startup" in graph["app.main"]
    assert "app.services.runtime_ocr_startup" in graph["app.core.bootstrap"]
    source = (APP / "services/runtime_ocr_startup.py").read_text()
    assert len(source.splitlines()) <= 300
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50


def test_lifespan_owns_resource_state_and_original_startup_failure_position():
    from app import main
    from app.services import runtime_ocr_startup

    assert main.HttpOcrResources is runtime_ocr_startup.HttpOcrResources
    assert main.initialize_http_ocr_gateway is runtime_ocr_startup.initialize_http_ocr_gateway
    source = (APP / "main.py").read_text()
    tree = ast.parse(source)
    life = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan")
    calls = [node for node in ast.walk(life) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
    allocation = [node for node in calls if node.func.id == "HttpOcrResources"]
    initialize = [node for node in calls if node.func.id == "initialize_http_ocr_gateway"]
    assert len(allocation) == len(initialize) == 1
    assert not allocation[0].args and not allocation[0].keywords
    assert [ast.unparse(arg) for arg in initialize[0].args] == ["ocr_resources", "role"]
    assert not initialize[0].keywords
    owner = next(
        node for node in ast.walk(life)
        if isinstance(node, ast.Try) and len(node.handlers) == 1
        and any(item is initialize[0] for item in ast.walk(node))
    )
    assert len(owner.handlers) == 1 and ast.unparse(owner.handlers[0].type) == "Exception"
    assert ast.unparse(owner.handlers[0].body[0]) == "report_http_startup_failure('OCR Gateway', e, _production_mode)"
    role = next(node for node in ast.walk(life) if isinstance(node, ast.If) and owner in node.body)
    assert ast.unparse(role.test) == "role in ('web', 'all')"
    lag = next(node for node in calls if node.func.id == "monitor_event_loop_lag")
    assert allocation[0].lineno < lag.lineno < initialize[0].lineno
    first, second = runtime_ocr_startup.HttpOcrResources(), runtime_ocr_startup.HttpOcrResources()
    assert first is not second and first.gateway is first.shared_http_client is None
    first.gateway = object()
    assert second.gateway is None


def test_worker_uses_real_assembly_with_pre_resolved_profile_logger_and_original_position():
    from app.core import bootstrap
    from app.services import runtime_ocr_startup

    assert bootstrap.initialize_worker_ocr_gateway is runtime_ocr_startup.initialize_worker_ocr_gateway
    source = (APP / "core/bootstrap.py").read_text()
    runtime = next(
        node for node in ast.parse(source).body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_init_worker_dependencies"
    )
    calls = [node for node in ast.walk(runtime) if isinstance(node, ast.Call)]
    initialize = [node for node in calls if getattr(node.func, "id", None) == "initialize_worker_ocr_gateway"]
    assert len(initialize) == 1
    assert [ast.unparse(arg) for arg in initialize[0].args] == [
        "profile", "logger", "resources.ocr"
    ]
    assert not initialize[0].keywords
    executor = next(
        node for node in calls
        if getattr(node.func, "id", None) == "initialize_worker_executors"
    )
    reconciler = next(node for node in calls if getattr(node.func, "attr", None) == "start_orphan_reconciler")
    assert executor.lineno < initialize[0].lineno < reconciler.lineno
    assert runtime.end_lineno - runtime.lineno + 1 <= 50
    assert not any(isinstance(node, ast.ImportFrom) and node.module == "app.core.ocr_runtime_config" for node in ast.walk(runtime))


def test_worker_partial_ocr_failure_remains_owned_by_role_cleanup():
    source = (APP / "core/bootstrap.py").read_text()
    tree = ast.parse(source)
    runner = next(
        node for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_run_standalone_role"
    )
    cleanup_calls = [
        node for node in ast.walk(runner)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "cleanup_failed_startup"
    ]
    assert len(cleanup_calls) == 2
    handlers = next(node for node in runner.body if isinstance(node, ast.Try)).handlers
    handler_types = [ast.unparse(handler.type) for handler in handlers]
    assert handler_types == ["asyncio.CancelledError", "SystemError", "Exception"]


def test_startup_cleanup_coordinator_owns_exception_and_logger_boundaries():
    source = (APP / "core/runtime_startup_cleanup.py").read_text()
    tree = ast.parse(source)
    graph, _ = scan_application(APP)
    assert graph["app.core.runtime_startup_cleanup"] == set()
    assert len(source.splitlines()) <= 300
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50
    cleanup = next(
        node for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "cleanup_failed_startup"
    )
    handlers = [
        node for node in ast.walk(cleanup)
        if isinstance(node, ast.ExceptHandler)
    ]
    assert len(handlers) == 2
    assert [ast.unparse(node.type) for node in handlers] == [
        "(Exception, asyncio.CancelledError)",
        "(Exception, asyncio.CancelledError)",
    ]
    assert not any(
        isinstance(node, ast.Raise) for node in ast.walk(cleanup)
    )
    rethrow = next(
        node for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "rethrow_startup_failure"
    )
    assert any(
        isinstance(node, ast.ExceptHandler)
        and ast.unparse(node.type) == "(Exception, asyncio.CancelledError)"
        for node in ast.walk(rethrow)
    )


def test_ocr_resource_ownership_is_retained_only_until_gateway_construction():
    source = (APP / "services/runtime_ocr_startup.py").read_text()
    tree = ast.parse(source)
    worker = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "initialize_worker_ocr_gateway"
    )
    statements = [
        ast.unparse(node) for node in worker.body
        if isinstance(node, (ast.Assign, ast.If))
    ]
    assert any("resources.worker_client = worker_client" in item for item in statements)
    assert any("resources.gateway = ocr_gateway" in item for item in statements)
    transfer = next(
        node for node in ast.walk(worker)
        if isinstance(node, ast.Assign)
        and ast.unparse(node.targets[0]) == "resources.worker_client"
        and ast.unparse(node.value) == "None"
    )
    gateway = next(
        node for node in ast.walk(worker)
        if isinstance(node, ast.Assign)
        and ast.unparse(node.targets[0]) == "resources.gateway"
    )
    publish = next(
        node for node in ast.walk(worker)
        if isinstance(node, ast.ImportFrom)
        and node.module == "app.services.ocr_service"
    )
    assert gateway.lineno < transfer.lineno < publish.lineno
    resources = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "HttpOcrResources"
    )
    fields = [
        node.target.id for node in resources.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    ]
    assert fields == ["gateway", "shared_http_client", "worker_client"]


def test_importing_ocr_startup_does_not_load_resources_or_create_tasks():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError('import must not create tasks')
asyncio.create_task = forbidden
from app.services.runtime_ocr_startup import (
    HttpOcrResources, initialize_http_ocr_gateway, initialize_worker_ocr_gateway,
)
assert HttpOcrResources().gateway is None
assert callable(initialize_http_ocr_gateway)
assert callable(initialize_worker_ocr_gateway)
assert before == dict(os.environ)
for name in (
    'app.main', 'app.core.config', 'app.core.database', 'httpx', 'app.core.ocr_runtime_config',
    'app.core.deployment_profile', 'app.features.ocr_gateway', 'app.services.ocr_worker_client',
    'app.services.ocr_service', 'paddle', 'paddleocr',
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent, capture_output=True,
        text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stderr
