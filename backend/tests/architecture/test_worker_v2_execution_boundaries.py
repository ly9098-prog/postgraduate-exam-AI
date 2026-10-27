"""Guard handler decomposition, ordered entry binding and late runtime imports."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"
DEPENDENCIES = {
    "worker_v2_state": set(),
    "worker_v2_execution": {
        "app.services.worker_v2_state",
        "app.services.worker_v2_dispatch",
        "app.core.database",
        "app.services.db_fencing",
    },
    "worker_v2_dispatch": {
        "app.services.worker_v2_state",
        "app.services.worker_v2_aux_handlers",
        "app.services.worker_v2_pipeline_handlers",
    },
    "worker_v2_pipeline_handlers": {
        "app.services.worker_v2_state",
        "app.services.import_pipeline_service",
        "app.features.pipeline_orchestrator",
        "app.features",
        "app.features.question_import_writer",
        "app.core.database",
        "app.features.pipeline_coordinator_entry",
    },
    "worker_v2_aux_handlers": {
        "app.services.worker_v2_state",
        "app.core.database",
        "app.models.formula",
        "app.services.formula_graph_batch_runner",
        "app.features",
        "app.features.batch_image_import_service",
    },
}


def check_tree(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50, node.name
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("app.api")
        if isinstance(node, ast.Call):
            assert getattr(node.func, "attr", "") not in {
                "create_task",
                "ensure_future",
                "connect",
                "from_url",
                "unlink",
                "remove",
                "rmtree",
            }
        assert not isinstance(node, ast.Delete)


def test_modules_have_explicit_dependencies_and_bounded_responsibilities():
    graph, _ = scan_application(APP)
    for name, expected in DEPENDENCIES.items():
        text = (APP / f"services/{name}.py").read_text()
        assert len(text.splitlines()) <= 300
        check_tree(ast.parse(text, feature_version=(3, 11)))
        assert graph[f"app.services.{name}"] == expected


@pytest.mark.parametrize("operation", ["create_task", "connect", "unlink"])
def test_gate_rejects_background_resource_or_deletion_ownership(operation):
    tree = ast.parse((APP / "services/worker_v2_execution.py").read_text())
    function = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef))
    function.body.append(ast.parse(f"owner.{operation}()").body[0])
    with pytest.raises(AssertionError):
        check_tree(tree)


def test_worker_entry_keeps_context_import_before_live_delegation():
    from app.services import task_queue_worker as worker
    from app.services.worker_v2_execution import run_v2_task

    assert worker.run_v2_task is run_v2_task
    tree = ast.parse((APP / "services/task_queue_worker.py").read_text())
    entry = next(n for n in tree.body if getattr(n, "name", "") == "_process_task_v2")
    assert entry.end_lineno - entry.lineno + 1 <= 50
    assert [arg.arg for arg in entry.args.args] == ["task"]
    assert ast.unparse(entry.returns) == "None"
    assert entry.body[1].module == "app.features.pipeline_checkpoint"
    assert [alias.name for alias in entry.body[1].names] == [
        "clear_fencing_context",
        "set_fencing_context",
    ]
    call = entry.body[-1].value.value
    assert ast.unparse(call.func) == "run_v2_task"
    assert [ast.unparse(arg) for arg in call.args] == ["task"]
    assert {kw.arg: ast.unparse(kw.value) for kw in call.keywords} == {
        "namespace": "globals()",
        "set_context": "set_fencing_context",
        "clear_context": "clear_fencing_context",
    }


def test_staging_resolution_still_binds_owner_and_generation_before_tracking():
    tree = ast.parse((APP / "services/worker_v2_state.py").read_text())
    state = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    method = next(
        n for n in state.body if getattr(n, "name", "") == "resolve_owned_staging"
    )
    call = method.body[1].value.value
    assert ast.unparse(call.func) == "self.namespace['_resolve_staging_path']"
    assert [ast.unparse(arg) for arg in call.args] == [
        "staging_id",
        "self.task.owner_token",
        "self.task.generation",
    ]
    assert ast.unparse(method.body[2]) == "self.staging_work_copies.append(work_path)"


def test_fresh_import_does_not_initialize_worker_database_or_providers():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError("v2 execution import must not create tasks")
asyncio.create_task = forbidden
from app.services.worker_v2_execution import run_v2_task
assert callable(run_v2_task)
assert dict(os.environ) == before
for name in (
    'app.core.config', 'app.core.database', 'app.services.task_queue_worker',
    'app.services.import_pipeline_service', 'app.features.pipeline_orchestrator',
    'app.models.formula', 'sqlalchemy',
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
