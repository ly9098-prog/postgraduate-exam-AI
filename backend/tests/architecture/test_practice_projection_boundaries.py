"""Keep projection stages bounded without transferring transaction ownership."""

import ast
from pathlib import Path

import pytest

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"
PRACTICE = APP / "services/practice"
MODULES = (
    "answer_projection_service",
    "answer_projection_stages",
    "projection_reconciliation_service",
    "projection_reconciliation_runtime",
)


def assert_projection_budget(source):
    functions = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert functions
    assert all(node.end_lineno - node.lineno + 1 <= 50 for node in functions)


def assert_stage_transaction_boundary(source):
    assert len(source.splitlines()) <= 300
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            assert getattr(node.func, "attr", "") not in {
                "commit",
                "rollback",
                "begin",
                "begin_nested",
            }
        if isinstance(node, ast.ImportFrom):
            assert node.module not in {
                "app.services.practice.answer_projection_service",
                "app.services.practice.projection_reconciliation_service",
            }
        assert not isinstance(node, ast.Try)


def test_all_projection_functions_and_effect_transaction_ownership_are_bounded():
    for name in MODULES:
        source = (PRACTICE / f"{name}.py").read_text()
        assert len(source.splitlines()) <= 300
        assert_projection_budget(source)
    assert_stage_transaction_boundary(
        (PRACTICE / "answer_projection_stages.py").read_text()
    )
    graph, _ = scan_application(APP)
    stage = "app.services.practice.answer_projection_stages"
    assert stage in graph["app.services.practice.answer_projection_service"]
    assert "app.services.practice.answer_projection_service" not in graph[stage]


@pytest.mark.parametrize(
    "mutation",
    [
        "async def oversized():\n" + "    value = 1\n" * 51,
        "def outer():\n    def nested():\n" + "        value = 1\n" * 51,
    ],
)
def test_budget_rejects_new_oversized_or_nested_helpers(mutation):
    with pytest.raises(AssertionError):
        assert_projection_budget(mutation)


@pytest.mark.parametrize(
    "source",
    [
        "async def stage(db):\n    await db.commit()\n",
        "async def stage(db):\n    await db.rollback()\n",
        "async def stage(db):\n    async with db.begin_nested():\n        pass\n",
        "from app.services.practice.answer_projection_service import project_practice_answer\n",
    ],
)
def test_effect_stage_rejects_transaction_ownership_and_reverse_imports(source):
    with pytest.raises(AssertionError):
        assert_stage_transaction_boundary(source)
