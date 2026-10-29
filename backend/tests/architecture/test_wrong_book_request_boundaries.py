"""Wrong-book request responsibilities, route contracts and import isolation."""

from __future__ import annotations

import ast
import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
OWNERS = {
    "_contains_code": "wrong_book_sanitization",
    "_fix_code_operator_splits": "wrong_book_sanitization",
    "_sanitize_text_field": "wrong_book_sanitization",
    "_sanitize_content": "wrong_book_sanitization",
    "_sanitize_option_value": "wrong_book_sanitization",
    "_sanitize_options": "wrong_book_sanitization",
    "enrich_wq": "wrong_book_projection",
    "_resolve_product_subject_ids": "wrong_book_queries",
    "_load_current_question_view": "wrong_book_queries",
    "_load_wrong_detail_view": "wrong_book_queries",
    "_enrich_single_wq_extra": "wrong_book_queries",
    "_validate_wrong_book_dates": "wrong_book_queries",
    "list_wrong": "wrong_book_reading",
    "get_task_flow": "wrong_book_reading",
    "get_wrong": "wrong_book_reading",
    "update_wrong": "wrong_book_mutations",
    "batch_operate": "wrong_book_mutations",
    "get_wrong_error_diagnosis": "wrong_book_diagnosis",
    "confirm_wrong_error_diagnosis": "wrong_book_diagnosis",
    "suggest_wrong_error_diagnosis": "wrong_book_diagnosis",
}
FUNCTIONS = {
    "wrong_book_diagnosis": [
        "get_wrong_error_diagnosis",
        "confirm_wrong_error_diagnosis",
        "suggest_wrong_error_diagnosis",
    ],
    "wrong_book_mutations": ["update_wrong", "batch_operate"],
    "wrong_book_projection": [
        "enrich_wq",
        "resolve_analysis_projection",
        "build_wrong_response",
    ],
    "wrong_book_queries": [
        "_resolve_product_subject_ids",
        "_load_current_question_view",
        "_load_wrong_detail_view",
        "_enrich_single_wq_extra",
        "_validate_wrong_book_dates",
        "project_detail_review_fields",
    ],
    "wrong_book_reading": ["list_wrong", "get_task_flow", "get_wrong"],
    "wrong_book_sanitization": [
        "_contains_code",
        "_fix_code_operator_splits",
        "_sanitize_text_field",
        "_sanitize_content",
        "_sanitize_option_value",
        "_sanitize_options",
    ],
}
METADATA = {
    "_contains_code": "5928609535e258f783ce7a34ee69f0babdfd25254c5124d2032155f5237dad79",
    "_resolve_product_subject_ids": "7b70f8295b27a3714a332805bf3157d411d88176b2be1c42205343ae982cb35a",
    "_fix_code_operator_splits": "97a5ce5472609782c7cdbf31071cb83e70256c220c4ba37d734bed9031d91214",
    "_sanitize_text_field": "c975fa4bd577a7570684fe5732f8b7d78c5b3e02fa0e64cc5d4c2aac974867db",
    "_sanitize_content": "389d12cb62f2412d35a36ca73f5c49ffb010c3268bd559394fce6ca2ebd0efc7",
    "_sanitize_option_value": "ad368d2467385f83597940684aa59853cf5139fe1b3dcb68803a87067be67b53",
    "_sanitize_options": "7dc766f2967ce53c836a21a4c6a549ccfbbd22ec703070106ee5b18bb3cf9281",
    "enrich_wq": "e22adc247d39f86ef18bc8b1325d6c62bd6310e46a965f11266f078abc8b0a9d",
    "_load_current_question_view": "fc30ab95591b74a68fecffb4f6016ff524edea8d9cf6636084b39c1be45f629b",
    "_load_wrong_detail_view": "c03c916b600748fafa68170c6652ad4998289e46708db851868f97d8f3f7b190",
    "_enrich_single_wq_extra": "e58509ceead2b8f7058316c396dd0f3926569a46e778559a4affcc5b7d2b25fe",
    "_validate_wrong_book_dates": "da878b031608493f8819d47a94a4412dd363b5688a34a9fde0902e0a3c5459aa",
    "list_wrong": "3877d52ad03eab14db2912edefd456ddf9391ecdaad9d3d2f6b0ca1ad249f41a",
    "get_stats": "51d2a8ac479a6f50f56e7ed22a1112068949f3ad2e79fd46263ae824c48d89df",
    "get_task_flow": "9eab847cfa8a2a72ec414666b2fcd3aa9641ea063d2b8e9cbb40a8884a18d571",
    "get_error_diagnosis_taxonomy": "edf14f3b6913620670a60652032b4f05250818f92196f68c1fc85decea96b15f",
    "get_error_diagnosis_stats": "3b361228d23032986b472a8ee8197b5d143e4ca2beb853006364ae8a1dbadf0b",
    "get_wrong": "5515e259a91fc4923ef0cb0cc4d21b95b7e2979d4556407829527dccffa3ea70",
    "get_wrong_error_diagnosis": "f6f71dc87b25748aeffa46de4c37b82a1f3f0636e3ddc66612bf89a3367a149b",
    "confirm_wrong_error_diagnosis": "bedc111f3ac051638e597185b222062a13ee7005c34e6b5b021b475fed569a13",
    "suggest_wrong_error_diagnosis": "20a5f32b8ea0ffbf58ee289e373ee8cd7ecd9536b9418eb6643149bcd9325d15",
    "update_wrong": "52f2679fae6f537d001223f42125791935db396f88ae358bb354c39e9172f6e8",
    "batch_operate": "8eabc1512784455674d5ec968a234fb9a574c7dafbd9c4db47ecf71dc9305723",
}
UNCHANGED = {
    "get_stats": "38dbc1152ae9ccccf9149f6f7d5d5c83c941345d651768d05f03b1f73a499255",
    "get_error_diagnosis_taxonomy": "c57c42f633df59564f417b3c42aec33456af92591db6b0d2d8b03cc2d7ee7d51",
    "get_error_diagnosis_stats": "b01dbda856d9d4fac41e3ffec817ea46115231568341ec65c5750b642f8c6335",
}


