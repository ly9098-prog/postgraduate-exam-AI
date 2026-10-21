"""Fallback flow consumes ports and preserves level/query/merge ownership."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"


def test_flow_dependencies_budgets_and_no_persistence_calls():
    graph, _ = scan_application(APP)
    assert graph["app.services.practice.scored_fallback_flow"] == {"app.models.question"}
    assert "app.services.practice.scored_fallback_flow" in graph["app.services.practice_service"]
    source = (APP / "services/practice/scored_fallback_flow.py").read_text()
    tree = ast.parse(source)
    assert len(source.splitlines()) <= 150
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50
        if isinstance(node, ast.Call):
            assert _call_name(node.func) not in {
                "execute", "commit", "rollback", "begin", "begin_nested",
                "scalar", "scalars", "flush",
            }


def test_real_entry_passes_policy_ports_to_the_flow_without_inline_fallback():
    from app.services import practice_service as svc
    from app.services.practice import scored_fallback_flow

    source = (APP / "services/practice_service.py").read_text()
    entry = next(
        node for node in ast.parse(source).body
        if getattr(node, "name", "") == "get_smart_scored_questions"
    )
    assert _fallback_request(entry) == {
        "db": "db",
        "selected": "selected",
        "selected_ids": "selected_ids",
        "metadata": "metadata",
        "count": "count",
        "fallback_level": "fallback_level",
        "base_conditions": "[Question.is_active]",
        "subject_condition": "subject_cond",
        "candidate_ids": "cand_ids",
        "excluded_subquery": "excluded_sub",
        "scope_ids": "scope_ids",
        "revision_condition": "_practice_revision_scope_condition",
        "random_fill": "load_random_fill_questions",
        "repeat_fill": "load_repeat_fill_questions",
        "sample_query": "_random_sample_query",
        "merge_fill": "merge_fill_questions",
        "metadata_factory": "_build_fallback_metadata",
    }
    assert svc.run_scored_fallback is scored_fallback_flow.run_scored_fallback
    assert not any(isinstance(node, ast.For) for node in entry.body)
    assert not any(isinstance(node, ast.If) and "len(selected) < count" in ast.unparse(node)
                   for node in entry.body)
    flow_source = (APP / "services/practice/scored_fallback_flow.py").read_text()
    flow = next(
        node for node in ast.parse(flow_source).body
        if getattr(node, "name", "") == "run_scored_fallback"
    )
    checks = [
        ast.unparse(node.test) for node in flow.body
        if isinstance(node, ast.If)
    ]
    assert checks == [
        "len(request.selected) < request.count",
        "len(request.selected) < request.count",
    ]
    _assert_fallback_conditions(flow_source)


def test_import_does_not_load_models_database_configuration_or_create_tasks():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError("flow import must not create tasks")
asyncio.create_task = forbidden
from app.services.practice.scored_fallback_flow import run_scored_fallback
assert callable(run_scored_fallback)
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


def _call_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _fallback_request(entry):
    calls = [
        node for node in ast.walk(entry)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "ScoredFallbackRequest"
    ]
    assert len(calls) == 1 and calls[0].func.id == "ScoredFallbackRequest"
    return {keyword.arg: ast.unparse(keyword.value) for keyword in calls[0].keywords}


def _assert_fallback_conditions(source):
    helpers = {
        node.name: node for node in ast.parse(source).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    random_source = ast.unparse(helpers["_run_random_fallback"])
    repeat_source = ast.unparse(helpers["_run_repeat_fallback"])
    expected = [
        "*request.base_conditions", "request.subject_condition",
        "request.revision_condition(request.scope_ids)",
        "Question.id.notin_(request.candidate_ids | request.selected_ids)",
    ]
    assert _condition_list(random_source) == expected
    assert "conditions.append(Question.id.notin_(request.excluded_subquery))" in random_source
    assert _condition_list(repeat_source) == [
        "*request.base_conditions", "request.subject_condition",
        "request.revision_condition(request.scope_ids)",
        "Question.id.notin_(request.selected_ids)",
    ]


def _condition_list(source):
    tree = ast.parse(source)
    node = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and getattr(node.targets[0], "id", "") == "conditions"
    )
    return [ast.unparse(item) for item in node.value.elts]
