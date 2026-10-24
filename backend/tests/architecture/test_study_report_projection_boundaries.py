"""Study-report projections must remain pure and consumed by the service."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

BACKEND = Path(__file__).resolve().parents[2]
APP = BACKEND / "app"
MODULE = "app.services.study_report_projection"
SERVICE = "app.services.study_report_service"


def test_projection_dependencies_and_budgets():
    graph, _ = scan_application(APP)
    assert graph[MODULE] == set()
    assert MODULE in graph[SERVICE]
    source = (APP / "services/study_report_projection.py").read_text()
    assert len(source.splitlines()) <= 188
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


def test_service_aliases_point_to_actual_projection_definitions():
    from app.services import study_report_projection, study_report_service

    assert study_report_service._safe_accuracy is study_report_projection.safe_accuracy
    assert study_report_service._extract_title is study_report_projection.extract_title
    assert (
        study_report_service._classify_mastery
        is study_report_projection.classify_mastery
    )
    assert (
        study_report_service._mastery_suggestion
        is study_report_projection.mastery_suggestion
    )
    assert study_report_service._calc_priority is study_report_projection.calc_priority

    tree = ast.parse(Path(study_report_service.__file__).read_text())
    definitions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert not definitions & {
        "safe_accuracy",
        "extract_title",
        "classify_mastery",
        "mastery_suggestion",
        "calc_priority",
    }


def test_import_has_no_runtime_resources_or_side_effects():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError("study report projection import must not create tasks")
asyncio.create_task = forbidden
from app.services.study_report_projection import safe_accuracy
assert callable(safe_accuracy)
assert dict(os.environ) == before
for name in (
    'app.main', 'app.core.config', 'app.core.database', 'app.models',
    'app.services.study_report_service', 'sqlalchemy', 'fastapi',
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
