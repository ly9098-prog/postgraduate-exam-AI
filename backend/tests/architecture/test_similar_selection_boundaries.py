"""Keep candidate assembly bounded and separate from issuance/persistence."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"
MODULE = APP / "services/practice/similar_selection.py"
SERVICE = APP / "services/practice_service.py"


def check_module(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50, node.name
        if isinstance(node, ast.ImportFrom):
            assert node.module in {"__future__", "typing", "app.services"}
            if node.module == "app.services":
                assert [name.name for name in node.names] == [
                    "vector_retrieval_service"
                ]
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
                "ensure_future",
                "connect",
            }


def test_selection_dependencies_and_function_budgets():
    source = MODULE.read_text()
    assert len(source.splitlines()) <= 300
    check_module(ast.parse(source, feature_version=(3, 11)))
    graph, _ = scan_application(APP)
    assert graph["app.services.practice.similar_selection"] == {
        "app.services",
        "app.services.vector_retrieval_service",
    }


@pytest.mark.parametrize("operation", ["commit", "execute", "create_task"])
def test_gate_rejects_new_transaction_or_runtime_ownership(operation):
    tree = ast.parse(MODULE.read_text())
    entry = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef))
    entry.body.append(ast.parse(f"owner.{operation}()").body[0])
    with pytest.raises(AssertionError):
        check_module(tree)


def test_service_keeps_scope_resolution_and_exact_candidate_options():
    from app.services import practice_service as svc
    from app.services.practice.similar_selection import run_similar_selection

    assert svc.run_similar_selection is run_similar_selection
    entry = next(
        node
        for node in ast.parse(SERVICE.read_text()).body
        if getattr(node, "name", "") == "get_similar_practice_questions"
    )
    assert entry.end_lineno - entry.lineno + 1 <= 50
    assert [arg.arg for arg in entry.args.args] == [
        "db",
        "user_id",
        "subject_code",
        "source_question_id",
        "count",
        "exclude_answered",
        "no_repeat_days",
        "use_leitner",
        "subject_ids",
    ]
    assert [ast.literal_eval(value) for value in entry.args.defaults] == [
        20,
        False,
        None,
        True,
        None,
    ]
    scope = entry.body[1]
    assert ast.unparse(scope.targets[0]) == "scope_ids"
    assert ast.unparse(scope.value) == (
        "subject_ids if subject_ids is not None else "
        "await resolve_subject_ids(db, subject_code)"
    )
    call = entry.body[-1].value.value
    assert ast.unparse(call.func) == "run_similar_selection"
    assert [ast.unparse(arg) for arg in call.args] == [
        "db",
        "user_id",
        "source_question_id",
        "scope_ids",
    ]
    assert {kw.arg: ast.unparse(kw.value) for kw in call.keywords} == {
        "count": "count",
        "exclude_answered": "exclude_answered",
        "no_repeat_days": "no_repeat_days",
        "namespace": "globals()",
    }


def test_import_does_not_load_runtime_orm_or_vector_provider():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError("similar import must not create tasks")
asyncio.create_task = forbidden
from app.services.practice.similar_selection import run_similar_selection
assert callable(run_similar_selection)
assert dict(os.environ) == before
for name in (
    'app.core.config', 'app.core.database', 'app.services.practice_service',
    'app.services.vector_retrieval_service', 'app.models.question', 'sqlalchemy',
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
