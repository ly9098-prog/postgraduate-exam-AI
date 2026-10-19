"""Keep shared subject lookup independent of administrative mutations."""

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
RESOLVERS = {"resolve_subject_id", "resolve_subject_ids"}
ADMIN_SERVICE = "app.services.admin_subject_service"


def _violations(source: str) -> list[int]:
    tree = ast.parse(source)
    return [
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == ADMIN_SERVICE
        and any(alias.name in RESOLVERS or alias.name == "*" for alias in node.names)
    ]


def test_no_consumer_uses_admin_subject_lookup():
    files = sorted(APP.rglob("*.py"))
    assert files and APP / "services" / "practice_service.py" in files
    violations = {
        str(path.relative_to(APP)): lines
        for path in files if (lines := _violations(path.read_text(encoding="utf-8")))
    }
    assert not violations


@pytest.mark.parametrize("source", [
    "from app.services.admin_subject_service import resolve_subject_id",
    "from app.services.admin_subject_service import resolve_subject_ids as scope",
    "from app.services.admin_subject_service import *",
])
def test_lookup_boundary_detects_injected_import(source):
    assert _violations(source) == [1]


def test_admin_mutations_remain_available():
    assert not _violations("from app.services.admin_subject_service import update_subject")


def test_shared_lookup_has_no_admin_transport_or_transaction_ownership():
    path = APP / "services" / "subject_resolution.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = [
        node.module for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    ]
    assert set(imports) == {"sqlalchemy", "sqlalchemy.ext.asyncio", "app.models.admin"}
    calls = [
        node.func.attr for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name) and node.func.value.id == "db"
    ]
    assert not {"commit", "rollback", "flush", "delete", "add"} & set(calls)
    assert len(path.read_text().splitlines()) <= 300
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50
