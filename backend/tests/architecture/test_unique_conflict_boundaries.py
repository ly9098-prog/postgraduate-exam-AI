"""Shared first-write conflict helpers must stay neutral and bounded."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

BACKEND = Path(__file__).resolve().parents[2]
APP = BACKEND / "app"
MODULE = "app.services.unique_conflict"
CONSUMERS = {
    "app.services.adaptive_learning_service",
    "app.services.mastery_service",
}


def test_conflict_helpers_are_shared_and_bounded():
    graph, _ = scan_application(APP)
    assert graph[MODULE] <= {"sqlalchemy"}
    assert all(MODULE in graph[consumer] for consumer in CONSUMERS)
    source = (APP / "services/unique_conflict.py").read_text()
    assert len(source.splitlines()) <= 100
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50
        if isinstance(node, ast.Call):
            assert getattr(node.func, "attr", "") not in {
                "commit",
                "rollback",
                "flush",
                "create_task",
            }


def test_import_has_no_runtime_resources_or_side_effects():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError("unique conflict import must not create tasks")
asyncio.create_task = forbidden
from app.services.unique_conflict import is_unique_violation
assert callable(is_unique_violation)
assert dict(os.environ) == before
for name in (
    'app.main', 'app.core.config', 'app.core.database', 'app.models',
    'app.services.adaptive_learning_service', 'app.services.mastery_service',
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
