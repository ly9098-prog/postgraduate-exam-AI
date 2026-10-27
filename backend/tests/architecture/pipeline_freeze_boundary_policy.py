"""Explicit capabilities of synchronous structure-freeze responsibilities."""

import ast


def normalized(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            if node.body and isinstance(node.body[0], ast.Expr):
                if isinstance(node.body[0].value, ast.Constant):
                    if isinstance(node.body[0].value.value, str):
                        node.body.pop(0)
    return ast.dump(tree, include_attributes=False)


def bounded(source):
    assert len(source.splitlines()) <= 300
    tree = ast.parse(source, feature_version=(3, 11))
    for node in ast.walk(tree):
        assert not isinstance(node, (ast.AsyncFunctionDef, ast.Await, ast.Lambda))
        if isinstance(node, ast.FunctionDef):
            assert node.end_lineno - node.lineno + 1 <= 50
    return tree


FUNCTIONS = {
    "orchestration": {"run_structure_freeze_mode", "_load_freeze_inputs", "_attempt_ir_freeze"},
    "projection": {
        "project_ir_freeze",
        "_project_empty_ir",
        "project_canary_fallback",
        "project_canary_success",
    },
    "canary": {"project_canary_freeze"},
    "dual": {"project_dual_freeze"},
}

# Readable fields, writable fields, live ports, and local assignment names.
POLICY = {
    "run_structure_freeze_mode": (
        "mode legacy_result doc_ir",
        "doc_ir",
        "_get_blocks_document_ir logger",
        "state",
    ),
    "_load_freeze_inputs": (
        "mode legacy_result legacy_registry",
        "mode legacy_result legacy_registry",
        "_get_structure_freeze_mode run_structure_freeze_stage",
        "state",
    ),
    "_attempt_ir_freeze": (
        "doc_ir ir_to_legacy ir_result ir_registry_raw",
        "ir_to_legacy ir_result ir_registry_raw",
        "Exception logger",
        "exc",
    ),
    "project_ir_freeze": (
        "ir_registry_raw ir_result legacy_result",
        "",
        "dict list",
        "legacy_compat",
    ),
    "_project_empty_ir": (
        "legacy_result ir_result",
        "",
        "logger dict list",
        "result ir_warns",
    ),
    "project_canary_fallback": (
        "legacy_result ir_result",
        "",
        "logger dict list",
        "result",
    ),
    "project_canary_success": (
        "converter ir_registry_raw ir_result legacy_result",
        "",
        "dict list",
        "legacy_compat",
    ),
    "project_canary_freeze": (
        "doc_ir legacy_result legacy_registry ir_result ir_registry_raw",
        "",
        "logger _compare_freeze_results bool any",
        "comparison should_fallback failover_reasons w",
    ),
    "project_dual_freeze": (
        "legacy_result legacy_registry ir_result ir_registry_raw",
        "",
        "_compare_freeze_results logger dict",
        "comparison diff result",
    ),
}

PREFIX = "app.features.pipeline_freeze_"
MODULE_IMPORTS = {
    "orchestration": {
        (PREFIX + "state", "FreezeState", None),
        (PREFIX + "canary", "project_canary_freeze", None),
        (PREFIX + "dual", "project_dual_freeze", None),
        (PREFIX + "projection", "project_ir_freeze", None),
    },
    "projection": {(PREFIX + "state", "FreezeState", None), ("typing", "Any", None)},
    "canary": {
        (PREFIX + "state", "FreezeState", None),
        (PREFIX + "projection", "project_canary_fallback", None),
        (PREFIX + "projection", "project_canary_success", None),
    },
    "dual": {(PREFIX + "state", "FreezeState", None)},
}
STAGE = "app.features.pipeline_stages.structure_freeze_stage"
LAZY_IMPORTS = {
    "_attempt_ir_freeze": {
        (STAGE, "freeze_from_document_ir", "_ir_freeze"),
        (STAGE, "freeze_registry_to_block_format", "_ir_to_legacy"),
    },
    "project_ir_freeze": {
        (STAGE, "_freeze_deep_freeze", None),
        (STAGE, "freeze_registry_to_block_format", "_ir_to_legacy"),
    },
    "project_canary_success": {(STAGE, "_freeze_deep_freeze", None)},
    "project_canary_freeze": {
        ("app.features.ocr_canary", name, None)
        for name in (
            "check_ir_canary_failover",
            "is_canary_globally_disabled",
            "is_ir_canary_disabled",
        )
    },
}
RESULT_KEYS = {
    "warnings",
    "freeze_mode",
    "freeze_ir_warnings",
    "freeze_ir_empty",
    "freeze_canary_fallback",
    "freeze_canary_fallback_reasons",
    "freeze_dual_diagnostics",
}
ENTRY = """
def _run_structure_freeze(self, normalized_blocks: list[dict], **_kw) -> dict:
    return run_structure_freeze_mode(normalized_blocks, namespace=globals())
"""
INJECTIONS = [
    ("projection", "project_canary_success", "state.ir_to_legacy(state.ir_registry_raw)"),
    ("projection", "project_ir_freeze", "state.namespace['x'] = 1"),
    ("projection", "project_ir_freeze", "alias = state"),
    ("projection", "project_ir_freeze", "state.legacy_result = {}"),
    ("projection", "project_ir_freeze", "state.port('open')('x')"),
    ("projection", "project_ir_freeze", "state.port(name)()"),
    ("projection", "project_ir_freeze", "state.port('logger').warning('x')"),
    ("projection", "project_ir_freeze", "state.legacy_result.execute(None)"),
    ("projection", "project_ir_freeze", "state.__dict__['namespace']"),
    ("projection", "project_ir_freeze", "del state.ir_registry_raw"),
    ("projection", "project_ir_freeze", "project_canary_success(state, {})"),
    ("projection", "_project_empty_ir", "result = state.legacy_result"),
    ("projection", "_project_empty_ir", "result['db'] = state.legacy_result"),
    ("orchestration", "_load_freeze_inputs", "namespace['db'] = None"),
    ("orchestration", "_attempt_ir_freeze", "alias = _ir_freeze"),
    ("dual", "project_dual_freeze", "comparison.commit()"),
    ("canary", "project_canary_freeze", "any([])"),
    (
        "canary",
        "project_canary_freeze",
        "from app.features.pipeline_freeze_state import FreezeState\nFreezeState(None)",
    ),
    ("canary", "project_canary_freeze", "state.port = None"),
]
STATE = """
from __future__ import annotations
from builtins import NameError as _NameError
from builtins import UnboundLocalError as _UnboundLocalError
from builtins import __dict__ as _bound_builtins
from dataclasses import dataclass, field
from typing import Any
@dataclass
class FreezeState:
    namespace: dict
    mode: Any
    legacy_result: Any
    legacy_registry: Any
    doc_ir: Any
    ir_result: Any = field(default_factory=dict)
    ir_registry_raw: Any = field(default_factory=dict)
    ir_to_legacy: Any = field(init=False)
    def converter(self) -> Any:
        if "ir_to_legacy" not in self.__dict__:
            raise _UnboundLocalError(
                "cannot access local variable '_ir_to_legacy' "
                "where it is not associated with a value"
            )
        return self.ir_to_legacy
    def port(self, name: str) -> Any:
        if name in self.namespace:
            return self.namespace[name]
        if name in _bound_builtins:
            return _bound_builtins[name]
        raise _NameError(f"name '{name}' is not defined", name=name)
"""

CALLS = {
    "run_structure_freeze_mode": {
        "_attempt_ir_freeze",
        "_load_freeze_inputs",
        "project_canary_freeze",
        "project_dual_freeze",
        "project_ir_freeze",
        "state.port",
        "state.port('_get_blocks_document_ir')",
        "state.port('logger').warning",
    },
    "_load_freeze_inputs": {
        "FreezeState",
        "state.legacy_result.get",
        "state.port",
        "state.port('_get_structure_freeze_mode')",
        "state.port('run_structure_freeze_stage')",
    },
    "_attempt_ir_freeze": {
        "_ir_freeze",
        "state.ir_result.get",
        "state.port",
        "state.port('logger').warning",
    },
    "project_ir_freeze": {
        "_freeze_deep_freeze",
        "_ir_to_legacy",
        "_project_empty_ir",
        "state.ir_result.get",
        "state.legacy_result.get",
        "state.port",
        "state.port('dict').fromkeys",
        "state.port('list')",
    },
    "_project_empty_ir": {
        "result.get",
        "state.ir_result.get",
        "state.port",
        "state.port('dict')",
        "state.port('dict').fromkeys",
        "state.port('list')",
        "state.port('logger').warning",
    },
    "project_canary_fallback": {
        "result.get",
        "state.ir_result.get",
        "state.port",
        "state.port('dict').fromkeys",
        "state.port('list')",
        "state.port('logger').warning",
    },
    "project_canary_success": {
        "_freeze_deep_freeze",
        "state.ir_result.get",
        "state.converter",
        "state.converter()",
        "state.legacy_result.get",
        "state.port",
        "state.port('dict').fromkeys",
        "state.port('list')",
    },
    "project_canary_freeze": {
        "check_ir_canary_failover",
        "comparison.get",
        "is_canary_globally_disabled",
        "is_ir_canary_disabled",
        "project_canary_fallback",
        "project_canary_success",
        "state.ir_result.get",
        "state.port",
        "state.port('_compare_freeze_results')",
        "state.port('any')",
        "state.port('bool')",
        "state.port('logger').info",
        "w.startswith",
    },
    "project_dual_freeze": {
        "diff.get",
        "state.ir_result.get",
        "state.port",
        "state.port('_compare_freeze_results')",
        "state.port('dict')",
        "state.port('logger').info",
    },
}
