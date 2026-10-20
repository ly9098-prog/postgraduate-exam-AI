"""Conservative static import graph; never imports application code."""

from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path

Graph = dict[str, set[str]]
Edge = tuple[str, str]


def application_sources(root: Path) -> dict[str, Path]:
    if not root.is_dir():
        raise ValueError(f"Application directory does not exist: {root}")
    sources = {}
    for path in sorted(root.rglob("*.py")):
        parts = path.relative_to(root.parent).with_suffix("").parts
        module = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
        sources[module] = path
    if not sources:
        raise ValueError(f"Application directory contains no Python sources: {root}")
    return sources


def _string_argument(call: ast.Call, name: str, index: int) -> str | None:
    value = call.args[index] if len(call.args) > index else next(
        (keyword.value for keyword in call.keywords if keyword.arg == name), None,
    )
    return value.value if isinstance(value, ast.Constant) and isinstance(value.value, str) else None


def _dynamic_import_names(tree: ast.AST) -> set[str]:
    modules = {"importlib"}
    functions = {"__import__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.asname or alias.name for alias in node.names
                           if alias.name == "importlib")
        elif isinstance(node, ast.ImportFrom) and node.module == "importlib":
            functions.update(alias.asname or alias.name for alias in node.names
                             if alias.name == "import_module")
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        direct = isinstance(func, ast.Name) and func.id in functions
        qualified = (isinstance(func, ast.Attribute) and func.attr == "import_module"
                     and isinstance(func.value, ast.Name) and func.value.id in modules)
        if not direct and not qualified:
            continue
        value = _string_argument(node, "name", 0)
        if value and value.startswith("."):
            package = _string_argument(node, "package", 1)
            if package:
                names.add(resolve_name(value, package))
        elif value:
            names.add(value)
    return names


def import_names(tree: ast.AST, package: str) -> set[str]:
    """Include local and type-checking imports; resolve relative from-imports."""
    names = _dynamic_import_names(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            name = node.module or ""
            if node.level:
                name = resolve_name("." * node.level + name, package)
            names.add(name)
            names.update(f"{name}.{alias.name}" for alias in node.names
                         if alias.name != "*")
    return names


def scan_application(root: Path) -> tuple[Graph, set[Edge]]:
    sources = application_sources(root)
    graph: Graph = {module: set() for module in sources}
    reverse_api_imports = set()
    for module, path in sources.items():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        package = module if path.name == "__init__.py" else module.rpartition(".")[0]
        names = import_names(tree, package)
        graph[module].update(name for name in names if name in sources and name != module)
        if module.startswith(("app.services.", "app.features.")) or module in {
            "app.services", "app.features",
        }:
            reverse_api_imports.update(
                (module, name) for name in names if name == "app.api" or name.startswith("app.api.")
            )
    return graph, reverse_api_imports


def cyclic_edges(graph: Graph) -> set[Edge]:
    """Return every edge within a strongly connected component."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    active: set[str] = set()
    result: set[Edge] = set()

    def visit(module: str) -> None:
        index[module] = low[module] = len(index)
        stack.append(module)
        active.add(module)
        for dependency in sorted(graph[module]):
            if dependency not in index:
                visit(dependency)
                low[module] = min(low[module], low[dependency])
            elif dependency in active:
                low[module] = min(low[module], index[dependency])
        if low[module] != index[module]:
            return
        component = set()
        while True:
            member = stack.pop()
            active.remove(member)
            component.add(member)
            if member == module:
                break
        result.update((member, dependency) for member in component
                      for dependency in graph[member] if dependency in component)

    for module in sorted(graph):
        if module not in index:
            visit(module)
    return result
