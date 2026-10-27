"""Bound the heartbeat adapter and keep Lua, clients and runtime in their owners."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
MODULE = APP / "services/task_queue_v2_heartbeat_execution.py"
SERVICE = APP / "services/task_queue_service.py"


def check_execution_module(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50, node.name
        if isinstance(node, ast.ImportFrom):
            assert node.module in {"__future__", "typing"}
        assert not isinstance(node, (ast.Import, ast.Delete))
        if isinstance(node, ast.Call):
            assert getattr(node.func, "attr", "") not in {
                "create_task",
                "ensure_future",
                "from_url",
                "connect",
                "execute",
                "commit",
                "rollback",
                "flush",
                "evalsha",
                "script_load",
            }


def test_execution_module_is_neutral_and_bounded():
    source = MODULE.read_text()
    assert len(source.splitlines()) <= 300
    tree = ast.parse(source, feature_version=(3, 11))
    check_execution_module(tree)
    assert all(
        isinstance(
            node, (ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.Expr)
        )
        for node in tree.body
    )


@pytest.mark.parametrize("operation", ["create_task", "from_url", "execute"])
def test_gate_rejects_new_task_client_and_database_ownership(operation):
    tree = ast.parse(MODULE.read_text())
    function = next(
        node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
    )
    function.body.append(ast.parse(f"owner.{operation}()").body[0])
    with pytest.raises(AssertionError):
        check_execution_module(tree)


def test_service_binds_identity_snapshot_and_live_namespace():
    from app.services import task_queue_service as service
    from app.services import task_queue_v2_heartbeat_execution as execution

    assert service.execute_v2_heartbeat is execution.execute_v2_heartbeat
    tree = ast.parse(SERVICE.read_text())
    queue = next(
        node for node in tree.body if getattr(node, "name", "") == "DurableTaskQueue"
    )
    entry = next(
        node for node in queue.body if getattr(node, "name", "") == "heartbeat_v2"
    )
    assert entry.end_lineno - entry.lineno + 1 <= 50
    assert [arg.arg for arg in entry.args.args] == ["self", "task_or_id"]
    assert [arg.arg for arg in entry.args.kwonlyargs] == ["task_type", "lease_sec"]
    assert [ast.unparse(value) for value in entry.args.kw_defaults] == [
        "None",
        "_DEFAULT_LEASE_SEC",
    ]
    returned = entry.body[-1]
    assert isinstance(returned.value, ast.Await)
    call = returned.value.value
    assert ast.unparse(call.func) == "execute_v2_heartbeat"
    assert [ast.unparse(arg) for arg in call.args] == ["self", "task_or_id"]
    assert {kw.arg: ast.unparse(kw.value) for kw in call.keywords} == {
        "task_id": "task_id",
        "task_type": "task_type",
        "owner_token": "token",
        "lease_sec": "lease_sec",
        "namespace": "globals()",
    }


def test_execution_import_does_not_load_queue_or_runtime():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError("heartbeat import must not create tasks")
asyncio.create_task = forbidden
from app.services.task_queue_v2_heartbeat_execution import execute_v2_heartbeat
assert callable(execute_v2_heartbeat)
assert dict(os.environ) == before
for name in (
    'app.core.config', 'app.core.database', 'app.services.task_queue_service',
    'app.services.task_queue_contract', 'redis', 'sqlalchemy',
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
