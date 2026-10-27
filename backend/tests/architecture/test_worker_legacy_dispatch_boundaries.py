"""Guard legacy worker dispatch decomposition, branch order and lazy imports."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"
HANDLERS = "worker_legacy_handlers"
EXPECTED_DEPENDENCIES = {
    "app.core.database",
    "app.features",
    "app.features.batch_image_import_service",
    "app.features.pipeline_coordinator_entry",
    "app.features.pipeline_orchestrator",
    "app.features.question_import_writer",
    "app.models.formula",
    "app.services.formula_graph_batch_runner",
    "app.services.import_pipeline_service",
}
EXPECTED_BRANCHES = [
    ("TASK_TYPE_IMPORT_PIPELINE", "handle_import_pipeline"),
    ("TASK_TYPE_IMAGE_PIPELINE", "handle_image_pipeline"),
    ("TASK_TYPE_EXCEL_PIPELINE", "handle_excel_pipeline"),
    ("TASK_TYPE_RESUME_PIPELINE", "handle_resume_pipeline"),
    ("TASK_TYPE_ADMIN_RESUME", "handle_admin_resume"),
    ("TASK_TYPE_ANSWER_PROJECTION", "handle_answer_projection"),
    ("TASK_TYPE_ERROR_DIAGNOSIS", "handle_error_diagnosis"),
    ("TASK_TYPE_FORMULA_BATCH", "handle_formula_batch"),
    ("TASK_TYPE_BATCH_IMAGE", "handle_batch_image"),
]


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


def deferred_app_imports(tree):
    deferred = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            deferred.extend(
                child.module
                for child in ast.walk(node)
                if isinstance(child, ast.ImportFrom)
                and (child.module or "").startswith("app.")
            )
    return deferred


def assert_no_module_level_app_imports(tree):
    for node in tree.body:
        assert not isinstance(node, ast.Import)
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("app."), node.module


def test_handler_module_stays_bounded_and_reviewed():
    text = (APP / f"services/{HANDLERS}.py").read_text()
    assert len(text.splitlines()) <= 300
    check_tree(ast.parse(text, feature_version=(3, 11)))
    graph, _ = scan_application(APP)
    assert graph[f"app.services.{HANDLERS}"] == EXPECTED_DEPENDENCIES


def test_handler_module_only_imports_business_modules_lazily():
    tree = ast.parse((APP / f"services/{HANDLERS}.py").read_text())
    assert_no_module_level_app_imports(tree)
    assert set(deferred_app_imports(tree)) == {
        "app.core.database",
        "app.features",
        "app.features.pipeline_coordinator_entry",
        "app.features.pipeline_orchestrator",
        "app.models.formula",
        "app.services.formula_graph_batch_runner",
        "app.services.import_pipeline_service",
    }


def test_gate_rejects_eager_imports_and_oversized_functions():
    eager = ast.parse("from app.core.config import settings\n")
    with pytest.raises(AssertionError):
        assert_no_module_level_app_imports(eager)

    lines = ["async def handler():", "    value = 1"]
    lines.extend("    value += 1" for _ in range(50))
    oversized = ast.parse("\n".join(lines))
    with pytest.raises(AssertionError):
        check_tree(oversized)


def test_selector_preserves_branch_order_and_dynamic_ports():
    tree = ast.parse((APP / f"services/{HANDLERS}.py").read_text())
    selector = next(
        node
        for node in tree.body
        if getattr(node, "name", "") == "select_legacy_handler"
    )
    branches = []
    for node in selector.body:
        if isinstance(node, ast.If):
            test = node.test
            assert isinstance(test, ast.Compare)
            assert ast.unparse(test.left) == "task_type"
            assert len(test.comparators) == 1
            constant = test.comparators[0]
            assert isinstance(constant, ast.Subscript)
            assert ast.unparse(constant.value) == "namespace"
            assert isinstance(constant.slice, ast.Constant)
            assert isinstance(node.body[0], ast.Return)
            handler_name = ast.unparse(node.body[0].value)
            assert handler_name in {name for _, name in EXPECTED_BRANCHES}
            branches.append((constant.slice.value, handler_name))
        else:
            assert ast.unparse(node) == (
                "raise ValueError(f'unknown_task_type: {task_type}')"
            )
    assert branches == EXPECTED_BRANCHES


def test_worker_entry_delegates_and_keeps_cleanup_ownership():
    from app.services.task_queue_worker import _process_task as live_process_task
    from app.services.worker_legacy_handlers import LegacyTaskContext

    tree = ast.parse((APP / "services/task_queue_worker.py").read_text())
    entry = next(
        node for node in tree.body if getattr(node, "name", "") == "_process_task"
    )
    assert entry.end_lineno - entry.lineno + 1 <= 50
    assert not any(
        isinstance(node, ast.Compare)
        and any(
            isinstance(part, ast.Name) and part.id.startswith("TASK_TYPE_")
            for part in ast.walk(node)
        )
        for node in ast.walk(entry)
    )
    body = ast.unparse(entry)
    assert "handler = select_legacy_handler(task_type, globals())" in body
    assert "await handler(context)" in body
    assert "LegacyTaskContext(" in body
    assert "namespace=globals()" in body
    assert "for work_path in legacy_staging_work_copies:" in body
    assert "await async_cleanup_work_copy(work_path)" in body
    assert callable(live_process_task)
    assert LegacyTaskContext.__module__ == "app.services.worker_legacy_handlers"


def test_worker_module_no_longer_owns_handler_bodies():
    tree = ast.parse((APP / "services/task_queue_worker.py").read_text())
    defined = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert not {name for name in defined if name.startswith("handle_")}
    assert "_process_task" in defined


def test_fresh_import_does_not_initialize_business_or_orm_modules():
    probe = """
import os
import sys
before = dict(os.environ)
from app.services.worker_legacy_handlers import LegacyTaskContext, select_legacy_handler
assert callable(select_legacy_handler)
assert LegacyTaskContext.__module__ == "app.services.worker_legacy_handlers"
assert dict(os.environ) == before
for name in (
    'app.core.config', 'app.core.database', 'app.services.import_pipeline_service',
    'app.features.pipeline_orchestrator', 'app.features.pipeline_coordinator_entry',
    'app.features.batch_image_import_service', 'app.models.formula', 'sqlalchemy',
    'app.services.task_queue_worker',
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", probe],
        cwd=APP.parent,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
