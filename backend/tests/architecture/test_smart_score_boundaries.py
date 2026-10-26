"""Keep scoring policy pure and its numerical groups independently bounded."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"
MODULES = ("smart_score_history", "smart_score_path")


def test_score_groups_are_neutral_bounded_and_have_no_persistence_ports():
    graph, _ = scan_application(APP)
    expected = {f"app.services.practice.{name}" for name in MODULES}
    assert expected <= graph["app.services.practice.smart_scoring"]
    for name in MODULES:
        assert not graph[f"app.services.practice.{name}"]
        source = (APP / f"services/practice/{name}.py").read_text()
        assert len(source.splitlines()) <= 150
        tree = ast.parse(source)
        functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
        assert functions
        assert all(node.end_lineno - node.lineno + 1 <= 50 for node in functions)
        assert not any(isinstance(node, (ast.Try, ast.Await, ast.AsyncFunctionDef)) for node in ast.walk(tree))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                assert getattr(node.func, "attr", "") not in {
                    "execute", "commit", "rollback", "flush", "begin", "begin_nested",
                }
    scoring = ast.parse((APP / "services/practice/smart_scoring.py").read_text())
    entry = next(node for node in scoring.body if getattr(node, "name", "") == "calculate_smart_score")
    assert entry.end_lineno - entry.lineno + 1 <= 50


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
