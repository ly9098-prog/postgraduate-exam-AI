"""Fallback merging consumes rows and metadata policy without query ownership."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"


def test_merge_dependencies_budgets_and_no_io():
    graph, _ = scan_application(APP)
    assert graph["app.services.practice.scored_fallback_merge"] == {"app.models.question"}
    assert "app.services.practice.scored_fallback_merge" in graph["app.services.practice_service"]
    source = (APP / "services/practice/scored_fallback_merge.py").read_text()
    tree = ast.parse(source)
    assert len(source.splitlines()) <= 100
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50
        if isinstance(node, ast.Call):
            assert getattr(node.func, "attr", "") not in {
                "execute", "commit", "rollback", "begin", "begin_nested",
            }


def test_scored_entry_uses_real_merge_for_both_different_fallback_rules():
    from app.services import practice_service as svc
    from app.services.practice import scored_fallback_flow, scored_fallback_merge

    source = (APP / "services/practice_service.py").read_text()
    entry = next(
        node for node in ast.parse(source).body
        if getattr(node, "name", "") == "_complete_scored_selection"
    )
    text = ast.unparse(entry)
    assert svc.merge_fill_questions is scored_fallback_merge.merge_fill_questions
    assert svc.run_scored_fallback is scored_fallback_flow.run_scored_fallback
    assert "merge_fill=merge_fill_questions" in text
    assert "metadata_factory=_build_fallback_metadata" in text
    flow_source = (APP / "services/practice/scored_fallback_flow.py").read_text()
    flow_text = ast.unparse(ast.parse(flow_source))
    assert flow_text.count("skip_duplicates=False") == 1
    assert flow_text.count("skip_duplicates=True") == 1
    assert not any(isinstance(node, ast.For) for node in entry.body)
    assert not any(
        getattr(node.func, "id", "") == "_build_fallback_metadata"
        for node in ast.walk(entry) if isinstance(node, ast.Call)
    )


def test_import_does_not_load_models_database_configuration_or_create_tasks():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError("merge import must not create tasks")
asyncio.create_task = forbidden
from app.services.practice.scored_fallback_merge import merge_fill_questions
assert callable(merge_fill_questions)
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
