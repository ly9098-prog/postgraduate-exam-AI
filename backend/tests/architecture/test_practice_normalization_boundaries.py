"""Bound session validation without introducing service or persistence owners."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
NORMALIZATION = APP / "services/practice/normalization.py"
SESSION = NORMALIZATION.with_name("session_normalization.py")
ENTRY_IMPORTS = {
    "__future__": {"annotations"},
    "builtins": None,
    "logging": None,
    "datetime": {"datetime"},
    "app.core.subject_scope": {"EXAM408_CORE_CODES"},
    "app.core.time_utils": {"normalize_to_naive_utc"},
    "app.services.practice": {"session_normalization"},
}
SESSION_IMPORTS = {
    "__future__": {"annotations"},
    "collections.abc": {"Callable"},
    "datetime": {"datetime"},
    "typing": {"Any"},
}


def assert_normalization_boundary(source, *, entry=False):
    assert len(source.splitlines()) <= 300
    tree = ast.parse(source)
    functions = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert functions
    assert all(node.end_lineno - node.lineno + 1 <= 50 for node in functions)
    imports = ENTRY_IMPORTS if entry else SESSION_IMPORTS
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(
                alias.name in imports and imports[alias.name] is None
                for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            assert not node.level and node.module in imports
            assert imports[node.module] is not None
            assert all(alias.name in imports[node.module] for alias in node.names)
        assert not isinstance(node, (ast.AsyncFunctionDef, ast.Await))
        if isinstance(node, ast.Call):
            assert getattr(node.func, "id", "") not in {"open", "exec", "eval", "__import__"}
            assert getattr(node.func, "attr", "") not in {
                "execute", "commit", "rollback", "flush", "begin", "begin_nested",
                "open", "read_text", "write_text", "read_bytes", "write_bytes",
                "urlopen", "request", "socket", "connect", "send", "recv",
                "system", "popen", "Popen", "run",
            }
    return {node.name for node in functions}


def test_normalization_modules_have_nonempty_function_size_import_and_io_gates():
    assert NORMALIZATION.is_file() and SESSION.is_file()
    assert "normalize_practice_session" in assert_normalization_boundary(
        NORMALIZATION.read_text(), entry=True,
    )
    assert {
        "normalize_session_timing", "normalize_session_identity",
        "normalize_session_question_count", "normalize_session_values",
    } <= assert_normalization_boundary(SESSION.read_text())


@pytest.mark.parametrize("entry", [False, True])
@pytest.mark.parametrize(
    "source",
    [
        "def small():\n    pass\n" + "\n" * 299,
        "def outer():\n    def nested():\n" + "        pass\n" * 51,
        "from app.core import config\ndef small():\n    pass\n",
        "from .normalization import logger\ndef small():\n    pass\n",
        "from app.services.practice import batch_submission\ndef small():\n    pass\n",
        "def small():\n    return open('payload').read()\n",
        "def small(db):\n    return db.commit()\n",
        "def small():\n    return __import__('socket')\n",
        "async def small():\n    pass\n",
    ],
)
def test_normalization_boundary_rejects_budget_runtime_io_and_async_mutations(
    source, entry,
):
    with pytest.raises(AssertionError):
        assert_normalization_boundary(source, entry=entry)


def test_fresh_import_keeps_normalization_independent_of_runtime_services():
    probe = """
import sys
from app.services.practice.normalization import normalize_practice_session
assert callable(normalize_practice_session)
assert 'app.services.practice.session_normalization' in sys.modules
for name in (
    'app.core.config', 'app.core.database', 'app.models.practice_session',
    'app.services.practice_service', 'app.services.practice.batch_submission_flow',
    'sqlalchemy', 'httpx', 'redis',
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", probe],
        cwd=APP.parent, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
