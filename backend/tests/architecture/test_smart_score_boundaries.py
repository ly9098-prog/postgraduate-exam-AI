"""Keep scoring policy pure and its numerical groups independently bounded."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"
MODULES = ("smart_score_history", "smart_score_path", "smart_reason_text")


def assert_bounded_functions(source):
    tree = ast.parse(source)
    functions = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert functions
    assert all(node.end_lineno - node.lineno + 1 <= 50 for node in functions)
    return {node.name for node in functions}


def assert_neutral_rules(source):
    assert len(source.splitlines()) <= 150
    assert_bounded_functions(source)
    allowed_imports = {"__future__", "collections.abc", "datetime"}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            assert all(alias.name in allowed_imports for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert not node.level and node.module in allowed_imports
        assert not isinstance(node, (ast.Try, ast.Await, ast.AsyncFunctionDef))
        if isinstance(node, ast.Call):
            assert getattr(node.func, "id", "") not in {
                "open", "exec", "eval", "__import__",
            }
            assert getattr(node.func, "attr", "") not in {
                "execute", "commit", "rollback", "flush", "begin", "begin_nested",
                "open", "read_text", "write_text", "read_bytes", "write_bytes",
                "urlopen", "request", "socket", "connect", "send", "recv",
                "system", "popen", "Popen", "run",
            }


def test_score_groups_are_neutral_bounded_and_have_no_persistence_ports():
    graph, _ = scan_application(APP)
    expected = {f"app.services.practice.{name}" for name in MODULES}
    assert expected <= graph["app.services.practice.smart_scoring"]
    for name in MODULES:
        assert not graph[f"app.services.practice.{name}"]
        source = (APP / f"services/practice/{name}.py").read_text()
        assert_neutral_rules(source)
    scoring = (APP / "services/practice/smart_scoring.py").read_text()
    assert {"calculate_smart_score", "_build_smart_recommendation_reason"} <= (
        assert_bounded_functions(scoring)
    )


@pytest.mark.parametrize("mutation", [
    "from pathlib import Path\n    return Path('data').read_text()",
    "return open('data', 'w').write('changed')",
    "import httpx\n    return httpx.get('https://example.test')",
    "return __import__('subprocess').run(['command'])",
])
def test_neutral_rules_reject_external_imports_and_direct_io(mutation):
    with pytest.raises(AssertionError):
        assert_neutral_rules("def injected():\n    " + mutation + "\n")


@pytest.mark.parametrize("prefix", ["def", "async def"])
def test_scoring_budget_rejects_future_oversized_helpers(prefix):
    source = (APP / "services/practice/smart_scoring.py").read_text()
    oversized = f"\n{prefix} future_helper():\n" + "    value = 1\n" * 51
    with pytest.raises(AssertionError):
        assert_bounded_functions(source + oversized)


def test_scoring_import_does_not_load_models_config_or_database():
    probe = """
import sys
from app.services.practice.smart_scoring import calculate_smart_score
assert callable(calculate_smart_score)
for name in (
    'app.core.config', 'app.core.database', 'app.models.question',
    'app.services.practice_service', 'sqlalchemy',
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
