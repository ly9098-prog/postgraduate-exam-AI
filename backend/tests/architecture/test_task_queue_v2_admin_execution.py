"""Keep administrative execution bounded and leave persistence in its owners."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
MODULE = APP / "services/task_queue_v2_admin_execution.py"
SERVICE = APP / "services/task_queue_service.py"


def check_module(tree):
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


def test_module_is_neutral_and_bounded():
    source = MODULE.read_text()
    assert len(source.splitlines()) <= 300
    check_module(ast.parse(source, feature_version=(3, 11)))


@pytest.mark.parametrize("operation", ["create_task", "from_url", "execute"])
def test_gate_rejects_client_task_and_database_ownership(operation):
    tree = ast.parse(MODULE.read_text())
    function = next(
        node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
    )
    function.body.append(ast.parse(f"owner.{operation}()").body[0])
    with pytest.raises(AssertionError):
        check_module(tree)


@pytest.mark.parametrize(
    "entry_name,target_name,arguments",
    [
        (
            "mark_corrupt_v2",
            "execute_v2_mark_corrupt",
            ["self", "task_id", "task_type", "error_summary"],
        ),
        ("cancel_v2", "execute_v2_cancel", ["self", "task_id", "task_type", "reason"]),
        ("_reclaim_expired_v2", "execute_v2_reclaim", ["self", "task_type"]),
    ],
)
def test_service_retains_disabled_gate_error_handler_and_live_ports(
    entry_name, target_name, arguments
):
    from app.services import task_queue_service as service
    from app.services import task_queue_v2_admin_execution as execution

    assert getattr(service, target_name) is getattr(execution, target_name)
    tree = ast.parse(SERVICE.read_text())
    queue = next(
        node for node in tree.body if getattr(node, "name", "") == "DurableTaskQueue"
    )
    entry = next(node for node in queue.body if getattr(node, "name", "") == entry_name)
    assert entry.end_lineno - entry.lineno + 1 <= 50
    gate = entry.body[1]
    assert isinstance(gate, ast.If)
    assert ast.unparse(gate.test) == "not self._redis_enabled"
    protected = entry.body[-1]
    assert isinstance(protected, ast.Try) and len(protected.handlers) == 1
    assert ast.unparse(protected.handlers[0].type) == "Exception"
    assert len(protected.body) == 1
    call = protected.body[0].value.value
    assert ast.unparse(call.func) == target_name
    assert [ast.unparse(arg) for arg in call.args] == arguments
    assert {kw.arg: ast.unparse(kw.value) for kw in call.keywords} == {
        "namespace": "globals()"
    }


def test_module_import_does_not_load_queue_or_runtime():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError("admin execution import must not create tasks")
asyncio.create_task = forbidden
from app.services.task_queue_v2_admin_execution import execute_v2_cancel
assert callable(execute_v2_cancel)
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
