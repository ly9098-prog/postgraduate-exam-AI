"""Budget and dependency boundaries for practice-batch persistence and commit."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
PERSISTENCE = APP / "services/practice/batch_persistence.py"
COMMIT = APP / "services/practice/batch_commit.py"

PERSISTENCE_IMPORTS = {
    "__future__": {"annotations"},
    "collections.abc": {"Awaitable", "Callable"},
    "dataclasses": {"dataclass"},
    "datetime": {"datetime"},
    "typing": {"Any"},
    "sqlalchemy.ext.asyncio": {"AsyncSession"},
    "app.models.practice_record": {"PracticeRecord"},
}
COMMIT_IMPORTS = {
    "__future__": {"annotations"},
    "collections.abc": {"Awaitable", "Callable"},
    "dataclasses": {"dataclass"},
    "typing": {"Any"},
    "sqlalchemy.ext.asyncio": {"AsyncSession"},
}


def inspect_boundary(source: str, imports: dict[str, set[str] | None]):
    assert len(source.splitlines()) <= 300
    tree = ast.parse(source, feature_version=(3, 11))
    functions: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node.end_lineno - node.lineno + 1)
        if isinstance(node, ast.Import):
            assert all(
                alias.name in imports and imports[alias.name] is None
                for alias in node.names
            )
        if isinstance(node, ast.ImportFrom):
            assert not node.level and node.module in imports
            assert imports[node.module] is not None
            assert all(alias.name in imports[node.module] for alias in node.names)
        if isinstance(node, ast.Call):
            assert getattr(node.func, "id", "") not in {
                "open",
                "exec",
                "eval",
                "__import__",
            }
            assert getattr(node.func, "attr", "") not in {
                "urlopen",
                "request",
                "socket",
                "connect",
                "send",
                "recv",
                "system",
                "popen",
                "Popen",
                "run",
            }
    assert functions and max(functions) <= 50
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def test_practice_batch_modules_keep_their_budget_and_dependency_ownership():
    assert {
        "_build_practice_record",
        "_stage_practice_batch_records",
        "_persist_practice_wrong_record",
        "persist_practice_batch_records",
    } <= inspect_boundary(PERSISTENCE.read_text(), PERSISTENCE_IMPORTS)
    assert {
        "_ClaimedPracticeBatchRequest",
        "_build_claimed_practice_response",
        "_finalize_claimed_practice_batch",
        "_run_claimed_practice_batch",
        "persist_claimed_practice_batch",
    } <= inspect_boundary(COMMIT.read_text(), COMMIT_IMPORTS)


def test_persistence_never_owns_transaction_commit_or_rollback():
    tree = ast.parse(PERSISTENCE.read_text(), feature_version=(3, 11))
    assert not {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in {"commit", "rollback"}
    }


@pytest.mark.parametrize(
    "source,imports",
    [
        (
            "from sqlalchemy import select\ndef small():\n    pass\n",
            PERSISTENCE_IMPORTS,
        ),
        (
            "from app.services.practice_service import logger\ndef small():\n    pass\n",
            COMMIT_IMPORTS,
        ),
        (
            "from .batch_commit import persist_claimed_practice_batch\ndef small():\n    pass\n",
            PERSISTENCE_IMPORTS,
        ),
        ("import httpx\ndef small():\n    pass\n", COMMIT_IMPORTS),
        ("def small():\n    return open('payload').read()\n", PERSISTENCE_IMPORTS),
        ("def small():\n    return __import__('socket')\n", COMMIT_IMPORTS),
        ("def outer():\n    def inner():\n" + "        pass\n" * 51, COMMIT_IMPORTS),
        ("async def small():\n" + "    pass\n" * 51, PERSISTENCE_IMPORTS),
    ],
)
def test_practice_batch_boundary_rejects_injected_dependency_or_budget(source, imports):
    with pytest.raises(AssertionError):
        inspect_boundary(source, imports)
