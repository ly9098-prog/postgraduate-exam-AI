"""Whole-backend import gates with injection tests for the scanner itself."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from tests.architecture.dependency_scan import (
    application_sources,
    cyclic_edges,
    import_names,
    scan_application,
)

APP = Path(__file__).resolve().parents[2] / "app"
BASELINE = Path(__file__).with_name("import_cycle_baseline.json")


def test_business_modules_do_not_import_api():
    graph, violations = scan_application(APP)
    assert "app.main" in graph
    assert not violations, f"Business modules must not depend on API: {sorted(violations)}"


def test_no_new_static_import_cycles():
    graph, _ = scan_application(APP)
    groups = json.loads(BASELINE.read_text(encoding="utf-8"))
    allowed = set()
    for group in groups:
        assert group["reason"].strip()
        for source, target in group["edges"]:
            assert (source, target) not in allowed, "Duplicate baseline edge"
            assert source in graph and target in graph, "Baseline references missing module"
            allowed.add((source, target))
    current = cyclic_edges(graph)
    assert not current - allowed, f"New cyclic imports: {sorted(current - allowed)}"
    assert not allowed - current, f"Remove resolved cycle baseline entries: {sorted(allowed - current)}"


@pytest.mark.parametrize("statement", [
    "from app.api.v1.auth import router",
    "from app import api",
    "import app.api.v1.auth as auth",
    "from ..api.v1 import auth",
    "def deferred():\n    from app.api.v1.auth import router",
    "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import app.api.v1.auth",
    "import importlib as loader\nloader.import_module('app.api.v1.auth')",
    "from importlib import import_module as load\nload('app.api.v1.auth')",
    "import importlib\nimportlib.import_module(name='app.api.v1.auth')",
    "import importlib\nimportlib.import_module('.api.v1.auth', package='app')",
    "__import__('app.api.v1.auth')",
])
def test_injected_reverse_import_is_detected(tmp_path, statement):
    root = tmp_path / "app"
    service = root / "services" / "example.py"
    service.parent.mkdir(parents=True)
    service.write_text(statement, encoding="utf-8")
    graph, violations = scan_application(root)
    assert "app.services.example" in graph
    assert any(source == "app.services.example" and target.startswith("app.api")
               for source, target in violations)


def test_relative_package_and_named_module_imports(tmp_path):
    root = tmp_path / "app"
    (root / "feature").mkdir(parents=True)
    (root / "feature" / "__init__.py").write_text("from . import rules\n")
    (root / "feature" / "rules.py").write_text("from .. import shared\n")
    (root / "shared.py").write_text("from .feature.rules import run\n")
    graph, violations = scan_application(root)
    assert graph["app.feature"] == {"app.feature.rules"}
    assert graph["app.feature.rules"] == {"app.shared"}
    assert graph["app.shared"] == {"app.feature.rules"}
    assert violations == set()
    assert cyclic_edges(graph) == {
        ("app.feature.rules", "app.shared"), ("app.shared", "app.feature.rules"),
    }


def test_cycles_include_all_internal_edges_but_not_acyclic_consumers():
    graph = {"a": {"b", "c"}, "b": {"a"}, "c": {"b"}, "consumer": {"a"}, "leaf": set()}
    assert cyclic_edges(graph) == {("a", "b"), ("a", "c"), ("b", "a"), ("c", "b")}
    graph["new"] = {"a"}
    assert ("new", "a") not in cyclic_edges(graph)
    graph["c"].add("new")
    assert {("new", "a"), ("c", "new")} <= cyclic_edges(graph)


@pytest.mark.parametrize("exists", [False, True])
def test_missing_or_empty_scope_is_not_a_green_scan(tmp_path, exists):
    root = tmp_path / "app"
    if exists:
        root.mkdir()
    with pytest.raises(ValueError):
        application_sources(root)


def test_invalid_python_is_not_silently_skipped(tmp_path):
    root = tmp_path / "app"
    root.mkdir()
    (root / "broken.py").write_text("def broken(")
    with pytest.raises(SyntaxError):
        scan_application(root)


def test_strings_and_external_imports_do_not_create_application_edges():
    tree = ast.parse("message = 'from app.api import auth'\nimport pathlib\n")
    assert import_names(tree, "app.services") == {"pathlib"}


def test_an_existing_cycle_does_not_allow_new_edges_or_modules():
    graph = {"a": {"b"}, "b": {"a"}, "new": set()}
    allowed = cyclic_edges(graph)
    graph["a"].add("new")
    graph["new"].add("b")
    assert cyclic_edges(graph) - allowed == {("a", "new"), ("new", "b")}
    graph["b"].clear()
    assert allowed - cyclic_edges(graph) == {("a", "b"), ("b", "a")}


def test_embedding_endpoint_rules_remain_independent_and_acyclic():
    source = (APP / "services" / "embedding_endpoints.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert import_names(tree, "app.services") == {"urllib.parse", "urllib.parse.urlparse"}
    assert len(source.splitlines()) <= 300
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50
    graph, _ = scan_application(APP)
    endpoint = "app.services.embedding_endpoints"
    assert endpoint in graph["app.services.embedding_service"]
    assert endpoint in graph["app.services.vector_config_service"]
    assert not graph[endpoint]
    assert not any(endpoint in edge for edge in cyclic_edges(graph))
