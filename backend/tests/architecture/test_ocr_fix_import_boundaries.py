"""OCR contracts must be usable without loading configured AI implementations."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.architecture.dependency_scan import cyclic_edges, scan_application

APP = Path(__file__).resolve().parents[2] / "app"
PACKAGE = "app.features.ocr_fix"


def test_ocr_package_has_no_eager_exports_and_consumers_use_defining_modules():
    tree = ast.parse((APP / "features/ocr_fix/__init__.py").read_text(encoding="utf-8"))
    assert len(tree.body) == 1
    assert isinstance(tree.body[0], ast.Expr)
    assert isinstance(tree.body[0].value, ast.Constant)
    assert isinstance(tree.body[0].value.value, str)
    graph, _ = scan_application(APP)
    assert graph[PACKAGE] == set()
    assert not any(PACKAGE in targets for targets in graph.values())
    assert not any(source.startswith(PACKAGE) for source, _ in cyclic_edges(graph))
    for consumer in ("app.features.ocr_correction", "app.features.pipeline_vl_rebuild_source"):
        assert f"{PACKAGE}.router" in graph[consumer]
    assert "app.features.pipeline_vl_rebuild_source" in graph[
        "app.features.pipeline_orchestrator"
    ]
    assert f"{PACKAGE}.interfaces" in graph[f"{PACKAGE}.openai_compatible_adapter"]


@pytest.mark.parametrize("module", [
    PACKAGE, f"{PACKAGE}.interfaces", f"{PACKAGE}.canonical_output", f"{PACKAGE}.router",
])
def test_contract_and_router_imports_do_not_load_ai_or_database(module):
    probe = """
import importlib
import sys
importlib.import_module(sys.argv[1])
for name in (
    'app.ai.client', 'app.core.config', 'app.core.database',
    'app.features.ocr_fix.openai_compatible_adapter',
    'app.features.ocr_fix.deepseek_adapter',
    'app.features.ocr_fix.rule_adapter',
    'app.features.ocr_vl.paddleocr_vl_adapter',
):
    assert name not in sys.modules, name
"""
    env = dict(os.environ, APP_ENV="invalid-import-boundary-probe")
    result = subprocess.run(
        [sys.executable, "-c", probe, module], cwd=APP.parent, env=env,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("module", [
    f"{PACKAGE}.openai_compatible_adapter", f"{PACKAGE}.deepseek_adapter",
])
def test_adapter_first_import_shares_canonical_result_type(module):
    probe = """
import importlib
import sys
module = importlib.import_module(sys.argv[1])
from app.features.ocr_fix.openai_compatible_adapter import OpenAICompatibleFixer
from app.features.ocr_fix.interfaces import OCRFixResult
assert not hasattr(importlib.import_module('app.features.ocr_fix'), 'OCRFixRouter')
if sys.argv[1].endswith('deepseek_adapter'):
    assert issubclass(module.DeepSeekFixer, OpenAICompatibleFixer)
else:
    assert module.ocr_fix_interfaces.OCRFixResult is OCRFixResult
assert 'app.features.ocr_fix.router' not in sys.modules
assert 'app.core.database' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", probe, module], cwd=APP.parent,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
