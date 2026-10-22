"""Shared learning natural-day projections must remain neutral and bounded."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

BACKEND = Path(__file__).resolve().parents[2]
APP = BACKEND / "app"
MODULE = "app.services.learning_time_projection"
CONSUMERS = {
    "app.services.stats_service": "sqlite/postgresql",
    "app.services.study_report_service": "sqlite/postgresql",
}


def test_projection_dependencies_and_budgets():
    graph, _ = scan_application(APP)
    assert graph[MODULE] == {"app.core.time_utils"}
    assert all(MODULE in graph[consumer] for consumer in CONSUMERS)
    source = (APP / "services/learning_time_projection.py").read_text()
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


def test_both_consumers_use_shared_symbol_without_duplicate_definitions():
    from app.services import (
        learning_time_projection,
        stats_service,
        study_report_service,
    )

    assert stats_service._china_date_expr is learning_time_projection.china_date_expr
    assert (
        study_report_service._china_date_expr
        is learning_time_projection.china_date_expr
    )
    definitions = set()
    for service in (stats_service, study_report_service):
        tree = ast.parse(Path(service.__file__).read_text())
        definitions.update(
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
    assert not definitions & {
        "_china_date_expr",
        "_china_hour_expr",
        "_today_utc",
        "_coerce_date",
    }


def test_import_has_no_runtime_resources_or_side_effects():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError("learning time import must not create tasks")
asyncio.create_task = forbidden
from app.services.learning_time_projection import china_date_expr
assert callable(china_date_expr)
assert dict(os.environ) == before
for name in (
    'app.main', 'app.core.config', 'app.core.database', 'app.models',
    'app.services.stats_service', 'app.services.study_report_service',
    'fastapi',
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
