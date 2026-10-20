"""OCR readiness has explicit state and does not import the HTTP application."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"


def test_ocr_readiness_has_single_direction_and_short_functions():
    graph, violations = scan_application(APP)
    assert not violations
    assert graph["app.services.ocr_readiness"] == {
        "app.core.config", "app.core.ocr_isolation", "app.core.log_context",
    }
    assert "app.services.ocr_readiness" in graph["app.main"]
    assert "app.services.ocr_readiness" in graph["app.cli.doctor"]
    assert "app.main" not in graph["app.cli.doctor"]
    source = (APP / "services/ocr_readiness.py").read_text()
    assert len(source.splitlines()) <= 300
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50, node.name


def test_http_assembly_owns_one_state_and_consumes_actual_check():
    from app import main
    from app.services.ocr_readiness import OcrReadinessState, check_ocr_config

    assert main.check_ocr_config is check_ocr_config
    assert isinstance(main.ocr_readiness_state, OcrReadinessState)
    assert not hasattr(main, "_ocr_remote_consecutive_failures")
    assert not hasattr(main, "_check_ocr_config")
    assert not hasattr(main, "_check_ocr_remote_connectivity")
    source = (APP / "main.py").read_text()
    assert source.count("ocr_readiness_state = OcrReadinessState()") == 1


def test_readiness_module_loads_without_configuration_or_transport_runtime():
    probe = """
import sys
from app.services.ocr_readiness import OcrReadinessState, check_ocr_remote_connectivity
assert OcrReadinessState().consecutive_failures == 0
for name in ('app.main', 'app.core.config', 'app.core.database', 'httpx',
             'app.core.ocr_isolation', 'app.services.ocr_service'):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
