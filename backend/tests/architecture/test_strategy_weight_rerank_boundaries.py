"""Keep reranking's score features pure and its best-effort boundary bounded."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
PROVIDER = APP / "services/practice/strategy_weight_rerank.py"
SCORES = APP / "services/practice/strategy_weight_scores.py"


def assert_score_features_are_pure(source):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        assert not isinstance(node, (ast.Try, ast.Await, ast.AsyncFunctionDef))
        if isinstance(node, ast.Import):
            raise AssertionError("score features do not require module imports")
        if isinstance(node, ast.ImportFrom):
            assert not node.level and node.module in {"__future__", "typing"}
        if isinstance(node, ast.Call):
            assert getattr(node.func, "id", "") not in {
                "open",
                "exec",
                "eval",
                "__import__",
            }
            assert getattr(node.func, "attr", "") not in {
                "execute",
                "scalar",
                "commit",
                "rollback",
                "flush",
                "begin",
                "begin_nested",
                "read_text",
                "write_text",
                "open",
                "random",
            }


def test_provider_and_score_feature_functions_stay_within_budgets():
    for path in (PROVIDER, SCORES):
        source = path.read_text()
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
            if isinstance(node, ast.Call):
                assert getattr(node.func, "attr", "") not in {
                    "commit",
                    "rollback",
                    "flush",
                    "begin",
                    "begin_nested",
                }
    assert_score_features_are_pure(SCORES.read_text())


@pytest.mark.parametrize(
    "mutation",
    [
        "import httpx\n",
        "from app.core import database\n",
        "def injected(db):\n    return db.execute('SELECT 1')\n",
        "def injected():\n    return open('data').read()\n",
    ],
)
def test_score_features_reject_import_or_io_regressions(mutation):
    with pytest.raises(AssertionError):
        assert_score_features_are_pure(SCORES.read_text() + "\n" + mutation)


def test_score_features_import_does_not_initialize_the_sql_provider():
    probe = """
import sys
from app.services.practice.strategy_weight_scores import build_strategy_base_scores
assert callable(build_strategy_base_scores)
for name in (
    'app.core.config', 'app.core.database', 'app.models.question',
    'app.services.practice.strategy_weight_rerank',
    'app.services.recommendation_strategy_service', 'sqlalchemy',
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=APP.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
