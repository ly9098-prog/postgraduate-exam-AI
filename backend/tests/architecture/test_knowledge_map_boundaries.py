"""Budgets and dependency direction for knowledge-map projections."""

import ast
from pathlib import Path

import pytest

SERVICES = Path(__file__).resolve().parents[2] / "app/services"
PROJECTIONS = (
    "knowledge_map_summary",
    "knowledge_map_hierarchy",
    "knowledge_map_nodes",
)
LEGACY_FUNCTIONS = {
    "get_overview": 62,
    "get_subject_map": 76,
    "_relation_payloads": 74,
    "get_point_detail": 172,
}


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
                module in {"__future__", "collections", "app.core.time_utils"}
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


def test_service_frozen_legacy_budgets():
    source = (SERVICES / "knowledge_map_service.py").read_text()
    assert budget_violations(source, 633, LEGACY_FUNCTIONS) == []
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
