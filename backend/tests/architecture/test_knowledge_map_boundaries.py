"""Budgets and dependency direction for knowledge-map projections."""

import ast
from pathlib import Path

import pytest

SERVICES = Path(__file__).resolve().parents[2] / "app/services"
PROJECTIONS = (
    "knowledge_map_summary",
    "knowledge_map_hierarchy",
    "knowledge_map_nodes",
    "knowledge_map_topology",
    "knowledge_map_relations",
    "knowledge_map_detail",
)


def budget_violations(source, ceiling, function_ceilings=None):
    violations = []
    if len(source.splitlines()) > ceiling:
        violations.append("file budget")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            limit = (function_ceilings or {}).get(node.name, 50)
            if node.end_lineno - node.lineno + 1 > limit:
                violations.append(f"function budget: {node.name}")
    return violations


def dependency_violations(source):
    violations = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules = [item.name for item in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [node.module or ""]
            if node.level:
                violations.append("relative import")
        else:
            modules = []
        for module in modules:
            if not (
                module
                in {
                    "__future__",
                    "collections",
                    "app.core.time_utils",
                    "app.core.subject_scope",
                }
                or module.startswith("app.models.")
                or module == "app.services.knowledge_map_summary"
            ):
                violations.append(f"dependency: {module}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in {"__import__", "eval", "exec"}:
                violations.append("dynamic execution")
    return violations


@pytest.mark.parametrize("module", PROJECTIONS)
def test_projection_budgets_and_dependencies(module):
    source = (SERVICES / f"{module}.py").read_text()
    assert budget_violations(source, 300) == []
    assert dependency_violations(source) == []


def test_service_budgets_and_projection_ownership():
    source = (SERVICES / "knowledge_map_service.py").read_text()
    assert budget_violations(source, 195) == []
    functions = {
        node.name
        for node in ast.parse(source).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert not functions.intersection(
        {
            "_state_status",
            "_build_subject_summary",
            "_build_hierarchy_metadata",
            "_node_payload",
        }
    )
    assert "select(" not in source
    assert "db.execute" not in source
    assert "db.scalars" not in source


def test_all_map_modules_are_registered_and_bounded():
    expected = {*PROJECTIONS, "knowledge_map_service", "knowledge_map_queries"}
    assert {path.stem for path in SERVICES.glob("knowledge_map*.py")} == expected
    for name in expected:
        source = (SERVICES / f"{name}.py").read_text()
        assert budget_violations(source, 300) == [], name
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "db":
                    assert node.func.attr not in {
                        "commit",
                        "rollback",
                        "flush",
                        "delete",
                        "add",
                        "add_all",
                    }, name


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("import sqlalchemy", "dependency: sqlalchemy"),
        ("from app.services import knowledge_map_service", "dependency: app.services"),
        ("from app.api.v1 import knowledge_map", "dependency: app.api.v1"),
        ("from .knowledge_map_summary import _state_status", "relative import"),
        ("__import__('sqlalchemy')", "dynamic execution"),
    ],
)
def test_dependency_gate_rejects_invalid_projection(source, expected):
    assert expected in dependency_violations(source)


def test_budgets_reject_growth():
    assert "file budget" in budget_violations("\n" * 301, 300)
    source = "def large():\n" + "    pass\n" * 50
    assert "function budget: large" in budget_violations(source, 300)
