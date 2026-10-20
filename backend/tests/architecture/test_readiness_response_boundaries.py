"""The readiness decision must not execute probes or load application runtime."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"


def test_readiness_projection_is_neutral_and_within_budget():
    graph, _ = scan_application(APP)
    assert graph["app.core.readiness_response"] == set()
    assert "app.core.readiness_response" in graph["app.main"]
    source = (APP / "core/readiness_response.py").read_text()
    assert len(source.splitlines()) <= 300
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50, node.name
    main = ast.parse((APP / "main.py").read_text())
    endpoint = next(n for n in main.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "ready_health")
    called = [
        node.func.id for node in ast.walk(endpoint)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert called.count("build_readiness_response") == 1
    assert called.count("ReadinessSnapshot") == 1


def test_readiness_projection_imports_without_settings_database_or_main():
    probe = """
import sys
from app.core.readiness_response import ReadinessSnapshot, build_readiness_response
assert callable(build_readiness_response)
for name in ('app.main', 'app.core.config', 'app.core.database', 'fastapi',
             'app.services.task_queue_worker', 'app.services.staging_storage'):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
