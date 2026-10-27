"""Keep visual cropping dependencies, late imports and module budgets explicit."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"
MODULES = {
    "pipeline_visual_crop": {
        "app.features.pipeline_visual_crop_regions",
        "app.features.pipeline_visual_crop_snapshot",
        "app.features.pipeline_visual_crop_state",
        "app.services.storage_backend",
        "app.services.visual_region_cropper",
        "app.services.visual_region_types",
    },
    "pipeline_visual_crop_regions": {
        "app.features.pipeline_visual_crop_state",
        "app.services.visual_region_types",
    },
    "pipeline_visual_crop_snapshot": {
        "app.features.pipeline_visual_crop_state",
        "app.core.executor_registry",
        "app.services.visual_region_cropper",
    },
    "pipeline_visual_crop_state": set(),
}


def check_module(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50, node.name
        if isinstance(node, ast.Call):
            assert getattr(node.func, "attr", "") not in {
                "commit",
                "rollback",
                "flush",
                "begin",
                "execute",
                "create_task",
                "ensure_future",
                "from_url",
                "connect",
            }
        assert not isinstance(node, ast.Delete)


def test_visual_crop_modules_have_one_way_dependencies_and_bounded_functions():
    graph, _ = scan_application(APP)
    for module, dependencies in MODULES.items():
        source = (APP / f"features/{module}.py").read_text()
        assert len(source.splitlines()) <= 300
        check_module(ast.parse(source, feature_version=(3, 11)))
        assert graph[f"app.features.{module}"] == dependencies


@pytest.mark.parametrize("operation", ["execute", "create_task", "connect"])
def test_budget_gate_rejects_new_runtime_or_transaction_ownership(operation):
    source = (APP / "features/pipeline_visual_crop.py").read_text()
    tree = ast.parse(source)
    function = next(
        node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
    )
    function.body.append(ast.parse(f"owner.{operation}()").body[0])
    with pytest.raises(AssertionError):
        check_module(tree)


def test_stage_entry_keeps_public_signature_and_passes_live_pipeline():
    from app.features import pipeline_orchestrator as target
    from app.features.pipeline_visual_crop import run_visual_region_crop

    assert target.run_visual_region_crop is run_visual_region_crop
    tree = ast.parse((APP / "features/pipeline_orchestrator.py").read_text())
    pipeline = next(
        node for node in tree.body if getattr(node, "name", "") == "ImportPipeline"
    )
    entry = next(
        node
        for node in pipeline.body
        if getattr(node, "name", "") == "_run_visual_region_crop"
    )
    assert entry.end_lineno - entry.lineno + 1 <= 50
    assert [arg.arg for arg in entry.args.args] == [
        "self",
        "questions",
        "page_image_refs",
    ]
    assert entry.args.kwarg.arg == "_kw"
    assert [ast.literal_eval(value) for value in entry.args.defaults] == [None]
    returned = entry.body[-1]
    assert isinstance(returned.value, ast.Await)
    call = returned.value.value
    assert ast.unparse(call.func) == "run_visual_region_crop"
    assert [ast.unparse(arg) for arg in call.args] == [
        "self",
        "questions",
        "page_image_refs",
    ]
    assert {kw.arg: ast.unparse(kw.value) for kw in call.keywords} == {
        "namespace": "globals()"
    }


def test_importing_visual_crop_does_not_initialize_storage_or_runtime():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError("visual crop import must not create tasks")
asyncio.create_task = forbidden
from app.features.pipeline_visual_crop import run_visual_region_crop
assert callable(run_visual_region_crop)
assert dict(os.environ) == before
for name in (
    'app.core.config', 'app.core.database', 'app.features.pipeline_orchestrator',
    'app.services.storage_backend', 'app.services.visual_region_cropper',
    'app.services.visual_region_types', 'app.core.executor_registry', 'sqlalchemy',
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
