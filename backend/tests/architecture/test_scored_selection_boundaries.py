"""Diversity policy stays neutral while the scored caller owns IO and reasons."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"


def test_selection_dependencies_and_budgets():
    graph, _ = scan_application(APP)
    assert graph["app.services.practice.scored_selection"] == {"app.models.question"}
    assert "app.services.practice.scored_selection" in graph["app.services.practice_service"]
    source = (APP / "services/practice/scored_selection.py").read_text()
    assert len(source.splitlines()) <= 100
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50


def test_real_scored_caller_keeps_projection_and_fallback_ownership():
    from app.services import practice_service
    from app.services.practice.scored_selection import select_scored_candidates

    assert practice_service.select_scored_candidates is select_scored_candidates
    source = (APP / "services/practice_service.py").read_text()
    tree = ast.parse(source)
    entry = next(node for node in tree.body if getattr(node, "name", "") == "get_smart_scored_questions")
    calls = [node for node in ast.walk(entry) if isinstance(node, ast.Call)]
    policy_calls = [node for node in calls if getattr(node.func, "id", "") == "select_scored_candidates"]
    assert len(policy_calls) == 1
    assert [ast.unparse(arg) for arg in policy_calls[0].args] == [
        "scored", "count", "q_kp_map", "metadata", "scored_metadata",
    ]
    assert not policy_calls[0].keywords
    assert not any(isinstance(node, ast.Name) and node.id == "max_per_kp" for node in ast.walk(entry))
    projection = next(node for node in entry.body if getattr(node, "name", "") == "scored_metadata")
    assert "_build_scored_metadata" in ast.unparse(projection)
    assert "scored_runtime.get('strategy_config_id')" in ast.unparse(projection)
    assert any(getattr(node.func, "attr", "") == "execute" for node in calls)
    assert any(getattr(node.func, "id", "") == "calculate_smart_score" for node in calls)


def test_import_has_no_runtime_or_resource_side_effects():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError("selection import must not create tasks")
asyncio.create_task = forbidden
from app.services.practice.scored_selection import select_scored_candidates
assert callable(select_scored_candidates)
assert dict(os.environ) == before
for name in (
    'app.main', 'app.core.config', 'app.core.database', 'app.models.question',
    'app.services.practice_service', 'sqlalchemy',
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
