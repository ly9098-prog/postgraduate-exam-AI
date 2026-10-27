"""The split coordinator must not acquire persistence or runtime dependencies."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
FEATURES = APP / "features"
FILES = {
    "state",
    "input",
    "rebuild",
    "prose",
    "fallback",
    "overlap",
    "result",
    "stage",
    "binding",
}
IMPORTS = {
    "__future__": {"annotations"},
    "collections.abc": {"Callable"},
    "typing": {"Any"},
    "functools": {"partial"},
    "dataclasses": {"dataclass", "field"},
    "app.features.pipeline_split_state": {"SplitState", "resolve_split_port"},
    "app.features.pipeline_split_input": {
        "filter_split_layout",
        "initialize_split_input",
        "merge_split_pages",
        "resolve_split_options",
    },
    "app.features.pipeline_split_rebuild": {"rebuild_split_input"},
    "app.features.pipeline_split_binding": {
        "execute_split_questions",
        "initialize_split_binding",
        "finalize_split_binding",
    },
    "app.features.pipeline_split_prose": {
        "filter_book_pdf_prose",
        "record_book_pdf_prose_from_blocks",
    },
    "app.features.pipeline_split_fallback": {"resolve_split_fallback"},
    "app.features.pipeline_split_overlap": {"deduplicate_chunk_overlap"},
    "app.features.pipeline_split_result": {
        "finish_split_result",
        "initialize_split_diagnostics",
    },
    "app.features.visual_boundary_detector": {
        "filter_book_layout_blocks_from_ir",
        "detect_visual_boundaries_from_ir",
    },
    "app.features.question_splitter": {"split_by_visual_boundaries"},
}
PORTS = {
    "isinstance",
    "ImportMode",
    "str",
    "_merge_cross_page_blocks",
    "len",
    "any",
    "_get_blocks_document_ir",
    "Exception",
    "logger",
    "_remap_frozen_registry_vl_rebuild",
    "sum",
    "list",
    "getattr",
    "split_questions",
    "_safe_hash_preview",
    "_is_book_import_mode",
    "_looks_like_book_pdf_prose_candidate",
    "re",
    "_BOOK_PDF_QUESTION_SIGNAL_RE",
    "_BOOK_PDF_PROSE_MARKER_RE",
    "_BOOK_PDF_SENTENCE_END_RE",
    "int",
    "_visual_boundary_preview",
    "_compute_overlap_hash",
    "sorted",
    "set",
    "abs",
    "bool",
    "_log_multi_blank_stage",
    "_apply_frozen_options",
}
HELPERS = {
    "initialize_split_input",
    "merge_split_pages",
    "filter_split_layout",
    "resolve_split_options",
    "rebuild_split_input",
    "initialize_split_diagnostics",
    "filter_book_pdf_prose",
    "record_book_pdf_prose_from_blocks",
    "resolve_split_fallback",
    "deduplicate_chunk_overlap",
    "finish_split_result",
    "remap_vl_registry",
    "publish_vl_rebuild",
    "try_visual_split",
    "create_review_fallback",
    "warn_unclosed_boundary",
    "execute_split_questions",
}


def inspect_port_use(node, parents):
    parent = parents[node]
    if node.id == "ports":
        if isinstance(parent, ast.Call) and parent.func is node:
            return
        if isinstance(parent, ast.keyword) and parent.arg == "ports":
            caller = parents[parent]
            assert isinstance(caller, ast.Call)
            assert getattr(caller.func, "id", "") in HELPERS
            return
        assert isinstance(parent, ast.Assign) and parent.targets == [node]
        assert isinstance(parent.value, ast.Call)
        assert getattr(parent.value.func, "id", "") == "partial"
        assert [getattr(arg, "id", "") for arg in parent.value.args] == [
            "resolve_split_port",
            "namespace",
        ]
    else:
        assert isinstance(parent, ast.Call)
        assert getattr(parent.func, "id", "") == "partial"
        assert len(parent.args) == 2 and parent.args[0] is node
        assert getattr(parent.args[-1], "id", "") == "namespace"
        assignment = parents[parent]
        assert isinstance(assignment, ast.Assign)
        assert len(assignment.targets) == 1
        assert getattr(assignment.targets[0], "id", "") == "ports"


def inspect_split_module(source):
    assert len(source.splitlines()) <= 300
    tree = ast.parse(source, feature_version=(3, 11))
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    functions = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.Lambda)):
            assert node.end_lineno - node.lineno + 1 <= 50
            if isinstance(node, ast.FunctionDef):
                functions.append(node.name)
        if isinstance(node, ast.Name) and node.id in {"ports", "resolve_split_port"}:
            inspect_port_use(node, parents)
        assert not isinstance(node, (ast.AsyncFunctionDef, ast.Await))
        if isinstance(node, ast.Import):
            assert all(alias.name == "hashlib" for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert not node.level and node.module in IMPORTS
            assert all(
                alias.name in IMPORTS[node.module] and alias.asname is None for alias in node.names
            )
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", "")
            assert name not in {"open", "eval", "exec", "__import__"}
            assert getattr(node.func, "attr", "") not in {
                "execute",
                "commit",
                "rollback",
                "flush",
                "begin",
                "begin_nested",
                "read_text",
                "write_text",
                "read_bytes",
                "write_bytes",
                "connect",
                "socket",
                "request",
                "run",
                "Popen",
            }
            if name == "ports":
                assert len(node.args) == 1 and isinstance(node.args[0], ast.Constant)
                assert node.args[0].value in PORTS
    return functions


def test_split_modules_have_complete_scan_bounded_functions_and_dependencies():
    actual = {p.stem.removeprefix("pipeline_split_") for p in FEATURES.glob("pipeline_split_*.py")}
    assert actual == FILES
    for name in FILES:
        functions = inspect_split_module(
            (FEATURES / f"pipeline_split_{name}.py").read_text(),
        )
        assert functions, name


def test_original_split_entry_keeps_signature_docstring_and_only_delegates():
    source = (FEATURES / "pipeline_orchestrator.py").read_text()
    entry = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "_run_split"
    )
    assert entry.end_lineno - entry.lineno + 1 <= 50
    assert [arg.arg for arg in entry.args.args] == [
        "self",
        "normalized_blocks",
        "structure",
    ]
    assert entry.args.kwarg.arg == "_kw"
    assert ast.get_docstring(entry).startswith("Stage 4: split text blocks")
    assert len(entry.body) == 2 and isinstance(entry.body[1], ast.Return)
    assert entry.body[1].value.func.id == "run_split_stage"


@pytest.mark.parametrize(
    "source",
    [
        "def split():\n    pass\n" + "\n" * 299,
        "def split():\n    def inner():\n" + "        pass\n" * 51,
        "from app.core import config\n",
        "from app.features.pipeline_orchestrator import ImportPipeline\n",
        "from .pipeline_split_state import SplitState\n",
        "from app.features.pipeline_split_state import runtime\n",
        "def split(db):\n    return db.commit()\n",
        "def split():\n    return open('payload').read()\n",
        "def split():\n    return __import__('socket')\n",
        "def split(ports):\n    return ports('create_outbox')()\n",
        "def split(ports, name):\n    return ports(name)()\n",
        "def split(ports):\n    runtime = ports\n    return runtime('create_outbox')()\n",
        "def split(namespace):\n    return resolve_split_port(namespace, 'open')('payload')\n",
        "def split(ports):\n    return arbitrary(ports=ports)\n",
        "resolver = resolve_split_port\n",
        "value = (lambda: (\n" + "    1,\n" * 100 + "))\n",
        "async def split():\n    pass\n",
    ],
)
def test_split_gate_rejects_budget_runtime_and_dynamic_dependency_mutations(source):
    with pytest.raises(AssertionError):
        inspect_split_module(source)


def test_fresh_split_import_does_not_initialize_orchestrator_ocr_or_runtime():
    probe = """
import sys
from app.features.pipeline_split_stage import run_split_stage
assert callable(run_split_stage)
for name in (
    'app.features.pipeline_orchestrator', 'app.core.config', 'app.core.database',
    'app.features.visual_boundary_detector', 'app.features.question_splitter',
    'app.services.practice_service', 'sqlalchemy', 'redis', 'httpx',
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", probe],
        cwd=APP.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
