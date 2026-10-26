"""Ranked scoring consumes caller state without owning IO or explanations."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"


def test_ranking_dependencies_and_budgets():
    graph, _ = scan_application(APP)
    assert graph["app.services.practice.scored_ranking"] == {"app.models.question"}
    assert "app.services.practice.scored_ranking" in graph["app.services.practice_service"]
    source = (APP / "services/practice/scored_ranking.py").read_text()
    assert len(source.splitlines()) <= 100
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50
        if isinstance(node, ast.Call):
            assert getattr(node.func, "attr", "") not in {"execute", "commit", "rollback"}


def test_scored_entry_uses_real_ranker_and_keeps_debug_and_explanation_ownership():
    from app.services import practice_service as svc
    from app.services.practice import scored_ranking

    source = (APP / "services/practice_service.py").read_text()
    entry = next(
        node for node in ast.parse(source).body
        if getattr(node, "name", "") == "get_smart_scored_questions"
    )
    policy_source = (APP / "services/practice/scored_policy.py").read_text()
    policy_tree = ast.parse(policy_source)
    policy = next(
        node for node in policy_tree.body
        if getattr(node, "name", "") == "rank_and_select_candidates"
    )
    calls = [node for node in ast.walk(policy) if isinstance(node, ast.Call)]
    ranking = [node for node in calls if ast.unparse(node.func) == "request.rank_candidates"]
    assert svc.score_and_rank_candidates is scored_ranking.score_and_rank_candidates
    assert len(ranking) == 1
    assert [ast.unparse(arg) for arg in ranking[0].args] == [
        "request.candidates", "learning.q_state_map", "learning.q_kp_map",
        "learning.kp_mastery", "learning.recent_kp_ids", "request.now",
    ]
    keywords = {keyword.arg: ast.unparse(keyword.value) for keyword in ranking[0].keywords}
    assert keywords == {
        "kp_observations": "learning.kp_observations",
        "blocked_kps": "learning.blocked_kps",
        "graph_candidates": "learning.graph_candidates",
        "prerequisites_by_target": "learning.prerequisites_by_target",
        "weights": "learning.rec_weights",
        "graph_config": "request.graph_config",
        "calculate_score": "request.calculate_score",
    }
    assert not any(isinstance(node, ast.For) for node in entry.body)
    assert not any(isinstance(node, ast.Call) and getattr(node.func, "id", "") == "calculate_smart_score" for node in calls)
    assert not any(
        isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_build_fallback_metadata"
        for node in calls
    )
    assert "_complete_scored_selection" in ast.unparse(entry)
    assert any(isinstance(node, ast.If) and "top5" in ast.unparse(node)
               for node in policy.body)
    projection = next(
        node for node in ast.walk(policy_tree)
        if getattr(node, "name", "") == "scored_metadata"
    )
    assert "request.build_metadata" in ast.unparse(projection)
    assert "request.runtime.get('strategy_config_id')" in ast.unparse(projection)


def test_import_does_not_load_models_database_configuration_or_create_tasks():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError("ranking import must not create tasks")
asyncio.create_task = forbidden
from app.services.practice.scored_ranking import score_and_rank_candidates
assert callable(score_and_rank_candidates)
assert dict(os.environ) == before
for name in (
    'app.main', 'app.core.config', 'app.core.database', 'app.models.question',
    'app.services.practice_service', 'sqlalchemy',
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
