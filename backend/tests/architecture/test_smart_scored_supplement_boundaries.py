"""Smart scored supplement keeps provider, query and finalizer ownership."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"
MODULE = "app.services.practice.smart_scored_supplement"


def _call_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _entry():
    source = (APP / "services/practice_service.py").read_text()
    return next(
        node
        for node in ast.parse(source).body
        if getattr(node, "name", "") == "get_smart_practice_questions"
    )


def _smart_entry():
    source = (APP / "services/practice/smart_entry.py").read_text()
    return next(
        node
        for node in ast.parse(source).body
        if getattr(node, "name", "") == "run_smart_entry"
    )


def test_module_has_no_application_io_dependencies_or_persistence_calls():
    graph, _ = scan_application(APP)
    assert graph[MODULE] == set()
    source = (APP / "services/practice/smart_scored_supplement.py").read_text()
    tree = ast.parse(source)
    assert len(source.splitlines()) <= 150
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50
        if isinstance(node, ast.Call):
            assert _call_name(node.func) not in {
                "execute",
                "scalar",
                "scalars",
                "commit",
                "rollback",
                "begin",
                "begin_nested",
                "flush",
                "add",
            }
    assert not any(isinstance(node, ast.For) for node in ast.walk(tree))


def test_real_entry_consumes_exact_ports_and_keeps_scored_provider():
    from app.services import practice_service as svc
    from app.services.practice import smart_scored_supplement
    from app.services.practice import smart_entry as entry_module

    entry = _entry()
    smart_entry = _smart_entry()
    branch_source = (APP / "services/practice/smart_branches.py").read_text(
        encoding="utf-8"
    )
    branch_tree = ast.parse(branch_source)
    requests = [
        node
        for node in ast.walk(smart_entry)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "create_smart_branches"
    ]
    assert len(requests) == 1
    scored_requests = [
        node
        for node in ast.walk(branch_tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "ScoredSupplementRequest"
    ]
    assert len(scored_requests) == 1
    provider_fields = {
        keyword.arg: ast.unparse(keyword.value)
        for keyword in requests[0].args[1].keywords
    }
    assert provider_fields == {
        "load_scored": "request.load_scored",
        "load_fallback": "request.load_fallback",
        "merge_results": "request.merge_results",
        "finalize_scored": "request.finalize",
        "finalize_path": "request.finalize",
        "build_path_conditions": "request.build_conditions",
        "load_path": "request.load_path",
        "run_weakness": "request.run_weakness",
    }
    assert {
        keyword.arg: ast.unparse(keyword.value)
        for keyword in scored_requests[0].keywords
    } == {
        "db": "request.db",
        "user_id": "request.user_id",
        "subject_code": "request.subject_code",
        "count": "request.count",
        "exclude_answered": "request.exclude_answered",
        "no_repeat_days": "request.no_repeat_days",
        "use_leitner": "request.use_leitner",
        "request_id": "request.request_id",
        "scope_ids": "branch_scope_ids",
        "skip_finalize": "request.skip_finalize",
        "experiment_id": "experiment_info.get('experiment_id')",
        "variant_key": "experiment_info.get('variant_key')",
        "logger": "_branch_logger()",
        "load_scored": "providers.load_scored",
        "load_fallback": "providers.load_fallback",
        "merge_results": "providers.merge_results",
        "finalize": "providers.finalize_scored",
    }
    assert svc.run_scored_supplement is smart_scored_supplement.run_scored_supplement
    entry_text = ast.unparse(entry)
    assert "get_smart_scored_questions" in entry_text
    assert "_smart_weakness_vector" in entry_text
    assert "create_smart_branches" not in entry_text
    assert entry_module.create_smart_branches is not None
    assert entry_module.run_smart_practice is not None
    assert not any(
        isinstance(node, ast.Try) and "get_smart_scored_questions" in ast.unparse(node)
        for node in ast.walk(branch_tree)
    )
    branch_text = ast.unparse(branch_tree)
    assert "get_smart_scored_questions" not in branch_text
    assert "_smart_weakness_vector" not in branch_text


def test_flow_preserves_completion_and_shortfall_order():
    source = (APP / "services/practice/smart_scored_supplement.py").read_text()
    tree = ast.parse(source)
    flow = next(
        node
        for node in tree.body
        if getattr(node, "name", "") == "run_scored_supplement"
    )
    assert [
        ast.unparse(node.test) for node in ast.walk(flow) if isinstance(node, ast.If)
    ] == ["len(scored) >= request.count"]
    text = ast.unparse(flow)
    assert "request.count - len(scored)" in text
    assert "exclude_ids={question.id for question in scored}" in text
    assert "merged[:request.count]" in text
    assert text.index("request.load_scored") < text.index("request.load_fallback")
    assert text.index("request.load_fallback") < text.index("request.merge_results")
    assert text.index("request.merge_results") < text.rindex("await _finalize(")


def test_import_does_not_load_application_config_resources_or_create_tasks():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError("smart supplement import must stay inert")
asyncio.create_task = forbidden
from app.services.practice.smart_scored_supplement import (
    ScoredSupplementRequest,
    run_scored_supplement,
)
assert callable(run_scored_supplement)
assert ScoredSupplementRequest.__module__.endswith("smart_scored_supplement")
assert dict(os.environ) == before
for name in (
    'app.main', 'app.core.config', 'app.core.database', 'app.models.question',
    'app.services.practice_service', 'sqlalchemy', 'fastapi',
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
