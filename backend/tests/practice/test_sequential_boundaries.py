"""Bound sequential selection and keep transaction ownership at the caller."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
FILES = ("sequential_service.py", "sequential_selection.py")
TRANSACTION_PORTS = {"commit", "rollback", "flush", "begin", "begin_nested"}


def assert_bounded(source: str) -> set[str]:
    assert len(source.splitlines()) <= 300
    functions = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert functions
    assert all(node.end_lineno - node.lineno + 1 <= 50 for node in functions)
    return {node.name for node in functions}


def assert_no_transaction_owner(tree: ast.AST) -> None:
    assert not [
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in TRANSACTION_PORTS
    ]


def test_service_and_helper_are_nonempty_and_every_function_is_bounded():
    names = {}
    for filename in FILES:
        source = (APP / "services/practice" / filename).read_text()
        names[filename] = assert_bounded(source)
    assert {
        "_reserve_sequential_questions",
        "get_sequential_practice_questions",
        "_get_reset_at",
        "_answered_ids_query",
        "_sequential_scope_key",
        "reset_sequential_progress",
    } <= names["sequential_service.py"]
    assert {"fill_reservations", "read_request_reservations"} <= names[
        "sequential_selection.py"
    ]


def test_selection_avoids_service_dependencies_and_caller_transactions():
    tree = ast.parse((APP / "services/practice/sequential_selection.py").read_text())
    allowed = {
        "__future__",
        "collections.abc",
        "dataclasses",
        "datetime",
        "typing",
        "sqlalchemy.ext.asyncio",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name in allowed for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.module in allowed and not node.level
    assert_no_transaction_owner(tree)
    service = ast.parse((APP / "services/practice/sequential_service.py").read_text())
    # Explicit reset retains its pre-existing commit; issuance never commits.
    for node in service.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name != "reset_sequential_progress":
                assert_no_transaction_owner(node)


@pytest.mark.parametrize("source", ["", "from datetime import datetime"])
def test_budget_rejects_an_empty_function_scan(source):
    with pytest.raises(AssertionError):
        assert_bounded(source)


@pytest.mark.parametrize("prefix", ["def", "async def"])
def test_budget_rejects_new_oversized_helpers(prefix):
    with pytest.raises(AssertionError):
        assert_bounded(f"{prefix} injected():\n" + "    value = 1\n" * 51)


@pytest.mark.parametrize("method", sorted(TRANSACTION_PORTS))
def test_transaction_gate_rejects_injected_ownership(method):
    with pytest.raises(AssertionError):
        assert_no_transaction_owner(
            ast.parse(f"async def injected(db):\n    await db.{method}()")
        )
