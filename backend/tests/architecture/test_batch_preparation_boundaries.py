"""Preparation stays synchronous and independent of persistence or runtime setup."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
FLOW = APP / "services/practice/batch_submission_flow.py"
PREPARATION = FLOW.with_name("batch_submission_preparation.py")
FUNCTIONS = {
    "validate_protocol", "prepare_batch_submission", "validate_session_contract",
    "validated_revision_questions", "validate_scope_subject", "build_practice_session",
}


def inspect_preparation(source):
    assert len(source.splitlines()) <= 300
    tree = ast.parse(source)
    functions = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            assert node.end_lineno - node.lineno + 1 <= 50
        assert not isinstance(node, (ast.Import, ast.AsyncFunctionDef, ast.Await))
        if isinstance(node, ast.ImportFrom):
            assert (node.module, tuple(alias.name for alias in node.names)) in {
                ("__future__", ("annotations",)),
                ("collections.abc", ("Callable",)), ("typing", ("Any",)),
            }
        if isinstance(node, ast.Call):
            assert getattr(node.func, "id", "") not in {"open", "eval", "exec", "__import__"}
            assert getattr(node.func, "attr", "") not in {
                "execute", "commit", "rollback", "flush", "begin", "begin_nested",
                "read_text", "write_text", "read_bytes", "write_bytes",
                "connect", "send", "request", "run", "Popen",
            }
    return functions


def test_preparation_and_original_flow_stay_bounded():
    assert PREPARATION.is_file() and FLOW.is_file()
    assert inspect_preparation(PREPARATION.read_text()) == FUNCTIONS
    source = FLOW.read_text()
    assert len(source.splitlines()) <= 300
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50


@pytest.mark.parametrize("source", [
    "def prepare():\n    pass\n" + "\n" * 299,
    "def prepare():\n    def inner():\n" + "        pass\n" * 51,
    "from app.core import config\ndef prepare():\n    pass\n",
    "from .batch_submission_flow import PreparedBatchSubmission\n",
    "async def prepare():\n    pass\n",
    "def prepare(db):\n    db.commit()\n",
    "def prepare():\n    return __import__('socket')\n",
    "def prepare():\n    return open('payload').read()\n",
])
def test_preparation_gate_rejects_injected_runtime_and_budget_debt(source):
    with pytest.raises(AssertionError):
        inspect_preparation(source)


def test_preparation_fresh_import_does_not_load_flow_database_or_runtime_services():
    probe = """
import sys
from app.services.practice import batch_submission_preparation
assert callable(batch_submission_preparation.prepare_batch_submission)
for name in (
    'app.services.practice.batch_submission_flow', 'app.core.database',
    'app.core.config', 'app.models.practice_session', 'sqlalchemy', 'redis', 'httpx',
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", probe], cwd=APP.parent,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
