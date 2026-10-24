"""Architecture guards for the smart weakness-vector orchestration module."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"
MODULE = "app.services.practice.smart_weakness_vector"
SERVICE = APP / "services" / "practice_service.py"


def _call_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def test_module_has_no_application_io_dependencies_or_persistence_calls():
    graph, _ = scan_application(APP)
    assert graph[MODULE] == set()
    assert MODULE in graph["app.services.practice_service"]

    source = (APP / "services" / "practice" / "smart_weakness_vector.py").read_text()
    tree = ast.parse(source)
    assert len(source.splitlines()) <= 180
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50
        if isinstance(node, ast.Call):
            assert _call_name(node.func) not in {
                "execute",
                "scalar",
                "scalars",
                "commit",
                "rollback",
                "begin",
                "begin_nested",
                "flush",
                "add",
            }


def test_real_entry_delegates_exact_ports_and_keeps_query_ownership():
    source = SERVICE.read_text()
    entry = next(
        node
        for node in ast.parse(source).body
        if getattr(node, "name", "") == "_smart_weakness_vector"
    )
    requests = [
        node
        for node in ast.walk(entry)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "SmartWeaknessVectorRequest"
    ]
    assert len(requests) == 1
    assert {
        keyword.arg: ast.unparse(keyword.value) for keyword in requests[0].keywords
    } == {
        "db": "db",
        "user_id": "user_id",
        "subject_code": "subject_code",
        "count": "count",
        "exclude_answered": "exclude_answered",
        "no_repeat_days": "no_repeat_days",
        "use_leitner": "use_leitner",
        "exclude_ids": "exclude_ids",
        "subject_ids": "subject_ids",
        "logger": "logger",
        "resolve_scope_ids": "resolve_subject_ids",
        "load_mastery": "mastery_service.get_user_weak_knowledge_points",
        "compute_weak_kps": "_compute_weak_knowledge_points",
        "load_random": "get_practice_questions",
        "load_vector_recalls": ("vector_retrieval_service.vector_recall_by_text"),
        "load_vector_matches": "load_vector_matches",
        "load_fill_questions": "load_fill_questions",
    }
    # SQL and session calls stay in the two provider closures owned by the
    # historical service entry; the extracted orchestrator has no persistence.
    provider_functions = [
        node
        for node in entry.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert len(provider_functions) == 2
    assert {
        _call_name(node.func)
        for provider in provider_functions
        for node in ast.walk(provider)
        if isinstance(node, ast.Call)
    } >= {"execute", "scalar", "scalars"}


def test_import_does_not_load_application_config_models_or_create_tasks():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError("weakness vector import must stay inert")
asyncio.create_task = forbidden
from app.services.practice.smart_weakness_vector import (
    SmartWeaknessVectorRequest,
    run_smart_weakness_vector,
)
assert callable(run_smart_weakness_vector)
assert SmartWeaknessVectorRequest.__module__.endswith("smart_weakness_vector")
assert dict(os.environ) == before
for name in (
    'app.main', 'app.core.config', 'app.core.database', 'app.models.question',
    'app.services.practice_service', 'sqlalchemy', 'fastapi',
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
