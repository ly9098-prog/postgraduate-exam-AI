"""Bound the pure response modules without splitting transaction ownership."""

import ast
from pathlib import Path

import pytest

SERVICES = Path(__file__).resolve().parents[2] / "app/services"
MODULES = ("exam_read_projection", "exam_result_projection")
PORTS = {
    "_money",
    "_elapsed_seconds",
    "_student_content",
    "_student_options",
    "TERMINAL_ATTEMPT_STATUSES",
    "EXAM408_CORE_CODES",
    "QT_SINGLE_CHOICE",
    "normalize_to_naive_utc",
}


def violations(source):
    tree = ast.parse(source)
    found = []
    if len(source.splitlines()) > 300:
        found.append("module budget")
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.end_lineno - node.lineno + 1 > 50:
                found.append("function budget")
        if isinstance(
            node, (ast.Import, ast.ImportFrom, ast.Await, ast.AsyncFunctionDef)
        ):
            found.append("runtime dependency")
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in {
                "open",
                "eval",
                "exec",
                "__import__",
                "compile",
            }:
                found.append("dynamic execution")
            if isinstance(node.func, ast.Attribute) and node.func.attr in {
                "execute",
                "scalar",
                "scalars",
                "commit",
                "rollback",
                "flush",
                "add",
                "add_all",
                "delete",
                "get_bind",
                "connect",
            }:
                found.append("database operation")
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "ports" and node.attr not in PORTS:
                found.append("unsupported service port")
    return found


@pytest.mark.parametrize("name", MODULES)
def test_projections_are_bounded_and_have_no_runtime_or_database_dependency(name):
    assert violations((SERVICES / f"{name}.py").read_text()) == []


@pytest.mark.parametrize(
    "source",
    [
        "import sqlalchemy",
        "from app.services import exam_service",
        "async def run():\n    pass",
        "client.execute(statement)",
        "session.commit()",
        "other.flush()",
        "open(path)",
        "__import__('app.main')",
        "ports._finalize_attempt()",
        "ports.unknown",
        "\n" * 301,
        "def large():\n" + "    pass\n" * 50,
    ],
)
def test_gate_rejects_dependency_side_effect_or_budget_growth(source):
    assert violations(source)


def test_service_keeps_entry_signatures_and_transaction_owners():
    source = (SERVICES / "exam_service.py").read_text()
    assert len(source.splitlines()) <= 1045
    tree = ast.parse(source)
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert {
        "start_attempt",
        "save_attempt_answer",
        "submit_attempt",
        "_finalize_attempt",
        "abandon_attempt",
        "get_attempt_result",
        "_apply_final_submit_answers",
    } <= functions.keys()
    for name in (
        "start_attempt",
        "save_attempt_answer",
        "_finalize_attempt",
        "abandon_attempt",
    ):
        assert any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "db"
            and node.func.attr == "commit"
            for node in ast.walk(functions[name])
        )
    calls = {
        node.func.value.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
    }
    assert set(MODULES) <= calls
