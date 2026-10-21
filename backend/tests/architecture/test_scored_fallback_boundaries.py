"""Scored fill IO consumes caller filters and preserves transaction ownership."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"


def test_fill_dependencies_and_bounded_functions():
    graph, _ = scan_application(APP)
    assert graph["app.services.practice.scored_fallback"] == {"app.models.question"}
    assert "app.services.practice.scored_fallback" in graph["app.services.practice_service"]
    source = (APP / "services/practice/scored_fallback.py").read_text()
    assert len(source.splitlines()) <= 150
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50
        if isinstance(node, ast.Call):
            assert getattr(node.func, "attr", "") not in {
                "commit", "rollback", "begin", "begin_nested",
            }


def test_scored_entry_uses_real_loaders_with_original_filters_and_sampler():
    from app.services import practice_service as svc
    from app.services.practice import scored_fallback, scored_fallback_merge

    source = (APP / "services/practice_service.py").read_text()
    entry = next(node for node in ast.parse(source).body if getattr(node, "name", "") == "get_smart_scored_questions")
    calls = [node for node in ast.walk(entry) if isinstance(node, ast.Call)]
    expected = {
        "load_random_fill_questions": ["db", "fill_cond", "remaining"],
        "load_repeat_fill_questions": ["db", "fill_cond2", "remaining", "_random_sample_query"],
    }
    for name, args in expected.items():
        assert getattr(svc, name) is getattr(scored_fallback, name)
        found = [node for node in calls if getattr(node.func, "id", "") == name]
        assert len(found) == 1 and not found[0].keywords
        assert [ast.unparse(arg) for arg in found[0].args] == args
    assert not any(getattr(node.func, "attr", "") == "execute" for node in calls)
    assert any(getattr(node.func, "id", "") == "_practice_revision_scope_condition" for node in calls)
    assert svc.merge_fill_questions is scored_fallback_merge.merge_fill_questions
    assert sum(
        getattr(node.func, "id", "") == "merge_fill_questions" for node in calls
    ) == 2


def test_import_does_not_load_models_configuration_database_or_create_tasks():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError("fill module import must not create tasks")
asyncio.create_task = forbidden
from app.services.practice.scored_fallback import load_random_fill_questions, load_repeat_fill_questions
assert callable(load_random_fill_questions) and callable(load_repeat_fill_questions)
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
