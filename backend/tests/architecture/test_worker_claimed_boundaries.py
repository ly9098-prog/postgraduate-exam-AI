"""Keep claimed execution bounded and its runtime ownership explicit."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"
DEPENDENCIES = {
    "worker_claimed_state": set(),
    "worker_claimed_cleanup": {"app.services.worker_claimed_state"},
    "worker_claimed_outcome": {"app.services.worker_claimed_state"},
    "worker_claimed_execution": {
        "app.services.worker_claimed_state",
        "app.services.worker_claimed_cleanup",
        "app.services.worker_claimed_outcome",
    },
}


def check_tree(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50, node.name
        if isinstance(node, ast.Call):
            assert getattr(node.func, "attr", "") not in {
                "connect",
                "from_url",
                "ensure_future",
                "unlink",
                "remove",
                "rmtree",
            }
        assert not isinstance(node, ast.Delete)


def test_modules_have_only_neutral_dependencies_and_bounded_functions():
    graph, _ = scan_application(APP)
    for name, expected in DEPENDENCIES.items():
        text = (APP / f"services/{name}.py").read_text()
        assert len(text.splitlines()) <= 300
        check_tree(ast.parse(text, feature_version=(3, 11)))
        assert graph[f"app.services.{name}"] == expected


@pytest.mark.parametrize("operation", ["connect", "unlink", "ensure_future"])
def test_gate_rejects_extra_resource_ownership(operation):
    tree = ast.parse((APP / "services/worker_claimed_execution.py").read_text())
    function = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef))
    function.body.append(ast.parse(f"owner.{operation}()").body[0])
    with pytest.raises(AssertionError):
        check_tree(tree)


def test_gate_rejects_state_deletion():
    tree = ast.parse("del state.task")
    with pytest.raises(AssertionError):
        check_tree(tree)


def test_entry_captures_context_helpers_before_live_worker_delegation():
    from app.services import task_queue_worker as worker
    from app.services.worker_claimed_execution import run_claimed_task

    assert worker.run_claimed_task is run_claimed_task
    tree = ast.parse((APP / "services/task_queue_worker.py").read_text())
    entry = next(
        n for n in tree.body if getattr(n, "name", "") == "_process_claimed_task_v2"
    )
    assert entry.end_lineno - entry.lineno + 1 <= 50
    assert [arg.arg for arg in entry.args.args] == ["task", "lease_sec", "sem"]
    assert ast.unparse(entry.returns) == "None"
    assert entry.body[1].module == "app.core.log_context"
    assert [alias.name for alias in entry.body[1].names] == [
        "bind_log_context",
        "generate_request_id",
        "generate_trace_id",
        "reset_log_context",
    ]
    call = entry.body[-1].value.value
    assert ast.unparse(call.func) == "run_claimed_task"
    assert [ast.unparse(arg) for arg in call.args] == ["task", "lease_sec", "sem"]
    assert {kw.arg: ast.unparse(kw.value) for kw in call.keywords} == {
        "namespace": "globals()",
        "bind_context": "bind_log_context",
        "generate_request_id": "generate_request_id",
        "generate_trace_id": "generate_trace_id",
        "reset_context": "reset_log_context",
    }


def test_three_children_are_created_in_original_order_and_registered():
    tree = ast.parse((APP / "services/worker_claimed_execution.py").read_text())
    function = next(
        n for n in tree.body if getattr(n, "name", "") == "start_claimed_children"
    )
    spawns = [
        n
        for n in function.body
        if isinstance(n, ast.Assign)
        and isinstance(n.value, ast.Call)
        and ast.unparse(n.value.func) == "spawn_claimed_child"
    ]
    assert [ast.unparse(n.targets[0]) for n in spawns] == [
        "state.heartbeat_task",
        "state.process_task",
        "state.cancel_watcher",
    ]
    assert [ast.unparse(n.value.args[1].func) for n in spawns] == [
        "ports['_v2_heartbeat_loop_with_lease_window']",
        "ports['_process_task_v2']",
        "ports['_cancel_on_owner_loss']",
    ]
    for node in spawns:
        assert ast.unparse(node.value.args[0]) == "ports['asyncio'].create_task"
    assert ast.unparse(function.body[-1]) == "state.children_ready = True"
    assert (
        sum(
            isinstance(n, ast.Attribute) and n.attr == "create_task"
            for name in DEPENDENCIES
            for n in ast.walk(ast.parse((APP / f"services/{name}.py").read_text()))
        )
        == 3
    )


def test_fresh_import_does_not_load_configuration_orm_or_start_runtime():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError("claimed execution import must not create tasks")
asyncio.create_task = forbidden
from app.services.worker_claimed_execution import run_claimed_task
assert callable(run_claimed_task)
assert dict(os.environ) == before
for name in (
    'app.core.config', 'app.core.database', 'app.services.task_queue_worker',
    'app.services.task_queue_service', 'app.features.pipeline_orchestrator',
    'sqlalchemy',
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", probe],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
