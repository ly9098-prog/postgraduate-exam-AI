"""Bound extraction owners while keeping runtime and IO behind live ports."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
FEATURES = APP / "features"
HELPERS = {
    "pipeline_extract_stage": {
        "__future__": {"annotations"},
        "collections.abc": {"Callable"},
        "functools": {"partial"},
        "typing": {"Any"},
        "app.features.pipeline_extract_diagnostics": {
            "project_extract_result",
            "resolve_extract_port",
        },
        "app.features.pipeline_extract_pdf": {
            "ExtractedContent",
            "extract_pdf_content",
        },
    },
    "pipeline_extract_pdf": {
        "__future__": {"annotations"},
        "collections.abc": {"Callable"},
        "dataclasses": {"dataclass", "field"},
        "typing": {"Any"},
        "app.core.config": {"settings"},
        "app.features.exercise_region_detector": {"detect_exercise_regions"},
    },
    "pipeline_extract_diagnostics": {
        "__future__": {"annotations"},
        "collections.abc": {"Callable"},
        "typing": {"Any"},
    },
}


def assert_extract_helper_boundary(source, imports):
    assert len(source.splitlines()) <= 300
    tree = ast.parse(source)
    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert functions
    assert all(node.end_lineno - node.lineno + 1 <= 50 for node in functions)
    for node in ast.walk(tree):
        assert not isinstance(node, (ast.Import, ast.AsyncFunctionDef, ast.Await))
        if isinstance(node, ast.ImportFrom):
            assert not node.level and node.module in imports
            assert {alias.name for alias in node.names} <= imports[node.module]
            if node.module in {
                "app.core.config",
                "app.features.exercise_region_detector",
            }:
                assert node not in tree.body
        if isinstance(node, ast.Call):
            assert getattr(node.func, "id", "") not in {
                "open",
                "exec",
                "eval",
                "__import__",
            }
            assert getattr(node.func, "attr", "") not in {
                "execute",
                "commit",
                "rollback",
                "flush",
                "begin",
                "begin_nested",
                "open",
                "read_text",
                "write_text",
                "read_bytes",
                "write_bytes",
                "urlopen",
                "request",
                "socket",
                "connect",
                "send",
                "recv",
                "system",
                "popen",
                "Popen",
                "run",
                "time",
                "monotonic",
                "perf_counter",
            }


def assert_extract_entry_boundary(source):
    tree = ast.parse(source)
    owner = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ImportPipeline"
    )
    entry = next(
        node
        for node in owner.body
        if isinstance(node, ast.FunctionDef) and node.name == "_run_extract"
    )
    assert entry.end_lineno - entry.lineno + 1 <= 50
    calls = [node for node in ast.walk(entry) if isinstance(node, ast.Call)]
    assert [getattr(node.func, "id", None) for node in calls] == [
        "run_extract_stage",
        "globals",
    ]


def test_extract_helpers_and_entry_keep_size_import_and_io_boundaries():
    for name, imports in HELPERS.items():
        path = FEATURES / f"{name}.py"
        assert path.is_file()
        assert_extract_helper_boundary(path.read_text(), imports)
    assert_extract_entry_boundary((FEATURES / "pipeline_orchestrator.py").read_text())


@pytest.mark.parametrize("helper", HELPERS)
@pytest.mark.parametrize(
    "source",
    [
        "def small(): pass\n" + "\n" * 300,
        "def outer():\n    def nested():\n" + "        pass\n" * 51,
        "from app.features.pipeline_orchestrator import logger\ndef small(): pass\n",
        "from app.core.config import settings\ndef small(): pass\n",
        "async def small(): pass\n",
        "def small():\n    return open('source').read()\n",
        "def small(db):\n    return db.commit()\n",
        "def small(clock):\n    return clock.perf_counter()\n",
    ],
)
def test_extract_helper_boundaries_reject_injected_violations(helper, source):
    with pytest.raises(AssertionError):
        assert_extract_helper_boundary(source, HELPERS[helper])


def test_extract_entry_budget_rejects_future_inline_expansion():
    oversized = (
        "class ImportPipeline:\n    def _run_extract(self):\n"
        + "        value = 1\n" * 51
    )
    with pytest.raises(AssertionError):
        assert_extract_entry_boundary(oversized)


def test_fresh_extract_import_does_not_initialize_orchestrator_config_or_engines():
    probe = """
import sys
from app.features.pipeline_extract_stage import run_extract_stage
assert callable(run_extract_stage)
for name in ('pipeline_extract_stage', 'pipeline_extract_pdf', 'pipeline_extract_diagnostics'):
    assert f'app.features.{name}' in sys.modules, name
for name in (
    'app.features.pipeline_orchestrator', 'app.core.config', 'app.core.database',
    'app.features.exercise_region_detector', 'fitz', 'paddleocr', 'sqlalchemy',
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", probe],
        cwd=APP.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
