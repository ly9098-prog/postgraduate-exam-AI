"""Budget and dependency gates for smart-practice branch/scope helpers."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
BRANCHES = APP / "services/practice/smart_branches.py"
ENTRY = APP / "services/practice/smart_entry.py"
SCOPE = APP / "services/practice/session_scope.py"

BRANCH_IMPORTS = {
    "__future__": {"annotations"},
    "collections.abc": {"Awaitable", "Callable"},
    "dataclasses": {"dataclass"},
    "logging": {"Logger"},
    "typing": {"Any"},
    "sqlalchemy.ext.asyncio": {"AsyncSession"},
    "app.services.practice.smart_scored_supplement": {
        "ScoredSupplementRequest",
        "run_scored_supplement",
    },
    "app.services.practice.smart_path_supplement": {
        "SmartPathRequest",
        "run_smart_path",
    },
}
ENTRY_IMPORTS = {
    **BRANCH_IMPORTS,
    "app.services.practice.smart_branches": {
        "SmartBranchProviders",
        "SmartBranchRequest",
        "create_smart_branches",
    },
    "app.services.practice.smart_orchestrator": {
        "SmartPracticeRequest",
        "run_smart_practice",
    },
}
SCOPE_IMPORTS = {
    "__future__": {"annotations"},
    "typing": {"Any"},
    "sqlalchemy": {"select"},
    "sqlalchemy.ext.asyncio": {"AsyncSession"},
    "app.models.practice_session": {"PracticeSession"},
}


def inspect_boundary(source, imports):
    assert len(source.splitlines()) <= 300
    tree = ast.parse(source, feature_version=(3, 11))
    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert functions
    assert max(node.end_lineno - node.lineno + 1 for node in functions) <= 50
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name in imports for alias in node.names)
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
            }
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def test_smart_branch_scope_modules_keep_budgets_and_expected_owners():
    assert {
        "_create_scored_branch",
        "_create_path_branch",
        "create_smart_branches",
    } <= (inspect_boundary(BRANCHES.read_text(), BRANCH_IMPORTS))
    assert {"run_smart_entry", "_run_smart_practice_request"} <= inspect_boundary(
        ENTRY.read_text(), ENTRY_IMPORTS
    )
    assert {
        "_scope_identity",
        "_resolved_scope_ids",
        "_served_scope_ids",
        "build_practice_session_scope",
        "public_practice_session_scope",
    } <= inspect_boundary(SCOPE.read_text(), SCOPE_IMPORTS)


def test_smart_branch_factories_do_not_eagerly_import_supplement_modules():
    tree = ast.parse(BRANCHES.read_text(), feature_version=(3, 11))
    eager = [
        alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    ]
    assert not any("supplement" in name for name in eager)


@pytest.mark.parametrize(
    "source,imports",
    [
        ("import httpx\ndef small():\n    pass\n", BRANCH_IMPORTS),
        (
            "from app.services.practice_service import logger\ndef small():\n    pass\n",
            ENTRY_IMPORTS,
        ),
        (
            "from app.models.question import Question\ndef small():\n    pass\n",
            SCOPE_IMPORTS,
        ),
        ("def small():\n    return open('payload').read()\n", BRANCH_IMPORTS),
        ("def small():\n    return __import__('socket')\n", SCOPE_IMPORTS),
        ("def outer():\n    def inner():\n" + "        pass\n" * 51, ENTRY_IMPORTS),
        ("async def small():\n" + "    pass\n" * 51, SCOPE_IMPORTS),
    ],
)
def test_smart_scope_boundary_rejects_injected_dependency_or_budget(source, imports):
    with pytest.raises(AssertionError):
        inspect_boundary(source, imports)