def digest(node):
    return hashlib.sha256(ast.dump(node).encode()).hexdigest()


def validate_modules(sources):
    assert set(sources) == set(FUNCTIONS)
    for name, source in sources.items():
        assert len(source.splitlines()) <= 300, name
        tree = ast.parse(source)
        functions = [
            n
            for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        assert [n.name for n in functions] == FUNCTIONS[name], name
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.end_lineno - node.lineno + 1 <= 50, node.name
                assert not node.decorator_list
                if node.name == "enrich_wq":
                    assert [arg.arg for arg in node.args.posonlyargs] == ["ports"]
                    assert node.args.kwarg.arg == "extra"
                else:
                    assert "ports" in [arg.arg for arg in node.args.kwonlyargs]
            elif isinstance(node, ast.ImportFrom):
                assert node.module == "__future__"
            else:
                assert isinstance(node, ast.Expr) and isinstance(
                    node.value, ast.Constant
                )
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("app.api")
            if isinstance(node, ast.Import):
                assert all(not alias.name.startswith("app.api") for alias in node.names)


def sources():
    return {
        name: (ROOT / "backend/app/services" / (name + ".py")).read_text()
        for name in FUNCTIONS
    }


def test_responsibility_modules_have_bounded_functions_and_one_way_imports():
    validate_modules(sources())


def test_original_route_declarations_and_thin_entrypoints_are_preserved():
    tree = ast.parse((ROOT / "backend/app/api/v1/wrong_questions.py").read_text())
    funcs = {
        n.name: n
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert set(funcs) == set(METADATA) | {"_wrong_book_port"}
    for name, expected in METADATA.items():
        node = funcs[name]
        meta = ast.Tuple(
            elts=[
                node.args,
                ast.List(elts=node.decorator_list, ctx=ast.Load()),
                node.returns or ast.Constant(None),
                ast.Constant(ast.get_docstring(node, clean=False)),
            ],
            ctx=ast.Load(),
        )
        assert digest(meta) == expected, name
        if name in UNCHANGED:
            assert digest(node) == UNCHANGED[name]
        else:
            body = node.body[1:] if ast.get_docstring(node) is not None else node.body
            assert len(body) == 1 and isinstance(body[0], ast.Return), name
            value = body[0].value
            if isinstance(node, ast.AsyncFunctionDef):
                assert isinstance(value, ast.Await), name
                value = value.value
            assert isinstance(value, ast.Call), name
            assert ast.unparse(value.func) == "_wrong_" + OWNERS[name] + "." + name
            expected_args = [arg.arg for arg in node.args.args]
            if name == "enrich_wq":
                expected_args.insert(0, "_wrong_book_port")
            assert [ast.unparse(arg) for arg in value.args] == expected_args
            expected_kwargs = {arg.arg: arg.arg for arg in node.args.kwonlyargs}
            if name != "enrich_wq":
                expected_kwargs["ports"] = "_wrong_book_port"
            if node.args.kwarg:
                expected_kwargs[None] = node.args.kwarg.arg
            assert {
                kw.arg: ast.unparse(kw.value) for kw in value.keywords
            } == expected_kwargs


def test_fresh_import_has_no_route_framework_database_or_config_side_effects():
    code = "import importlib, sys; modules = " + repr(list(FUNCTIONS)) + "; "
    code += "[importlib.import_module('app.services.' + name) for name in modules]; "
    code += "assert not any(name in sys.modules for name in "
    code += (
        repr(
            [
                "fastapi",
                "sqlalchemy",
                "app.core.database",
                "app.core.config",
                "app.api.v1.wrong_questions",
                "app.models.wrong_question",
            ]
        )
        + ")"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT / "backend",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "mutation",
    ["runtime_import", "reverse_import", "unbounded_function", "extra_function"],
)
def test_module_gate_rejects_boundary_and_budget_drift(mutation):
    candidates = sources()
    name = "wrong_book_sanitization"
    if mutation == "runtime_import":
        candidates[name] = "import sqlalchemy\n" + candidates[name]
    elif mutation == "reverse_import":
        candidates[name] = candidates[name].replace(
            "def _contains_code(text, *, ports):",
            "def _contains_code(text, *, ports):\n    from app.api.v1 import exports",
        )
    elif mutation == "unbounded_function":
        candidates[name] = candidates[name].replace(
            "def _contains_code(text, *, ports):",
            "def _contains_code(text, *, ports):" + "\n    pass" * 51,
        )
    else:
        candidates[name] += "\n\ndef unexpected():\n    pass\n"
    with pytest.raises(AssertionError):
        validate_modules(candidates)
