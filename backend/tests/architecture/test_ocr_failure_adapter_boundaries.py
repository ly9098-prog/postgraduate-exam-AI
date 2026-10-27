"""Failure normalization stays synchronous, bounded and behind local OCR guards."""

import ast
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "app/services/ocr_service.py"
FUNCTIONS = (
    "_gateway_results_all_failed",
    "_gateway_page_text",
    "ocr_pages",
    "_legacy_ocr_pages_with_boxes",
    "_worker_result_to_page_result",
)


def inspect_function(source, name):
    functions = [
        n
        for n in ast.parse(source, feature_version=(3, 11)).body
        if isinstance(n, ast.FunctionDef) and n.name == name
    ]
    assert len(functions) == 1
    node = functions[0]
    assert node.end_lineno - node.lineno + 1 <= 50
    assert not any(
        isinstance(n, (ast.AsyncFunctionDef, ast.Await)) for n in ast.walk(node)
    )
    return node


@pytest.mark.parametrize("name", FUNCTIONS)
def test_failure_adapters_are_bounded_synchronous_functions(name):
    assert SOURCE.is_file()
    inspect_function(SOURCE.read_text(), name)


@pytest.mark.parametrize("source", ["", "def too_big():\n" + "    pass\n" * 51])
def test_function_gate_rejects_missing_or_oversized_implementation(source):
    with pytest.raises(AssertionError):
        inspect_function(source, "too_big")


@pytest.mark.parametrize("name", ["_legacy_ocr_pages", "_legacy_ocr_pages_with_boxes"])
def test_local_executor_import_is_still_after_cloud_guard(name):
    node = inspect_function(SOURCE.read_text(), name)
    assert ast.unparse(node.body[1]) == f"_reject_cloud_legacy('{name}')"
    assert isinstance(node.body[2], ast.ImportFrom)
    assert node.body[2].module == "app.services.ocr_executor_service"
