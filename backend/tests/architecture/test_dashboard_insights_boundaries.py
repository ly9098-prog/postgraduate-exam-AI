"""Keep scoring modules independent and preserve insights orchestration ownership."""

import ast
from pathlib import Path

import pytest

SERVICES = Path(__file__).resolve().parents[2] / "app" / "services"
PROJECTIONS = ["quality", "topic", "speed", "balance", "action"]


def projection_violations(source):
    tree = ast.parse(source)
    violations = []
    if len(source.splitlines()) > 300:
        violations.append("module budget")
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.end_lineno - node.lineno + 1 > 50:
                violations.append("function budget")
        if isinstance(node, (ast.AsyncFunctionDef, ast.Await)):
            violations.append("async dependency")
        if isinstance(node, ast.Import):
            if any(n.name not in {"math", "datetime"} for n in node.names):
                violations.append("import dependency")
        if isinstance(node, ast.ImportFrom) and node.module not in {
            "datetime",
            "typing",
        }:
            violations.append("import dependency")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in {"__import__", "eval", "exec", "open"}:
                violations.append("runtime dependency")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {
                "execute",
                "commit",
                "flush",
                "rollback",
                "add",
                "add_all",
                "delete",
                "refresh",
                "connection",
            }:
                violations.append("database operation")
    return violations


@pytest.mark.parametrize("name", PROJECTIONS)
def test_pure_module_budget_and_dependencies(name):
    assert (
        projection_violations(
            (SERVICES / f"dashboard_{name}_projection.py").read_text()
        )
        == []
    )


@pytest.mark.parametrize(
    "source",
    [
        "from sqlalchemy import select\n",
        "from app.core.cache import cache\n",
        "import os\n",
        "async def f():\n    return 1\n",
        "def f():\n" + "    x = 1\n" * 50,
        "x = 1\n" * 301,
        "x = __import__('sqlalchemy')\n",
        "def injected(db):\n    db.execute('select 1')\n",
        "def injected(db):\n    db.commit()\n",
        "def injected(db):\n    db.flush()\n",
        "def injected(db):\n    db.rollback()\n",
        "def injected(db):\n    db.add(object())\n",
    ],
)
def test_dependency_and_budget_gate_rejects_regressions(source):
    assert projection_violations(source)


def test_service_keeps_query_cache_and_aggregation_ownership():
    source = (SERVICES / "dashboard_insights_service.py").read_text()
    tree = ast.parse(source)
    functions = {n.name: n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)}
    expected = {
        "compute_today_quality": "quality.today_quality",
        "compute_weekly_consistency": "quality.weekly_consistency",
        "compute_weak_topic_ranking": "topics.weak_topic_items",
        "compute_repeat_wrong_analysis": "topics.repeat_wrong_analysis",
        "compute_speed_accuracy": "speed.speed_accuracy",
        "compute_new_vs_review": "balance.new_vs_review",
        "compute_input_output": "balance.input_output",
        "compute_action_plan": "actions.action_plan",
    }
    for name, call in expected.items():
        body = ast.unparse(functions[name])
        assert call in body
        if name != "compute_action_plan":
            assert "await db.execute(" in body
    aggregate = ast.unparse(functions["get_dashboard_insights"])
    for fragment in (
        "await cache.get(",
        "return_exceptions=True",
        "await get_overview(",
        "ttl=120",
    ):
        assert fragment in aggregate
    assert "isinstance(val, Exception)" in aggregate
    assert "except Exception:" in aggregate
