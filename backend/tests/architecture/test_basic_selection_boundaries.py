"""Constrain eligibility assembly without moving persistence into the module."""

import ast
import subprocess
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"
MODULE = APP / "services/practice/basic_selection.py"
SERVICE = APP / "services/practice_service.py"


def test_selection_is_bounded_and_has_no_runtime_imports_or_transactions():
    source = MODULE.read_text()
    tree = ast.parse(source, feature_version=(3, 11))
    assert len(source.splitlines()) <= 300
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50, node.name
        if isinstance(node, ast.ImportFrom):
            assert node.module in {
                "__future__",
                "collections.abc",
                "dataclasses",
                "typing",
            }
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


def entries():
    return {
        node.name: node
        for node in ast.parse(SERVICE.read_text()).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def option_keywords(entry):
    request = next(
        node
        for node in ast.walk(entry)
        if isinstance(node, ast.Call)
        and ast.unparse(node.func) == "BasicSelectionOptions"
    )
    assert not request.args
    return {kw.arg: ast.unparse(kw.value) for kw in request.keywords}


def test_both_service_entries_bind_original_options_and_live_namespace():
    for name in ("get_practice_questions", "get_aggregated_random_questions"):
        entry = entries()[name]
        assert entry.end_lineno - entry.lineno + 1 <= 50
        assert option_keywords(entry) == {
            "user_id": "user_id",
            "knowledge_points": "knowledge_points",
            "knowledge_point_ids": "knowledge_point_ids",
            "exclude_answered": "exclude_answered",
            "no_repeat_days": "no_repeat_days",
            "use_leitner": "use_leitner",
            "namespace": "globals()",
        }


def test_basic_entry_forwards_exact_scope_and_pool_size():
    call = entries()["get_practice_questions"].body[-1].value.value
    assert ast.unparse(call.func) == "run_basic_selection"
    assert [ast.unparse(arg) for arg in call.args] == ["db", "subject_code"]
    assert {
        kw.arg: ast.unparse(kw.value) for kw in call.keywords if kw.arg != "options"
    } == {"count": "count", "mode": "mode", "subject_ids": "subject_ids"}


def test_aggregation_remains_owned_by_existing_aggregator():
    entry = entries()["get_aggregated_random_questions"]
    call = entry.body[-1].value.value
    assert ast.unparse(call.func) == "run_aggregated_random"
    request = call.args[0]
    assert ast.unparse(request.func) == "AggregatedRandomRequest"
    assert {kw.arg: ast.unparse(kw.value) for kw in request.keywords} == {
        "db": "db",
        "subject_code": "subject_code",
        "subject_ids": "subject_ids",
        "count": "count",
        "logger": "logger",
        "load_bucket": "load_bucket",
        "merge": "_round_robin_merge",
    }
    binding = next(
        node
        for node in ast.walk(entry)
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "bind_random_bucket"
    )
    assert ast.unparse(binding.args[0].func) == "BasicSelectionOptions"


def test_import_does_not_load_orm_or_configuration():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError("selection import must not create tasks")
asyncio.create_task = forbidden
from app.services.practice.basic_selection import run_basic_selection
assert callable(run_basic_selection)
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
