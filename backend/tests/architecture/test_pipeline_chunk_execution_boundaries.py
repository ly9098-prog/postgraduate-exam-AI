"""Guard single-chunk execution budgets, delegation, and fresh imports."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
FEATURES = APP / "features"
MODULE = FEATURES / "pipeline_chunk_execution.py"
ORCHESTRATOR = FEATURES / "pipeline_orchestrator.py"
FUNCTIONS = {
    "resolve_chunk_port",
    "build_chunk_execution_state",
    "run_chunk_execution",
    "render_chunk_page_window",
    "initialize_chunk_execution",
    "run_chunk_single_pass",
    "finalize_chunk_execution",
    "project_chunk_result",
}
ALLOWED_IMPORTS = {
    "__future__": {"annotations"},
    "dataclasses": {"dataclass", "field"},
    "typing": {"Any"},
    "app.core.config": {"settings"},
    "app.services.pdf_renderer_service": {"pdf_renderer"},
    "app.features": {"pipeline_checkpoint"},
}
FORBIDDEN_CALLS = {
    "commit",
    "rollback",
    "execute",
    "flush",
    "connect",
    "read_text",
    "write_text",
    "read_bytes",
    "write_bytes",
}
ENTRY_KWONLY = [
    "chunk_index",
    "page_start",
    "logical_end",
    "total_pages",
    "is_last_chunk",
    "chunk_overlap",
    "file_content",
    "file_path",
    "source_type",
    "source_file",
    "subject",
    "subject_id",
    "opts",
    "db",
    "shared",
    "progress_callback",
    "started_at",
    "seen_hashes",
    "hash_index",
    "page_images",
    "page_image_refs",
]


def inspect_module(source: str):
    assert len(source.splitlines()) <= 300
    tree = ast.parse(source, feature_version=(3, 11))
    functions = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert functions == FUNCTIONS
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            assert node.end_lineno - node.lineno + 1 <= 50
        if isinstance(node, ast.Import):
            raise AssertionError("use explicit bounded imports")
        if isinstance(node, ast.ImportFrom):
            assert not node.level and node.module in ALLOWED_IMPORTS
            assert all(
                alias.name in ALLOWED_IMPORTS[node.module] for alias in node.names
            )
        if isinstance(node, ast.Call):
            assert getattr(node.func, "attr", "") not in FORBIDDEN_CALLS
        if isinstance(node, ast.Name):
            assert node.id not in {"open", "eval", "exec", "__import__"}
    return tree


def test_chunk_execution_module_keeps_budgets_and_explicit_dependencies():
    inspect_module(MODULE.read_text())


def test_execute_chunk_keeps_full_signature_and_delegates_to_helper():
    tree = ast.parse(ORCHESTRATOR.read_text())
    entry = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_execute_chunk"
    )
    assert entry.end_lineno - entry.lineno + 1 <= 50
    assert [arg.arg for arg in entry.args.args] == ["self"]
    assert [arg.arg for arg in entry.args.kwonlyargs] == ENTRY_KWONLY
    assert isinstance(entry.body[-1], ast.Return)
    assert (
        ast.unparse(entry.body[-1].value)
        == "await run_chunk_execution(build_chunk_execution_state(self, locals(), globals()))"
    )


@pytest.mark.parametrize(
    "source",
    [
        "def extra():\n    return 1\n",
        "def extra():\n    return open('payload')\n",
        "def extra():\n    return db.commit()\n",
    ],
)
def test_gate_rejects_extra_functions_forbidden_io_and_budget_growth(source):
    with pytest.raises((AssertionError, StopIteration)):
        inspect_module(MODULE.read_text() + source)


def test_fresh_chunk_execution_import_does_not_load_runtime_resources():
    probe = """
import sys
from app.features.pipeline_chunk_execution import run_chunk_execution
assert callable(run_chunk_execution)
for name in (
    'app.core.config', 'app.services.pdf_renderer_service',
    'app.features.pipeline_checkpoint', 'app.features.pipeline_orchestrator',
    'sqlalchemy', 'redis', 'httpx',
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", probe],
        cwd=APP.parent,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
