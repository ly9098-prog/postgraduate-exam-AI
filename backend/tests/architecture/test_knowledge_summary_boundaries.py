"""Bound knowledge summaries and keep signed/read-time projections free of IO."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
PURE = (
    "knowledge_summary_baseline",
    "knowledge_summary_points",
    "knowledge_summary_projection",
)


def assert_bounded(source):
    assert len(source.splitlines()) <= 300
    functions = [
        n
        for n in ast.walk(ast.parse(source))
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert functions
    assert all(n.end_lineno - n.lineno + 1 <= 50 for n in functions)
    return {n.name for n in functions}


def assert_pure(source):
    for n in ast.walk(ast.parse(source)):
        assert not isinstance(n, (ast.Await, ast.AsyncFunctionDef))
        if isinstance(n, ast.Import):
            raise AssertionError("projection requires no module imports")
        if isinstance(n, ast.ImportFrom):
            assert not n.level and n.module in {
                "__future__",
                "collections",
                "collections.abc",
                "typing",
            }
        if isinstance(n, ast.Call):
            assert getattr(n.func, "id", "") not in {
                "open",
                "exec",
                "eval",
                "__import__",
            }
            assert getattr(n.func, "attr", "") not in {
                "execute",
                "scalar",
                "scalars",
                "commit",
                "rollback",
                "flush",
                "begin",
                "begin_nested",
                "read_text",
                "write_text",
            }


def test_all_summary_functions_are_bounded_and_projections_stay_pure():
    for name in ("knowledge_session_summary", *PURE):
        source = (APP / f"services/practice/{name}.py").read_text()
        names = assert_bounded(source)
        if name in PURE:
            assert_pure(source)
        else:
            assert {
                "build_issue_knowledge_context",
                "get_session_knowledge_summary",
            } <= names
            calls = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call)]
            assert not any(
                getattr(n.func, "attr", "")
                in {
                    "commit",
                    "rollback",
                    "flush",
                    "begin",
                    "begin_nested",
                }
                for n in calls
            )


@pytest.mark.parametrize(
    "source",
    [
        "from app.core import database",
        "def injected(db):\n    return db.execute('SELECT 1')",
        "def injected():\n    return open('file').read()",
        "async def injected():\n    pass",
    ],
)
def test_projection_rejects_runtime_imports_io_and_async(source):
    with pytest.raises(AssertionError):
        assert_pure(source)


def test_budget_rejects_future_oversized_helpers():
    with pytest.raises(AssertionError):
        assert_bounded("def injected():\n" + "    value = 1\n" * 51)


def test_pure_projection_import_does_not_load_service_or_database():
    probe = """
import importlib, sys
for name in sys.argv[1:]:
    importlib.import_module('app.services.practice.' + name)
for name in (
    'app.core.config', 'app.core.database', 'app.models.practice_record',
    'app.services.practice.knowledge_session_summary', 'sqlalchemy',
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe, *PURE],
        cwd=APP.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
