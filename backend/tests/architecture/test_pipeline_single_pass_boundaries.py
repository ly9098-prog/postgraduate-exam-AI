"""Single-pass preparation, restoration and execution keep bounded dependencies."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
FEATURES = APP / "features"
FILES = {"state", "input", "checkpoint", "execution", "loop", "result", "stage"}
IMPORTS = {
    "__future__": {"annotations"},
    "collections.abc": {"Callable"},
    "typing": {"Any"},
    "functools": {"partial"},
    "dataclasses": {"dataclass", "field"},
    "app.features.pipeline_single_pass_state": {
        "SinglePassState",
        "SinglePassRequest",
        "resolve_pass_port",
    },
    "app.features.pipeline_single_pass_input": {
        "begin_single_pass",
        "resolve_pass_vision",
        "prepare_pass_data",
    },
    "app.features.pipeline_single_pass_checkpoint": {
        "initialize_pass_checkpoint",
        "restore_pass_artifacts",
        "checkpoint_completed_stage",
        "checkpoint_failed_stage",
        "finalize_pass_checkpoint",
    },
    "app.features.pipeline_single_pass_execution": {"execute_pass_stage"},
    "app.features.pipeline_single_pass_loop": {"execute_pass_loop"},
    "app.features.pipeline_single_pass_result": {"finish_single_pass"},
    "app.services.model_config_resolver": {"resolve_active_model"},
}
PORTS = {
    "logging",
    "time",
    "log_event",
    "logger",
    "Exception",
    "list",
    "len",
    "_write_stage_checkpoint",
    "set",
    "_restore_from_artifacts",
    "sorted",
    "isinstance",
    "dict",
    "_update_stage_metrics",
    "complete_stage_data",
    "_save_stage_artifact",
    "_clear_stage_checkpoint",
    "_save_completed_marker",
    "_save_failed_marker",
    "_build_stats",
    "_build_diagnostics",
    "serialize_utc_datetime",
    "utcnow",
    "_build_quality_report",
    "_log_routing_stability",
    "_list_artifacts",
    "round",
}
HELPERS = {
    "begin_single_pass",
    "resolve_pass_vision",
    "prepare_pass_data",
    "initialize_pass_checkpoint",
    "restore_pass_artifacts",
    "checkpoint_completed_stage",
    "checkpoint_failed_stage",
    "finalize_pass_checkpoint",
    "complete_pass_stage",
    "handle_stage_failure",
    "execute_pass_stage",
    "skip_pass_stage",
    "report_pass_progress",
    "execute_pass_loop",
    "project_pass_quality",
    "finish_single_pass",
}
SIGNATURE = """async def _run_single_pass(
    self, *, file_content: bytes | None, file_path: str | None,
    source_type: str, source_file: str, subject: str | None,
    subject_id: int | None = None, opts: dict, db, shared: dict,
    progress_callback, started_at: str, page_start: int | None = None,
    page_end: int | None = None, chunk_seen_hashes: set | None = None,
    chunk_logical_end: int | None = None, page_images: dict[int, bytes] | None = None,
    page_image_refs: dict[int, str] | None = None,
    pre_extracted_blocks: list[dict] | None = None,
    resume_from_checkpoint: dict | None = None,
) -> dict: pass
"""


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
            "resolve_pass_port",
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


def inspect_pass_module(source):
    assert len(source.splitlines()) <= 300
    tree = ast.parse(source, feature_version=(3, 11))
    parents = {
        child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)
    }
    functions = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            assert node.end_lineno - node.lineno + 1 <= 50
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append(node.name)
        if isinstance(node, ast.Name) and node.id in {"ports", "resolve_pass_port"}:
            inspect_port_use(node, parents)
        if isinstance(node, ast.Import):
            assert False, "use explicit bounded imports"
        if isinstance(node, ast.ImportFrom):
            assert not node.level and node.module in IMPORTS
            assert all(
                alias.name in IMPORTS[node.module] and alias.asname is None
                for alias in node.names
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


def test_pass_modules_have_complete_scan_bounded_functions_and_dependencies():
    actual = {
        p.stem.removeprefix("pipeline_single_pass_")
        for p in FEATURES.glob("pipeline_single_pass_*.py")
    }
    assert actual == FILES
    for name in FILES:
        functions = inspect_pass_module(
            (FEATURES / f"pipeline_single_pass_{name}.py").read_text(),
        )
        assert functions, name


def assert_pass_entry(entry):
    expected = ast.parse(SIGNATURE).body[0]
    assert entry.end_lineno - entry.lineno + 1 <= 50
    assert ast.dump(entry.args) == ast.dump(expected.args)
    assert ast.dump(entry.returns) == ast.dump(expected.returns)
    assert len(entry.body) == 2 and isinstance(entry.body[1], ast.Return)
    result = entry.body[1].value
    assert isinstance(result, ast.Await)
    assert ast.unparse(result.value) == (
        "run_single_pass(self, locals(), namespace=globals())"
    )


def test_original_pass_entry_keeps_full_keyword_signature_and_only_delegates():
    source = (FEATURES / "pipeline_orchestrator.py").read_text()
    entry = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_run_single_pass"
    )
    assert_pass_entry(entry)


@pytest.mark.parametrize("mutation", ["default", "name", "order"])
def test_pass_entry_gate_rejects_keyword_signature_mutations(mutation):
    entry = ast.parse(SIGNATURE).body[0]
    entry.body = [
        ast.Expr(value=ast.Constant(value="doc")),
        ast.parse(
            "return await run_single_pass(self, locals(), namespace=globals())"
        ).body[0],
    ]
    if mutation == "default":
        entry.args.kw_defaults[-4] = ast.Dict(keys=[], values=[])
    elif mutation == "name":
        entry.args.kwonlyargs[-4].arg = "images"
    else:
        entry.args.kwonlyargs[-4:-2] = reversed(entry.args.kwonlyargs[-4:-2])
    with pytest.raises(AssertionError):
        assert_pass_entry(entry)


@pytest.mark.parametrize(
    "source",
    [
        "def split():\n    pass\n" + "\n" * 299,
        "def split():\n    def inner():\n" + "        pass\n" * 51,
        "from app.core import config\n",
        "from app.features.pipeline_orchestrator import ImportPipeline\n",
        "from .pipeline_single_pass_state import RouterStageState\n",
        "from app.features.pipeline_single_pass_state import runtime\n",
        "def split(db):\n    return db.commit()\n",
        "def split(db):\n    return db.flush()\n",
        "def split():\n    return open('payload').read()\n",
        "def split():\n    return __import__('socket')\n",
        "def split(ports):\n    return ports('create_outbox')()\n",
        "def split(ports, name):\n    return ports(name)()\n",
        "def split(ports):\n    runtime = ports\n    return runtime('create_outbox')()\n",
        "def split(namespace):\n    return resolve_pass_port(namespace, 'open')('payload')\n",
        "def split(ports):\n    return arbitrary(ports=ports)\n",
        "resolver = resolve_pass_port\n",
        "value = (lambda: (\n" + "    1,\n" * 100 + "))\n",
        "from app.services.model_config_resolver import resolve_active_model as runtime\n",
    ],
)
def test_pass_gate_rejects_budget_runtime_and_dynamic_dependency_mutations(source):
    with pytest.raises(AssertionError):
        inspect_pass_module(source)


def test_fresh_pass_import_does_not_initialize_orchestrator_ocr_or_runtime():
    probe = """
import sys
from app.features.pipeline_single_pass_stage import run_single_pass
assert callable(run_single_pass)
for name in (
    'app.features.pipeline_orchestrator', 'app.core.config', 'app.core.database',
    'app.services.model_config_resolver', 'app.features.pipeline_stage_completion',
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
