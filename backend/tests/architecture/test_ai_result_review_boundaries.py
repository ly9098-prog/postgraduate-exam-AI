"""Result review is an in-process dispatcher without resource ownership."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "app/services/ai/analysis_result_review.py"
CALLS = {
    "review_analysis_result": {
        "result.get", "parse_content", "validate_content", "build_usage",
        "reconcile_visual_evidence", "VisualValidationRequest", "_make_review",
    },
    "_make_review": {"ReviewedAnalysis", "detect_visual_ack_failure"},
    "resolve_analysis_outcome": {
        "_OutcomeArguments", "_resolve_early_outcome", "_resolve_grounded_outcome",
    },
    "_resolve_early_outcome": {
        "visual_ack_failure", "parse_failed_response", "arguments.logger.info",
    },
    "_resolve_grounded_outcome": {"arguments.grounding_repair", "arguments.valid_outcome"},
}
LOCALS = {
    "review_analysis_result": {"result", "raw_content", "parsed", "parsed_valid", "usage", "grounding"},
    "_make_review": set(),
    "resolve_analysis_outcome": {"arguments", "handled", "response"},
    "_resolve_early_outcome": {"response"},
    "_resolve_grounded_outcome": set(),
}
IMPORTS = {
    "__future__": {"annotations"},
    "collections.abc": {"Awaitable", "Callable"},
    "dataclasses": {"dataclass"}, "logging": {"Logger"}, "typing": {"Any"},
    "sqlalchemy.ext.asyncio": {"AsyncSession"},
    "app.services.ai.analysis_outcomes": {"VisualAckFailure", "detect_visual_ack_failure"},
    "app.services.ai.analysis_responses": {"parse_failed_response"},
    "app.services.ai.analysis_validation": {
        "AnalysisUsage", "GroundingValidation", "VisualValidationRequest", "reconcile_visual_evidence",
    },
    "app.services.ai.provider_invocation": {"ProviderInvocationResult"},
}
RECORDS = {
    "ReviewedAnalysis": ["parsed", "parsed_valid", "usage", "grounding", "ack_failure"],
    "_OutcomeArguments": [
        "db", "wrong_question", "user_id", "context", "result", "image_data_urls",
        "input_signature", "model_signature", "expected_answer_check", "effective_force",
        "runtime", "visual_evidence_is_valid", "max_tokens", "logger", "grounding_repair",
        "valid_outcome",
    ],
}
SIGNATURES = ast.parse("""
async def review_analysis_result(
    invocation: ProviderInvocationResult, *, image_data_urls: list[str],
    wrong_question_id: int, chat: Callable[..., Awaitable[Any]],
    expected_answer_check: Any, answer_grounding: Any,
    parse_content: Callable[[str], dict], validate_content: Callable[[dict], bool],
    extract_evidence: Callable[[str], str], build_usage: Callable[..., AnalysisUsage],
    validate_answer_check: Callable[[str, Any], tuple[bool, str, Any]],
    diagnosis_contradicts_grounding: Callable[[str, Any], tuple[bool, str | None]],
    evidence_is_valid: Callable[[str], bool], should_retry_visual_ack: Callable[..., bool],
    retry_visual_ack: Callable[..., Awaitable[Any]],
) -> ReviewedAnalysis: pass
async def resolve_analysis_outcome(
    db: AsyncSession, review: ReviewedAnalysis, *, wrong_question: Any, user_id: int,
    context: dict, result: dict, image_data_urls: list[str], input_signature: str,
    model_signature: str, expected_answer_check: Any, effective_force: bool, runtime: Any,
    visual_evidence_is_valid: Callable[[str], bool], max_tokens: int, logger: Logger,
    visual_ack_failure: Callable[..., dict], grounding_repair: Callable[..., Awaitable[dict]],
    valid_outcome: Callable[..., Awaitable[dict]],
) -> dict: pass
def _make_review(
    parsed: dict, parsed_valid: bool, usage: AnalysisUsage, grounding: GroundingValidation,
    image_data_urls: list[str], evidence_is_valid: Callable[[str], bool],
) -> ReviewedAnalysis: pass
def _resolve_early_outcome(
    review: ReviewedAnalysis, arguments: _OutcomeArguments, image_data_urls: list[str],
    visual_ack_failure: Callable[..., dict],
) -> tuple[bool, dict | None]: pass
async def _resolve_grounded_outcome(
    review: ReviewedAnalysis, arguments: _OutcomeArguments,
) -> dict: pass
""")
SIGNATURES = {node.name: node for node in SIGNATURES.body}


def check_function(node):
    assert node.name in CALLS, "unexpected responsibility"
    assert node.end_lineno - node.lineno + 1 <= 50, "function budget"
    calls = [child for child in ast.walk(node) if isinstance(child, ast.Call)]
    assert {ast.unparse(call.func) for call in calls} <= CALLS[node.name], "call capability"
    for child in ast.walk(node):
        assert child is node or not isinstance(child, (
            ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
        )), "nested binding"
        if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
            assert child.id in LOCALS[node.name], "local binding"
        elif isinstance(child, (ast.Attribute, ast.Subscript)):
            assert not isinstance(child.ctx, (ast.Store, ast.Del)), "external write"
        assert not isinstance(child, (
            ast.Try, ast.TryStar, ast.With, ast.AsyncWith, ast.For, ast.AsyncFor, ast.While,
            ast.Import, ast.ImportFrom, ast.Match, ast.Global, ast.Nonlocal,
        )), "resource or exception ownership"
    for call in calls:
        if ast.unparse(call.func) == "_OutcomeArguments":
            assert not call.args, "raw argument references"
            assert [field.arg for field in call.keywords] == RECORDS["_OutcomeArguments"], (
                "raw argument references"
            )
            assert all(
                isinstance(field.value, ast.Name) and field.value.id == field.arg
                for field in call.keywords
            ), "raw argument references"
    expected = SIGNATURES[node.name]
    assert type(node) is type(expected), "async signature"
    assert ast.dump(node.args) == ast.dump(expected.args), "signature"
    assert ast.dump(node.returns) == ast.dump(expected.returns), "return annotation"


def check_record(node):
    assert node.name in RECORDS, "record responsibility"
    assert [ast.unparse(item) for item in node.decorator_list] == ["dataclass(slots=True)"]
    assert all(
        not isinstance(child, ast.Expr)
        or (isinstance(child.value, ast.Constant) and isinstance(child.value.value, str))
        for child in node.body
    ), "record effect"
    fields = [child for child in node.body if not isinstance(child, ast.Expr)]
    assert all(
        isinstance(field, ast.AnnAssign) and isinstance(field.target, ast.Name)
        and field.value is None for field in fields
    ), "record must only store raw inputs"
    assert [field.target.id for field in fields] == RECORDS[node.name], "record fields"


def check_source(source):
    tree = ast.parse(source, feature_version=(3, 11))
    assert len(source.splitlines()) <= 300, "file budget"
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            check_function(node)
        elif isinstance(node, ast.ClassDef):
            check_record(node)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 and node.module in IMPORTS, "dependency"
            assert all(
                alias.name in IMPORTS[node.module] and alias.asname is None
                for alias in node.names
            ), "dependency alias"
        else:
            assert isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant), "module effect"


def test_result_review_budget_signature_raw_capture_and_dependency_boundaries():
    source = SOURCE.read_text()
    check_source(source)
    definitions = [
        node.name for node in ast.parse(source).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    assert sorted(definitions) == sorted([*CALLS, *RECORDS])


@pytest.mark.parametrize("source,reason", [
    ("import subprocess", "module effect"),
    ("from sqlalchemy.ext.asyncio import AsyncSession as valid_outcome", "dependency alias"),
    ("async def _resolve_grounded_outcome(review, arguments):\n    await arguments.db.commit()",
     "call capability"),
    ("def _make_review():\n    ReviewedAnalysis = db.commit\n    return ReviewedAnalysis()",
     "local binding"),
    ("async def review_analysis_result(invocation):\n"
     "    def parse_content(*args, **kwargs): return None", "nested binding"),
    ("async def review_analysis_result(invocation):\n"
     "    class parse_content: pass", "nested binding"),
    ("def _resolve_early_outcome(review):\n    review.parsed = {}", "external write"),
    ("async def review_analysis_result(invocation):\n    pass", "signature"),
    ("def resolve_analysis_outcome():\n    pass", "async signature"),
    ("async def _resolve_grounded_outcome(review, arguments):\n"
     "    try:\n        return None\n    except Exception:\n        return {}",
     "resource or exception ownership"),
    ("def _make_review():\n" + "    pass\n" * 51, "function budget"),
    ("\n" * 301, "file budget"),
])
def test_boundary_negative_controls(source, reason):
    with pytest.raises(AssertionError, match=reason):
        check_source(source)


def test_constructor_rejects_copying_raw_visual_inputs():
    source = SOURCE.read_text()
    replacement = source.replace(
        "image_data_urls=image_data_urls,\n        input_signature=input_signature,",
        "image_data_urls=[*image_data_urls],\n        input_signature=input_signature,",
    )
    assert replacement != source
    with pytest.raises(AssertionError, match="raw argument references"):
        check_source(replacement)


def test_fresh_import_does_not_initialize_model_database_or_worker():
    script = """
import importlib, sys
importlib.import_module("app.services.ai.analysis_result_review")
for name in ("app.worker_main", "app.services.ai_service", "app.core.database"):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=SOURCE.parents[3],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
