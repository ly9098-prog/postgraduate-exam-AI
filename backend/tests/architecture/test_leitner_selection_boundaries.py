"""Keep query adaptation bounded and free of runtime imports and transactions."""

import ast
import subprocess
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"
SELECTION = APP / "services/practice/leitner_selection.py"
SERVICE = APP / "services/practice_service.py"


def test_selection_budget_and_dependency_direction():
    source = SELECTION.read_text()
    tree = ast.parse(source, feature_version=(3, 11))
    assert len(source.splitlines()) <= 300
    allowed_imports = {"__future__", "collections.abc", "dataclasses", "typing"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50, node.name
        if isinstance(node, ast.ImportFrom):
            assert node.module in allowed_imports
        assert not isinstance(node, (ast.Import, ast.Try, ast.Delete))
        if isinstance(node, ast.Call):
            assert getattr(node.func, "attr", "") not in {
                "commit",
                "rollback",
                "flush",
                "begin",
                "begin_nested",
                "execute",
                "scalar",
                "create_task",
            }


def test_service_retains_signature_and_supplies_live_namespace():
    tree = ast.parse(SERVICE.read_text())
    entry = next(
        node
        for node in tree.body
        if getattr(node, "name", "") == "_get_questions_with_leitner"
    )
    assert entry.end_lineno - entry.lineno + 1 <= 50
    assert [arg.arg for arg in entry.args.args] == [
        "db",
        "user_id",
        "base_conditions",
        "mode",
        "count",
        "exclude_answered",
        "no_repeat_days",
    ]
    assert [ast.literal_eval(value) for value in entry.args.defaults] == [False, None]
    returned = entry.body[-1]
    assert isinstance(returned, ast.Return) and isinstance(returned.value, ast.Await)
    call = returned.value.value
    assert ast.unparse(call.func) == "run_leitner_selection"
    assert len(call.args) == 1 and call.keywords == []
    request = call.args[0]
    assert ast.unparse(request.func) == "LeitnerSelectionRequest"
    assert {kw.arg: ast.unparse(kw.value) for kw in request.keywords} == {
        "db": "db",
        "user_id": "user_id",
        "base_conditions": "base_conditions",
        "mode": "mode",
        "count": "count",
        "exclude_answered": "exclude_answered",
        "no_repeat_days": "no_repeat_days",
        "namespace": "globals()",
    }


def test_selection_import_does_not_load_runtime_or_orm():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError("selection import must not create tasks")
asyncio.create_task = forbidden
from app.services.practice.leitner_selection import run_leitner_selection
assert callable(run_leitner_selection)
assert dict(os.environ) == before
for name in (
    'app.core.config', 'app.core.database', 'app.services.practice_service',
    'app.models.question', 'sqlalchemy',
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", probe],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
