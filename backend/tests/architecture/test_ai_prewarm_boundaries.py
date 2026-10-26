"""The revision protocol must be usable without importing worker lifecycle state."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"
REVISION = APP / "ai/prewarm_revision.py"
CONSUMERS = {
    "app.api.v1.ai",
    "app.services.ai_service",
    "app.services.practice.batch_submission_flow",
    "app.services.exam_service",
    "app.services.review_scheduler",
    "app.services.wrong_question_service",
}


def test_revision_has_only_the_prompt_version_and_standard_library_dependencies():
    source = REVISION.read_text(encoding="utf-8")
    tree = ast.parse(source)
    dependencies = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    }
    assert dependencies == {"__future__", "hashlib", "app.ai.prompts"}
    assert len(source.splitlines()) <= 300
    functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    assert [node.name for node in functions] == ["build_prewarm_revision"]
    assert all(node.end_lineno - node.lineno + 1 <= 50 for node in functions)


def test_all_producers_and_validator_import_the_neutral_protocol():
    graph, _ = scan_application(APP)
    actual = {source for source, targets in graph.items() if "app.ai.prewarm_revision" in targets}
    assert actual == CONSUMERS
    assert "app.services.ai_prewarm_worker" not in graph["app.services.ai_service"]
    assert "app.services.ai_service" in graph["app.services.ai_prewarm_worker"]
    for path in APP.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "app.services.ai_prewarm_worker":
                assert all(alias.name != "build_prewarm_revision" for alias in node.names), path
    worker = ast.parse((APP / "services/ai_prewarm_worker.py").read_text(encoding="utf-8"))
    assert not any(isinstance(node, ast.FunctionDef) and node.name == "build_prewarm_revision"
                   for node in ast.walk(worker))


def test_fresh_revision_import_does_not_load_worker_ai_service_or_database():
    probe = """
import sys
from app.ai.prewarm_revision import build_prewarm_revision
assert build_prewarm_revision(review_count=2, wrong_answer='synthetic').startswith('r2:')
for name in ('app.services.ai_prewarm_worker', 'app.services.ai_service', 'app.core.database'):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
