"""Pin service-owned ports across the scored selection and completion boundary."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"


def test_scored_policy_is_neutral_and_bounded():
    graph, _ = scan_application(APP)
    assert graph["app.services.practice.scored_policy"] == {
        "app.models.question", "app.services.practice.scored_context",
    }
    assert "app.services.practice.scored_policy" in graph["app.services.practice_service"]
    source = (APP / "services/practice/scored_policy.py").read_text()
    assert len(source.splitlines()) <= 150
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50
        assert not isinstance(node, (ast.Try, ast.Await))
        if isinstance(node, ast.Call):
            assert getattr(node.func, "attr", "") not in {
                "execute", "commit", "rollback", "begin", "begin_nested", "flush",
            }


def test_entry_binds_real_policy_ports_and_awaits_service_owned_completion():
    from app.services import practice_service as svc
    from app.services.practice import scored_policy

    assert svc.rank_and_select_candidates is scored_policy.rank_and_select_candidates
    assert svc.ScoredPolicyRequest is scored_policy.ScoredPolicyRequest
    source = (APP / "services/practice_service.py").read_text()
    tree = ast.parse(source)
    entry = next(
        node for node in tree.body if getattr(node, "name", "") == "get_smart_scored_questions"
    )
    calls = [node for node in ast.walk(entry) if isinstance(node, ast.Call)]
    request = next(node for node in calls if ast.unparse(node.func) == "ScoredPolicyRequest")
    assert {kw.arg: ast.unparse(kw.value) for kw in request.keywords} == {
        "candidates": "candidates",
        "learning": "learning",
        "runtime": "scored_runtime",
        "graph_config": "graph_runtime",
        "now": "now",
        "count": "count",
        "user_id": "user_id",
        "metadata": "metadata",
        "logger": "logger",
        "rank_candidates": "score_and_rank_candidates",
        "select_candidates": "select_scored_candidates",
        "calculate_score": "calculate_smart_score",
        "build_metadata": "_build_scored_metadata",
    }
    policy = [node for node in calls if ast.unparse(node.func) == "rank_and_select_candidates"]
    assert len(policy) == 1 and policy[0].args == [request]
    returned = entry.body[-1]
    assert isinstance(returned, ast.Return) and isinstance(returned.value, ast.Await)
    completion = returned.value.value
    assert ast.unparse(completion.func) == "_complete_scored_selection"
    assert [ast.unparse(arg) for arg in completion.args] == [
        "db", "user_id", "subject_code", "count", "candidate_context",
        "cand_ids", "selection", "metadata",
    ]


def test_entry_snapshots_expanded_candidate_ids_before_policy_and_keeps_budgets():
    source = (APP / "services/practice_service.py").read_text()
    functions = {
        node.name: node for node in ast.parse(source).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    entry = functions["get_smart_scored_questions"]
    text = ast.unparse(entry)
    assert text.index("await load_scored_learning_context(") < text.index("cand_ids = ")
    assert text.index("cand_ids = ") < text.index("selection = rank_and_select_candidates(")
    for name, budget in (("get_smart_scored_questions", 80), ("_complete_scored_selection", 50)):
        assert functions[name].end_lineno - functions[name].lineno + 1 <= budget


def test_policy_import_has_no_runtime_or_resource_side_effects():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError("policy import must not create tasks")
asyncio.create_task = forbidden
from app.services.practice.scored_policy import rank_and_select_candidates
assert callable(rank_and_select_candidates)
assert dict(os.environ) == before
for name in (
    'app.main', 'app.core.config', 'app.core.database', 'app.models.question',
    'app.services.practice_service', 'app.services.practice.scored_context', 'sqlalchemy',
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
