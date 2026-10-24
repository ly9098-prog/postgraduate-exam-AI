"""Architecture guards for the aggregated smart-practice orchestration module."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"
MODULE = "app.services.practice.aggregated_smart"
SERVICE = APP / "services" / "practice_service.py"


def test_module_has_no_application_io_dependencies_or_persistence_calls():
    graph, _ = scan_application(APP)
    assert graph[MODULE] == set()
    assert MODULE in graph["app.services.practice_service"]

    source = (APP / "services" / "practice" / "aggregated_smart.py").read_text()
    tree = ast.parse(source)
    assert len(source.splitlines()) <= 300
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", getattr(node.func, "id", ""))
            assert name not in {
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


def test_service_entry_delegates_exact_ports_and_keeps_query_ownership():
    source = SERVICE.read_text()
    entry = next(
        node
        for node in ast.parse(source).body
        if getattr(node, "name", "") == "get_aggregated_smart_questions"
    )
    calls = [
        node
        for node in ast.walk(entry)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "run_aggregated_smart"
    ]
    assert len(calls) == 1
    assert {
        keyword.arg: ast.unparse(keyword.value) for keyword in calls[0].keywords
    } == {
        "db": "db",
        "user_id": "user_id",
        "subject_code": "subject_code",
        "subject_ids": "subject_ids",
        "count": "count",
        "exclude_answered": "exclude_answered",
        "no_repeat_days": "no_repeat_days",
        "use_leitner": "use_leitner",
        "request_id": "request_id",
        "smart_strategy": "smart_strategy",
        "logger": "logger",
        "load_subjects": "load_subjects",
        "load_smart": "get_smart_practice_questions",
        "merge_metadata": "_round_robin_merge_with_metadata",
        "finalize": "_finalize_smart",
    }


def test_import_does_not_load_application_config_resources_or_create_tasks():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError("aggregated smart import must stay inert")
asyncio.create_task = forbidden
from app.services.practice.aggregated_smart import run_aggregated_smart
assert callable(run_aggregated_smart)
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
