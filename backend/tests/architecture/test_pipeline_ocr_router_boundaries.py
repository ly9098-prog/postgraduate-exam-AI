"""OCR correction keeps captured budget imports and bounded orchestration helpers."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
FEATURES = APP / "features"
FILES = {
    "state",
    "config",
    "classification",
    "execution",
    "candidates",
    "quality",
    "publication",
    "results",
    "output",
    "stage",
}
IMPORTS = {
    "__future__": {"annotations"},
    "collections.abc": {"Callable"},
    "typing": {"Any"},
    "functools": {"partial"},
    "dataclasses": {"dataclass", "field"},
    "types": {"SimpleNamespace"},
    "app.features.pipeline_ocr_router_state": {
        "RouterStageState",
        "RouterCandidate",
        "resolve_router_port",
    },
    "app.services.model_config_resolver": {
        "AICapability",
        "AIModelConfigResolver",
    },
    "app.services.admin_ai_config_service": {"get_all_configs"},
    "app.features.pipeline_ocr_router_classification": {
        "initialize_router_state",
        "classify_router_candidates",
    },
    "app.features.pipeline_ocr_router_execution": {"execute_router_candidates"},
    "app.features.pipeline_ocr_router_candidates": {
        "project_candidate_metadata",
        "record_failed_candidate",
        "record_unchanged_candidate",
    },
    "app.features.pipeline_ocr_router_quality": {"observe_domain_quality"},
    "app.features.pipeline_ocr_router_publication": {"publish_evaluation"},
    "app.features.pipeline_ocr_router_results": {"process_router_results"},
    "app.features.pipeline_ocr_router_output": {
        "filter_corrected_blocks",
        "finish_router_stage",
    },
    "app.features.token_budget": {
        "check_token_limit",
        "record_token_usage",
        "estimate_tokens",
    },
    "app.features.ocr_fix.metrics": {"OcrCorrectionMetrics"},
    "app.features.ocr_fix.router": {"OCRFixRouter"},
    "app.features.candidate_evaluator": {"CandidateDecision", "get_evaluator"},
    "app.features.quality_gate": {
        "CompositeQualityGate",
        "QualityContext",
        "record_shadow_decision",
    },
}
ALIASES = {
    ("types", "SimpleNamespace"): "_FixResult",
    ("app.features.token_budget", "estimate_tokens"): "_est",
    ("app.features.quality_gate", "QualityContext"): "QGateContext",
    ("app.features.quality_gate", "record_shadow_decision"): "_record_qgate",
}
PORTS = {
    "len",
    "enumerate",
    "str",
    "_detect_noise",
    "_detect_structure_abnormal",
    "bool",
    "_should_correct",
    "round",
    "asyncio",
    "logger",
    "safe_text_preview",
    "re",
    "getattr",
    "int",
    "zip",
    "isinstance",
    "BaseException",
    "_safe_text_summary",
    "dict",
    "_get_domain_quality_gate_mode",
    "Exception",
    "ValueError",
    "logger",
    "_filter_sensitive",
    "sorted",
}
HELPERS = {
    "initialize_router_state",
    "classify_router_candidates",
    "execute_router_candidates",
    "request_router_fix",
    "record_router_usage",
    "record_failed_candidate",
    "project_candidate_metadata",
    "record_unchanged_candidate",
    "evaluate_router_candidate",
    "observe_domain_quality",
    "publish_evaluation",
    "publish_accepted_candidate",
    "publish_rejected_candidate",
    "process_router_candidate",
    "process_router_results",
    "filter_corrected_blocks",
    "finish_router_stage",
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
            "resolve_router_port",
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


def inspect_router_module(source):
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
        if isinstance(node, ast.Name) and node.id in {"ports", "resolve_router_port"}:
            inspect_port_use(node, parents)
        if isinstance(node, ast.Import):
            assert False, "use explicit bounded imports"
        if isinstance(node, ast.ImportFrom):
            assert not node.level and node.module in IMPORTS
            assert all(
                alias.name in IMPORTS[node.module]
                and alias.asname == ALIASES.get((node.module, alias.name))
                for alias in node.names
            )
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", "")
            assert name not in {"open", "eval", "exec", "__import__"}
            if getattr(node.func, "attr", "") == "flush":
                assert ast.unparse(node.func.value) == "state.metrics"
            assert getattr(node.func, "attr", "") not in {
                "execute",
                "commit",
                "rollback",
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


def test_router_modules_have_complete_scan_bounded_functions_and_dependencies():
    actual = {
        p.stem.removeprefix("pipeline_ocr_router_")
        for p in FEATURES.glob("pipeline_ocr_router_*.py")
    }
    assert actual == FILES
    for name in FILES:
        functions = inspect_router_module(
            (FEATURES / f"pipeline_ocr_router_{name}.py").read_text(),
        )
        assert functions, name


def test_original_router_entry_keeps_async_signature_and_only_delegates():
    source = (FEATURES / "pipeline_orchestrator.py").read_text()
    entry = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_run_ocr_correction_router"
    )
    assert entry.end_lineno - entry.lineno + 1 <= 50
    assert [arg.arg for arg in entry.args.args] == [
        "self",
        "normalized_blocks",
        "opts",
        "db",
    ]
    assert entry.args.kwarg.arg == "_kw"
    assert len(entry.body) == 2 and isinstance(entry.body[1], ast.Return)
    assert isinstance(entry.body[1].value, ast.Await)
    assert entry.body[1].value.value.func.id == "run_ocr_router_stage"


@pytest.mark.parametrize(
    "source",
    [
        "def split():\n    pass\n" + "\n" * 299,
        "def split():\n    def inner():\n" + "        pass\n" * 51,
        "from app.core import config\n",
        "from app.features.pipeline_orchestrator import ImportPipeline\n",
        "from .pipeline_ocr_router_state import RouterStageState\n",
        "from app.features.pipeline_ocr_router_state import runtime\n",
        "def split(db):\n    return db.commit()\n",
        "def split(db):\n    return db.flush()\n",
        "def split():\n    return open('payload').read()\n",
        "def split():\n    return __import__('socket')\n",
        "def split(ports):\n    return ports('create_outbox')()\n",
        "def split(ports, name):\n    return ports(name)()\n",
        "def split(ports):\n    runtime = ports\n    return runtime('create_outbox')()\n",
        "def split(namespace):\n    return resolve_router_port(namespace, 'open')('payload')\n",
        "def split(ports):\n    return arbitrary(ports=ports)\n",
        "resolver = resolve_router_port\n",
        "value = (lambda: (\n" + "    1,\n" * 100 + "))\n",
        "from app.features.token_budget import estimate_tokens as runtime\n",
    ],
)
def test_router_gate_rejects_budget_runtime_and_dynamic_dependency_mutations(source):
    with pytest.raises(AssertionError):
        inspect_router_module(source)


def test_fresh_router_import_does_not_initialize_orchestrator_ocr_or_runtime():
    probe = """
import sys
from app.features.pipeline_ocr_router_stage import run_ocr_router_stage
assert callable(run_ocr_router_stage)
for name in (
    'app.features.pipeline_orchestrator', 'app.core.config', 'app.core.database',
    'app.features.ocr_fix.router', 'app.features.ocr_fix.metrics',
    'app.features.candidate_evaluator', 'app.features.quality_gate', 'app.features.token_budget',
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
