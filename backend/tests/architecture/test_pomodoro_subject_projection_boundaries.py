"""Keep focus subject projection independent from persistence and HTTP."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"
MODULE = "app.services.pomodoro_subject_projection"
NAMES = {
    "resolve_subject",
    "resolve_allocations",
    "allocation_group_key",
    "allocate_seconds_by_weight",
}


def test_projection_dependencies_and_function_budgets():
    graph, _ = scan_application(APP)
    assert graph[MODULE] == {"app.core.subject_scope"}
    source = (APP / "services/pomodoro_subject_projection.py").read_text()
    assert len(source.splitlines()) <= 100
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50
        if isinstance(node, ast.Call):
            assert getattr(node.func, "attr", "") not in {
                "execute",
                "commit",
                "rollback",
                "flush",
                "create_task",
            }


def test_real_snapshot_consumes_projection_without_duplicate_implementations():
    from app.core.subject_scope import EXAM408_CORE_CODES
    from app.services import pomodoro_service, pomodoro_subject_projection

    assert EXAM408_CORE_CODES == (
        "data_structure",
        "computer_organization",
        "operating_system",
        "computer_network",
    )
    tree = ast.parse((APP / "services/pomodoro_service.py").read_text())
    definitions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert not definitions & (NAMES | {f"_{name}" for name in NAMES})
    snapshot = next(
        node
        for node in tree.body
        if getattr(node, "name", "") == "_accumulate_snapshot_sessions"
    )
    calls = {
        node.func.id: node
        for node in ast.walk(snapshot)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    focus_ports = {
        keyword.arg: ast.unparse(keyword.value)
        for keyword in calls["accumulate_focus_sessions"].keywords
    }
    supplemental_ports = {
        keyword.arg: ast.unparse(keyword.value)
        for keyword in calls["accumulate_supplemental_sessions"].keywords
    }
    assert {
        "resolve_allocations": "resolve_allocations",
        "allocation_group_key": "allocation_group_key",
        "allocate_seconds": "allocate_seconds_by_weight",
    }.items() <= focus_ports.items()
    assert supplemental_ports["resolve_subject"] == "resolve_subject"
    for name in NAMES:
        assert getattr(pomodoro_service, name) is getattr(
            pomodoro_subject_projection, name
        )


def test_new_process_projection_import_has_no_runtime_resources():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError("projection import must not create tasks")
asyncio.create_task = forbidden
from app.services.pomodoro_subject_projection import resolve_allocations
assert callable(resolve_allocations)
assert dict(os.environ) == before
for name in (
    'app.main', 'app.core.config', 'app.core.database', 'app.models.pomodoro',
    'app.services.pomodoro_service', 'sqlalchemy', 'fastapi',
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=APP.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
