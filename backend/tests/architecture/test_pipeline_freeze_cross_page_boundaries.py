"""Freeze projection and page merging stay synchronous, bounded and free of I/O."""

import ast
from pathlib import Path

import pytest

FEATURES = Path(__file__).resolve().parents[2] / "app/features"
MODULES = {
    "pipeline_frozen_options": {
        "apply_frozen_options",
        "_verify_registry_checksum",
        "_index_block_text",
        "_question_block_keys",
        "_apply_question_options",
    },
    "pipeline_freeze_comparison": {"compare_freeze_results", "_freeze_differences"},
    "pipeline_freeze_rebinding": {"remap_frozen_registry", "_rebuilt_option_texts"},
    "pipeline_cross_page_merge": {
        "merge_cross_page_blocks",
        "apply_cross_page_block_merge",
        "_merge_one_link",
        "_merge_source_block",
        "_record_cross_page_merge",
    },
}
PORTS = {
    "logger",
    "os",
    "_get_blocks_document_ir",
    "_apply_cross_page_block_merge",
    "Exception",
    "dict",
    "len",
    "str",
    "range",
    "sorted",
    "set",
    "list",
    "max",
    "getattr",
    "hasattr",
    "isinstance",
    "enumerate",
}
IMPORTS = {
    "__future__": {"annotations"},
    "typing": {"Any", "TYPE_CHECKING"},
    "app.features.pipeline_stages.structure_freeze_stage": {
        "FrozenOptionEntry",
        "_compute_freeze_checksum",
    },
    "app.features.cross_page_linking": {
        "detect_cross_page_links",
        "CrossPageMergeResult",
        "_get_page_text",
    },
}
METHODS = {
    "get",
    "items",
    "setdefault",
    "strip",
    "warning",
    "debug",
    "info",
    "add",
    "keys",
    "append",
    "split",
    "startswith",
    "to_dict",
}
WRAPPERS = {
    "_apply_frozen_options": "apply_frozen_options(raw_questions, frozen_option_registry, freeze_checksum, normalized_blocks, ports=partial(resolve_split_port, globals()))",
    "_compare_freeze_results": "compare_freeze_results(legacy_result, ir_result, legacy_registry, ir_registry, ports=partial(resolve_split_port, globals()))",
    "_remap_frozen_registry_vl_rebuild": "remap_frozen_registry(old_registry, rebuilt_blocks, ports=partial(resolve_split_port, globals()))",
    "_merge_cross_page_blocks": "merge_cross_page_blocks(blocks, doc_ir, ports=partial(resolve_split_port, globals()))",
    "_apply_cross_page_block_merge": "apply_cross_page_block_merge(blocks, links, doc_ir, ports=partial(resolve_split_port, globals()))",
}


def inspect_module(source, role):
    assert len(source.splitlines()) <= 300
    tree = ast.parse(source)
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    assert len(functions) == len(MODULES[role])
    assert {n.name for n in functions} == MODULES[role]
    direct_calls = MODULES[role] | {
        "ports",
        "_verify_checksum",
        "detect_cross_page_links",
        "result_type",
        "page_text",
    }
    for node in ast.walk(tree):
        assert not isinstance(
            node,
            (
                ast.Import,
                ast.AsyncFunctionDef,
                ast.Await,
                ast.ClassDef,
                ast.Global,
                ast.Nonlocal,
                ast.Lambda,
                ast.Delete,
                ast.NamedExpr,
            ),
        )
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0 and node.module in IMPORTS
            assert all(a.name in IMPORTS[node.module] for a in node.names)
        if isinstance(node, ast.FunctionDef):
            assert node in functions and not node.decorator_list
            assert node.end_lineno - node.lineno + 1 <= 50
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                assert node.func.id in direct_calls
                if node.func.id == "ports":
                    assert len(node.args) == 1 and not node.keywords
                    assert isinstance(node.args[0], ast.Constant)
                    assert node.args[0].value in PORTS
            elif isinstance(node.func, ast.Attribute):
                assert node.func.attr in METHODS
            else:
                assert isinstance(node.func, ast.Call)
                assert (
                    isinstance(node.func.func, ast.Name)
                    and node.func.func.id == "ports"
                )
    return tree


def inspect_wrappers(source):
    tree = ast.parse(source)
    found = {
        n.name: n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name in WRAPPERS
    }
    assert set(found) == set(WRAPPERS)
    for name, expected in WRAPPERS.items():
        actual = ast.Module(body=found[name].body, type_ignores=[])
        assert ast.dump(actual) == ast.dump(ast.parse("return " + expected))


@pytest.mark.parametrize("role", MODULES)
def test_responsibility_budgets_and_capabilities(role):
    inspect_module((FEATURES / (role + ".py")).read_text(), role)


def test_original_entrypoints_are_live_single_delegates():
    inspect_wrappers((FEATURES / "pipeline_orchestrator.py").read_text())


@pytest.mark.parametrize(
    "injection",
    [
        "open('file')",
        "ports('open')('file')",
        "ports(name)()",
        "db.execute('sql')",
        "import subprocess",
        "from os import remove",
    ],
)
def test_gate_rejects_new_io_and_dynamic_capabilities(injection):
    role = "pipeline_frozen_options"
    source = (FEATURES / (role + ".py")).read_text()
    source += "\n" + injection + "\n"
    with pytest.raises(AssertionError):
        inspect_module(source, role)


def test_gate_rejects_detached_entrypoint():
    source = (FEATURES / "pipeline_orchestrator.py").read_text()
    source = source.replace("return merge_cross_page_blocks(", "return list(", 1)
    with pytest.raises(AssertionError):
        inspect_wrappers(source)
