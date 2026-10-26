"""Keep completed-stage cleanup separate from pipeline IO and transactions."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
MODULE = APP / "features/pipeline_stage_completion.py"
ALLOWED = {
    "__future__": {"annotations"},
    "collections.abc": {"Callable"},
    "typing": {"Any"},
    "app.evaluation.split_quality": {"evaluate_split_quality"},
    "app.evaluation.routing_metrics": {"build_routing_metrics"},
}


def assert_boundary(source):
    assert len(source.splitlines()) <= 300
    tree = ast.parse(source)
    functions = [
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert functions
    assert all(n.end_lineno - n.lineno + 1 <= 50 for n in functions)
    for node in ast.walk(tree):
        assert not isinstance(node, (ast.Import, ast.AsyncFunctionDef, ast.Await))
        if isinstance(node, ast.ImportFrom):
            assert not node.level and node.module in ALLOWED
            assert {alias.name for alias in node.names} <= ALLOWED[node.module]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"open", "exec", "eval", "__import__"}
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {
                "commit",
                "rollback",
                "execute",
                "flush",
                "begin",
            }


def test_completion_module_budget_import_and_transaction_boundaries():
    assert_boundary(MODULE.read_text())


def test_single_pass_uses_completion_owner_once_without_duplicate_observers():
    source = (APP / "features/pipeline_orchestrator.py").read_text()
    tree = ast.parse(source)
    method = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_run_single_pass"
    )
    calls = [
        n
        for n in ast.walk(method)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "complete_stage_data"
    ]
    assert len(calls) == 1
    assert "split_quality evaluation failed: %s" not in source
    assert "routing_metrics build failed: %s" not in source


@pytest.mark.parametrize(
    "source",
    [
        "def small(): pass\n" + "\n" * 300,
        "def outer():\n    def nested():\n" + "        pass\n" * 51,
        "def small(): pass\nfrom app.core.config import settings\n",
        "def small(): pass\nimport app.features.pipeline_orchestrator\n",
        "async def small(): pass\n",
        "def small():\n    open('forbidden')\n",
        "def small():\n    db.commit()\n",
    ],
)
def test_completion_boundary_rejects_injected_violations(source):
    with pytest.raises(AssertionError):
        assert_boundary(source)


def test_completion_import_does_not_initialize_orchestrator_or_observers():
    probe = """
import sys
from app.features.pipeline_stage_completion import complete_stage_data
assert callable(complete_stage_data)
for name in (
    "app.features.pipeline_orchestrator", "app.evaluation.split_quality",
    "app.evaluation.routing_metrics", "app.core.config", "app.core.database",
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=APP.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
