"""IR source bindings have no runtime I/O and cannot reenter legacy injection."""

import ast
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.architecture.ir_freeze_binding_boundary_policy import (
    ATTRIBUTE_WRITES,
    BUILTINS,
    IMPORTS,
    MODULES,
    RULES,
    call_name,
    inspect_capture,
    inspect_split_wiring,
)
from tests.architecture.pipeline_freeze_boundary_policy import bounded

FEATURES = Path(__file__).resolve().parents[2] / "app/features"


def inspect_import(node, role):
    if isinstance(node, ast.Import):
        assert all(
            a.name in IMPORTS[role] and not IMPORTS[role][a.name] and a.asname is None
            for a in node.names
        )
    else:
        assert isinstance(node, ast.ImportFrom) and not node.level
        assert node.module in IMPORTS[role]
        assert all(a.name in IMPORTS[role][node.module] and a.asname is None for a in node.names)


def inspect_node(node, parents, function, names):
    calls, locals_, attributes, stores = RULES[function]
    assert not isinstance(node, (ast.Delete, ast.Global, ast.Nonlocal, ast.NamedExpr, ast.ClassDef))
    if isinstance(node, ast.Call):
        assert call_name(node.func) in calls.split("|")
        if call_name(node.func) == "getattr":
            assert ast.unparse(node) == "getattr(document, '_freeze_source_capture', None)"
        if call_name(node.func) == "ports":
            assert ast.unparse(node) == "ports('split_questions')"
    if isinstance(node, ast.Attribute):
        assert not node.attr.startswith("__")
        parent = parents[node]
        invoked = isinstance(parent, ast.Call) and parent.func is node
        assert invoked or ast.unparse(node) in attributes.split("|")
        if isinstance(node.ctx, ast.Store):
            assert ast.unparse(node) in ATTRIBUTE_WRITES.get(function, set())
    if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store):
        assert ast.unparse(node.value) in stores.split()
    if isinstance(node, ast.Name):
        assert node.id in (locals_.split() if isinstance(node.ctx, ast.Store) else names)
        if node.id == "ports":
            assert isinstance(parents[node], ast.Call) and parents[node].func is node
        if node.id == "state":
            assert isinstance(parents[node], ast.Attribute)


def inspect_pure_helper(source, role):
    tree = bounded(source)
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    assert {n.name for n in functions} == MODULES[role] and len(functions) == len(MODULES[role])
    imported = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            inspect_import(node, role)
            imported.update(a.name for a in node.names)
        elif not isinstance(node, ast.FunctionDef):
            assert isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
            assert isinstance(node.value.value, str)
    for function in functions:
        assert not function.decorator_list
        parents = {c: n for n in ast.walk(function) for c in ast.iter_child_nodes(n)}
        names = imported | BUILTINS | MODULES[role] | set(RULES[function.name][1].split())
        names |= {n.arg for n in ast.walk(function.args) if isinstance(n, ast.arg)}
        for node in ast.walk(function):
            assert not isinstance(node, (ast.Import, ast.ImportFrom))
            assert not isinstance(node, ast.FunctionDef) or node is function
            inspect_node(node, parents, function.name, names)
    return tree


def assert_ir_cannot_apply(namespace):
    for mode in ("ir", "ir_canary"):
        for plan in (None, {}):
            state = SimpleNamespace(
                keyword_arguments={
                    "freeze_mode": mode,
                    "freeze_block_binding": plan,
                    "freeze_canary_fallback": True,
                    "freeze_ir_empty": True,
                },
                extra_data={},
                frozen_option_registry={"1:0": {"A": "stale"}},
                ir_freeze_binding=None,
                freeze_input_changed=False,
                split_blocks=[],
                structure=None,
                gap_tolerance=10,
                import_mode_str="exam",
                layout_result={},
                split_mode="standard",
            )
            namespace["initialize_split_binding"](state)
            assert state.frozen_option_registry == {} and state.ir_freeze_binding is not None

            def ports(name):
                assert name == "split_questions"

                def split(*args, **kwargs):
                    assert not kwargs["frozen_option_registry"]
                    assert kwargs["freeze_block_binding"] is state.ir_freeze_binding
                    return []

                return split

            namespace["execute_split_questions"](state, ports=ports)
            assert not state.frozen_option_registry and state.raw_questions == []


@pytest.mark.parametrize("role", MODULES)
def test_binding_modules_have_explicit_pure_rule_capabilities(role):
    inspect_pure_helper((FEATURES / f"{role}.py").read_text(), role)


def test_capture_and_split_ownership_are_at_the_actual_boundaries():
    inspect_capture(ast.parse((FEATURES / "document_ir_builder.py").read_text()))
    inspect_split_wiring(ast.parse((FEATURES / "pipeline_split_stage.py").read_text()))


def test_ir_missing_and_invalid_plans_cannot_feed_final_legacy_apply():
    from app.features import pipeline_split_binding
    from app.features.pipeline_split_result import finish_split_result

    assert_ir_cannot_apply(vars(pipeline_split_binding))
    state = SimpleNamespace(
        keyword_arguments={"freeze_mode": "ir"},
        extra_data={},
        frozen_option_registry={"x": {}},
        ir_freeze_binding=None,
        raw_questions=[],
        split_blocks=[],
        import_mode_str="exam",
        split_diagnostics={},
        warnings=[],
    )
    pipeline_split_binding.initialize_split_binding(state)

    def ports(name):
        assert name != "_apply_frozen_options"

        def no_effect(*args, **kwargs):
            return None

        return no_effect

    finish_split_result(state, ports=ports)


