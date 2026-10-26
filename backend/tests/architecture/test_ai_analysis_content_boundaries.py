"""Keep recursive AI response parsing bounded and independent of runtime state."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
CONTENT = APP / "services/ai/analysis_content.py"
HELPERS = (
    CONTENT.with_name("analysis_text_syntax.py"),
    CONTENT.with_name("analysis_answer_check.py"),
)


def assert_content_boundary(source, *, entry=False):
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
        if isinstance(node, ast.Import):
            assert entry
            assert all(alias.name in {"ast", "json", "re"} for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module != "__future__":
                assert entry and node.module == "app.services.ai"
                assert not node.level
                assert all(
                    alias.name in {"analysis_text_syntax", "analysis_answer_check"}
                    for alias in node.names
                )
        assert not isinstance(node, (ast.Await, ast.AsyncFunctionDef))


def test_analysis_content_and_helpers_keep_module_function_and_import_budgets():
    assert_content_boundary(CONTENT.read_text(), entry=True)
    for path in HELPERS:
        assert path.is_file()
        assert_content_boundary(path.read_text())


@pytest.mark.parametrize("entry", [False, True])
@pytest.mark.parametrize(
    "source",
    [
        "def small():\n    pass\n" + "\n" * 299,
        "def outer():\n    def nested():\n" + "        pass\n" * 51,
        "def small():\n    pass\nfrom app.core import config\n",
        "def small():\n    pass\nfrom app.services.ai import analysis_cache\n",
        "async def asynchronous():\n    pass\n",
    ],
)
def test_content_boundaries_reject_budget_runtime_and_async_mutations(source, entry):
    with pytest.raises(AssertionError):
        assert_content_boundary(source, entry=entry)


def test_analysis_content_import_does_not_initialize_service_models_or_config():
    probe = """
import sys
from app.services.ai.analysis_content import parse_error_analysis_content
assert callable(parse_error_analysis_content)
assert 'app.services.ai.analysis_text_syntax' in sys.modules
assert 'app.services.ai.analysis_answer_check' in sys.modules
for name in (
    'app.core.config', 'app.core.database', 'app.services.ai_service',
    'sqlalchemy', 'httpx', 'redis',
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
