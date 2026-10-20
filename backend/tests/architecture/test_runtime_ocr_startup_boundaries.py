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
        "app.features.ocr_gateway", "app.services.ocr_worker_client", "app.services.ocr_service",
    }
    assert "app.services.runtime_ocr_startup" in graph["app.main"]
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
    assert [ast.unparse(arg) for arg in initialize[0].args] == ["_ocr_resources", "role"]
    assert not initialize[0].keywords
    owner = next(node for node in ast.walk(life) if isinstance(node, ast.Try) and any(item is initialize[0] for item in ast.walk(node)))
    assert len(owner.handlers) == 1 and ast.unparse(owner.handlers[0].type) == "Exception"
    assert ast.unparse(owner.handlers[0].body[0]) == "report_http_startup_failure('OCR Gateway', e, _production_mode)"
    role = next(node for node in life.body if isinstance(node, ast.If) and owner in node.body)
    assert ast.unparse(role.test) == "role in ('web', 'all')"
    lag = next(node for node in calls if node.func.id == "monitor_event_loop_lag")
    assert allocation[0].lineno < lag.lineno < initialize[0].lineno
    first, second = runtime_ocr_startup.HttpOcrResources(), runtime_ocr_startup.HttpOcrResources()
    assert first is not second and first.gateway is first.shared_http_client is None
    first.gateway = object()
    assert second.gateway is None


def test_importing_ocr_startup_does_not_load_resources_or_create_tasks():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError('import must not create tasks')
asyncio.create_task = forbidden
from app.services.runtime_ocr_startup import HttpOcrResources, initialize_http_ocr_gateway
assert HttpOcrResources().gateway is None
assert callable(initialize_http_ocr_gateway)
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
