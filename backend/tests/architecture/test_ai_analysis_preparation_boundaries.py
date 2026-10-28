"""Preparation owns loading; orchestration owns the generation lease."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

AI = Path(__file__).resolve().parents[2] / "app/services/ai"
CALLS = {
    "prepare_analysis": {
        "_load_analysis_pair",
        "_guard_revision",
        "_guarded_return",
        "_visual_requirements",
        "_missing_visual_return",
        "_prepare_material_analysis",
    },
    "_guarded_return": {"_early_return"},
    "_missing_visual_return": {"_missing_visual_response", "_early_return"},
    "_prepare_material_analysis": {
        "_load_materials",
        "request.build_grounding",
        "getattr",
        "request.input_signature",
        "request.model_signature",
        "_initial_cache_response",
        "AnalysisPreparation",
        "bool",
    },
    "_load_analysis_pair": {
        "request.db.execute",
        "select",
        "select(WrongQuestion).where",
        "select(Question).where",
        "wq_result.scalar_one_or_none",
        "q_result.scalar_one_or_none",
        "ValueError",
    },
    "_guard_revision": {"request.revision_guard"},
    "_visual_requirements": {
        "request.collect_visual_sources",
        "bool",
        "request.has_visual_slot",
    },
    "_missing_visual_response": {
        "request.logger.info",
        "vision_input_missing_response",
    },
    "_load_materials": {
        "request.load_knowledge_points",
        "int",
        "knowledge_map.get",
        "request.load_runtime",
    },
    "_initial_cache_response": {
        "request.logger.info",
        "request.cached_response",
        "request.cache_age",
        "request.stale_reason",
        "((wrong_question.ai_analysis or {}).get('_meta') or {}).get",
        "(wrong_question.ai_analysis or {}).get",
    },
    "_early_return": {"AnalysisPreparation", "bool"},
    "execute_locked_analysis": {
        "begin_analysis_generation",
        "generation_in_progress_response",
        "_execute_with_lease",
        "finish_analysis_generation",
    },
    "_execute_with_lease": {
        "_review_cache",
        "_prepare_inputs",
        "_grounded_context",
        "_invoke_review",
        "_resolve_review_outcome",
    },
    "_grounded_context": set(),
    "_invoke_review": {"invoke_and_review_analysis"},
    "_resolve_review_outcome": {"resolve_reviewed_analysis_outcome"},
    "_review_cache": {"review_locked_analysis_cache"},
    "_prepare_inputs": {"prepare_locked_analysis_inputs"},
}
IMPORTS = {
    "__future__": {"annotations"},
    "collections.abc": {"Awaitable", "Callable"},
    "dataclasses": {"dataclass"},
    "logging": {"Logger"},
    "typing": {"Any"},
    "sqlalchemy": {"select"},
    "sqlalchemy.ext.asyncio": {"AsyncSession"},
    "app.models.question": {"Question"},
    "app.models.wrong_question": {"WrongQuestion"},
    "app.services.ai.analysis_responses": {
        "vision_input_missing_response",
        "generation_in_progress_response",
    },
    "app.services.ai.analysis_execution": {
        "AnalysisLease",
        "LockedAnalysisInputs",
        "LockedCacheReview",
        "begin_analysis_generation",
        "finish_analysis_generation",
        "prepare_locked_analysis_inputs",
        "review_locked_analysis_cache",
    },
    "app.services.ai.analysis_review_invocation": {
        "invoke_and_review_analysis",
        "resolve_reviewed_analysis_outcome",
    },
}
TRUSTED = {name for calls in CALLS.values() for name in calls if name.isidentifier()}
SIGNATURES = {
    "prepare_analysis": "request: AnalysisPreparationRequest",
    "execute_locked_analysis": "request: AnalysisOrchestrationRequest",
    "_execute_with_lease": "request: AnalysisOrchestrationRequest, lease: AnalysisLease",
}


def check_source(source):
    tree = ast.parse(source, feature_version=(3, 11))
    assert len(source.splitlines()) <= 300, "file budget"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            raise AssertionError("dependency")
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 and node.module in IMPORTS, "dependency"
            assert all(
                alias.name in IMPORTS[node.module] and alias.asname is None
                for alias in node.names
            ), "dependency alias"
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            assert node.id not in TRUSTED, "trusted binding"
        elif isinstance(node, ast.arg):
            assert node.arg not in TRUSTED, "trusted binding"
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50, "function budget"
            assert node.name in CALLS, "unexpected responsibility"
            calls = {
                ast.unparse(child.func)
                for child in ast.walk(node)
                if isinstance(child, ast.Call)
            }
            assert calls <= CALLS[node.name], "call capability"
            check_writes(node)
            if node.name in SIGNATURES:
                assert isinstance(node, ast.AsyncFunctionDef), "async contract"
                assert ast.unparse(node.args) == SIGNATURES[node.name], "signature"
                expected = (
                    "AnalysisPreparation" if node.name == "prepare_analysis" else "dict"
                )
                assert ast.unparse(node.returns) == expected, "return annotation"


def check_writes(function):
    for node in ast.walk(function):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise AssertionError("function dependency")
        if isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(
            node.ctx, (ast.Store, ast.Del)
        ):
            assert (
                function.name == "_grounded_context"
                and ast.unparse(node) == "context['answer_grounding']"
            ), "external write"


@pytest.mark.parametrize("module", ["analysis_preparation", "analysis_orchestration"])
def test_preparation_and_orchestration_budgets_and_dependencies(module):
    check_source((AI / (module + ".py")).read_text())


@pytest.mark.parametrize(
    "source,reason",
    [
        ("import subprocess", "dependency"),
        (
            "async def _prepare_inputs(request):\n    await request.db.commit()",
            "call capability",
        ),
        (
            "async def _review_cache(request):\n    await request.chat()",
            "call capability",
        ),
        (
            "async def _prepare_inputs(request):\n"
            "    prepare_locked_analysis_inputs = request.db.commit\n"
            "    return await prepare_locked_analysis_inputs()",
            "trusted binding",
        ),
        ("async def _review_cache(request):\n    request.db = None", "external write"),
        (
            "from sqlalchemy import select as prepare_locked_analysis_inputs",
            "dependency alias",
        ),
        ("def prepare_analysis(request):\n    pass", "async contract"),
        ("async def prepare_analysis(db):\n    pass", "signature"),
        (
            "async def prepare_analysis(request: AnalysisPreparationRequest) -> str:\n    pass",
            "return annotation",
        ),
        ("def new_query():\n    pass", "unexpected responsibility"),
        (
            "async def _prepare_inputs(request):\n" + "    pass\n" * 51,
            "function budget",
        ),
        ("\n" * 301, "file budget"),
    ],
)
def test_boundary_negative_controls(source, reason):
    with pytest.raises(AssertionError, match=reason):
        check_source(source)


def test_fresh_import_does_not_start_worker_model_or_database():
    script = """
import importlib
import sys
for name in ("analysis_preparation", "analysis_orchestration"):
    importlib.import_module("app.services.ai." + name)
for name in ("app.worker_main", "app.services.ai_service", "app.core.database"):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=AI.parents[2],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