@pytest.mark.parametrize(
    "role,function,statement",
    [
        ("freeze_source_binding", "block_snapshot", "open('x')"),
        ("freeze_source_binding", "record_region_source", "document.pages.clear()"),
        ("freeze_source_binding", "binding_checksum", "__import__('socket')"),
        ("freeze_source_binding", "block_snapshot", "block['page'] = 2"),
        ("question_freeze_binding", "_source_options", "binding.execute(None)"),
        ("question_freeze_binding", "resolve_question_bindings", "plan = globals()"),
        ("question_freeze_binding", "question_bound_options", "binding.__dict__"),
        ("pipeline_split_binding", "initialize_split_binding", "alias = state"),
        ("pipeline_split_binding", "initialize_split_binding", "state.namespace['db'] = None"),
        ("pipeline_split_binding", "execute_split_questions", "ports('open')('x')"),
        ("pipeline_split_binding", "execute_split_questions", "state.frozen_option_registry = {}"),
        ("pipeline_split_binding", "execute_split_questions", "return state"),
    ],
)
def test_actual_helpers_reject_io_namespace_and_capability_escape(role, function, statement):
    tree = ast.parse((FEATURES / f"{role}.py").read_text())
    target = next(n for n in tree.body if getattr(n, "name", "") == function)
    target.body[:0] = ast.parse(statement).body
    with pytest.raises(AssertionError):
        inspect_pure_helper(ast.unparse(tree), role)


@pytest.mark.parametrize("mutation", ["remove", "late", "wrong_source", "outside_loop"])
def test_actual_builder_rejects_capture_point_mutations(mutation):
    tree = ast.parse((FEATURES / "document_ir_builder.py").read_text())
    function = next(n for n in tree.body if getattr(n, "name", "") == "blocks_to_document_ir")
    parents = {c: n for n in ast.walk(function) for c in ast.iter_child_nodes(n)}
    record = next(
        n
        for n in ast.walk(function)
        if isinstance(n, ast.Call) and call_name(n.func) == "record_region_source"
    )
    if mutation == "wrong_source":
        record.args[1] = ast.Subscript(
            value=ast.Name(id="blocks", ctx=ast.Load()), slice=ast.Constant(value=0), ctx=ast.Load()
        )
    elif mutation == "late":
        begin = next(
            n
            for n in function.body
            if isinstance(n, ast.Expr)
            and isinstance(n.value, ast.Call)
            and call_name(n.value.func) == "begin_source_capture"
        )
        function.body.remove(begin)
        function.body.insert(-1, begin)
    else:
        statement = parents[record]
        parents[statement].body.remove(statement)
        if mutation == "outside_loop":
            function.body.insert(-2, statement)
    with pytest.raises(AssertionError):
        inspect_capture(ast.parse(ast.unparse(tree)))


@pytest.mark.parametrize("mutation", ["clear", "legacy_plan", "recapture"])
def test_actual_ir_route_rejects_legacy_injection_regressions(mutation):
    tree = ast.parse((FEATURES / "pipeline_split_binding.py").read_text())
    function = next(n for n in tree.body if getattr(n, "name", "") == "initialize_split_binding")
    if mutation == "clear":
        for node in function.body:
            if isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) == (
                "state.frozen_option_registry"
            ):
                node.value = ast.parse("{'1:0': {'A': 'stale'}}", mode="eval").body
    elif mutation == "legacy_plan":
        selector = next(n for n in tree.body if getattr(n, "name", "") == "_uses_ir_binding")
        selector.body = ast.parse("return False").body
    else:
        execute = next(n for n in tree.body if getattr(n, "name", "") == "execute_split_questions")
        execute.body += ast.parse("state.frozen_option_registry = {'1:0': {'A': 'stale'}}").body
    namespace = {}
    exec(compile(ast.fix_missing_locations(tree), "<binding-boundary-mutant>", "exec"), namespace)
    with pytest.raises(AssertionError):
        assert_ir_cannot_apply(namespace)


def test_binding_helpers_and_gates_keep_budgets():
    for name in ("ir_freeze_binding_boundary_policy.py", "test_ir_freeze_binding_boundaries.py"):
        bounded(Path(__file__).with_name(name).read_text())


def test_fresh_import_cannot_attempt_runtime_dependencies(tmp_path):
    probe = """
import importlib, sys
attempts = []
blocked = ('app.core', 'app.services', 'app.features.pipeline_orchestrator',
           'app.features.question_splitter', 'app.features.pipeline_stages',
           'sqlalchemy', 'redis', 'httpx', 'fitz', 'paddleocr')
class Guard:
    def find_spec(self, name, path=None, target=None):
        if name.startswith('app.features.ocr') or any(
            name == p or name.startswith(p + '.') for p in blocked
        ):
            attempts.append(name)
            raise AssertionError(name)
sys.meta_path.insert(0, Guard())
for name in ('freeze_source_binding', 'question_freeze_binding', 'pipeline_split_binding'):
    importlib.import_module('app.features.' + name)
assert not attempts, attempts
assert not any(n == p or n.startswith(p + '.') for n in sys.modules for p in blocked)
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", probe],
        cwd=FEATURES.parents[1],
        env={"PATH": os.defpath, "HOME": str(tmp_path), "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
