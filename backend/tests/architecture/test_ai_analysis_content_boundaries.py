"""Keep recursive AI response parsing bounded and independent of runtime state."""

import ast
import subprocess
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"
CONTENT = APP / "services/ai/analysis_content.py"


def test_analysis_content_functions_are_bounded_and_only_import_standard_parsers():
    tree = ast.parse(CONTENT.read_text())
    functions = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert functions
    assert all(node.end_lineno - node.lineno + 1 <= 50 for node in functions)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name in {"ast", "json", "re"} for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.module == "__future__"
        assert not isinstance(node, (ast.Await, ast.AsyncFunctionDef))


def test_analysis_content_import_does_not_initialize_service_models_or_config():
    probe = """
import sys
from app.services.ai.analysis_content import parse_error_analysis_content
assert callable(parse_error_analysis_content)
for name in (
    'app.core.config', 'app.core.database', 'app.services.ai_service',
    'sqlalchemy', 'httpx', 'redis',
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
