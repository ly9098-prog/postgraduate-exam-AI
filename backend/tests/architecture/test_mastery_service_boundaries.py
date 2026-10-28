"""Mastery-service ownership, budget and neutral-dependency gates."""

import ast
from pathlib import Path

import pytest

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"
MODULE = "app.services.mastery_service"
FILE = APP / "services/mastery_service.py"

FUNCTION_BUDGET = 50
# Frozen legacy ceiling: every future extraction must lower it, never raise it.
FILE_CEILING = 653

UPDATE_ENTRY = "update_user_knowledge_state_after_answer"
UPDATE_HELPERS = (
    "_empty_mastery_update_summary",
    "_load_version_knowledge_mappings",
    "_load_version_difficulty",
    "_ensure_knowledge_states",
    "_apply_answer_to_knowledge_state",
    "_apply_answer_to_mappings",
    "_build_mastery_update_summary",
)
PROJECTION_HELPERS = (
    "_load_weak_state_rows",
    "_weak_point_from_state",
    "_load_recent_practice_rows",
    "_aggregate_practice_rows",
    "_weak_point_from_practice_stats",
    "_load_knowledge_state_rows",
    "_load_subject_label_map",
    "_knowledge_state_view",
)


def _functions(source: str) -> dict[str, ast.AST]:
    return {
        node.name: node
        for node in ast.parse(source).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def budget_violations(source: str) -> list[str]:
    violations = []
    if len(source.splitlines()) > FILE_CEILING:
        violations.append(f"file exceeds frozen ceiling {FILE_CEILING}")
    for name, node in _functions(source).items():
        size = node.end_lineno - node.lineno + 1
        if size > FUNCTION_BUDGET:
            violations.append(f"{name} is {size} lines")
    return violations


def ownership_violations(source: str) -> list[str]:
    violations = []
    functions = _functions(source)
    for name in UPDATE_HELPERS + PROJECTION_HELPERS:
        if name not in functions:
            violations.append(f"missing helper {name}")
    entry = functions.get(UPDATE_ENTRY)
    if entry is None:
        return [*violations, f"missing entry {UPDATE_ENTRY}"]

    text = ast.unparse(entry)
    sequence = (
        "_load_version_knowledge_mappings",
        "_load_version_difficulty",
        "_ensure_knowledge_states",
        "_apply_answer_to_mappings",
        "db.flush",
        "_build_mastery_update_summary",
    )
    positions = []
    for name in sequence:
        if name not in text:
            violations.append(f"entry lost {name}")
        else:
            positions.append(text.index(name))
    if positions != sorted(positions):
        violations.append("entry call order changed")
    if "not mappings or difficulty is None" not in text:
        violations.append("entry lost the empty-input guard")
    if "_empty_mastery_update_summary" not in text:
        violations.append("entry lost the empty summary port")
    if "select(" in text or ".execute(" in text:
        violations.append("entry owns SQL")
    if "db.commit" in text or "db.rollback" in text:
        violations.append("entry owns the request transaction")

    claim = functions.get("_ensure_knowledge_states")
    if claim is not None:
        claim_text = ast.unparse(claim)
        if "_start_explicit_transaction" not in claim_text:
            violations.append("claim lost the explicit transaction")
        guarded = any(
            "missing_mappings" in ast.unparse(node.test)
            and "_start_explicit_transaction" in ast.unparse(node)
            for node in ast.walk(claim)
            if isinstance(node, ast.If)
        )
        if not guarded:
            violations.append("claim transaction is not guarded by missing mappings")
        for port in ("_claim_knowledge_state", "_reload_knowledge_state"):
            if port not in claim_text:
                violations.append(f"claim lost {port}")

    apply_state = functions.get("_apply_answer_to_knowledge_state")
    if apply_state is not None:
        apply_text = ast.unparse(apply_state)
        for port in (
            "compute_mastery_delta",
            "clamp_mastery_score",
            "compute_confidence",
            "get_mastery_label",
        ):
            if port not in apply_text:
                violations.append(f"state update lost {port}")
        if "select(" in apply_text or ".execute(" in apply_text:
            violations.append("state update owns SQL")

    apply_mappings = functions.get("_apply_answer_to_mappings")
    if apply_mappings is not None:
        mappings_text = ast.unparse(apply_mappings)
        if "missing_claim_states" not in mappings_text:
            violations.append("mapping update lost the claim counter")
        if "raise RuntimeError" not in mappings_text:
            violations.append("mapping update lost the missing-state guard")

    weak_entry = functions.get("get_user_weak_knowledge_points")
    if weak_entry is not None:
        weak_text = ast.unparse(weak_entry)
        for fragment in (
            "MASTERY_NORMAL_THRESHOLD",
            "len(weak_points) >= limit",
            "_fallback_weak_kps",
            "resolve_subject_ids",
        ):
            if fragment not in weak_text:
                violations.append(f"weak entry lost {fragment}")

    practice_projection = functions.get("_weak_point_from_practice_stats")
    if practice_projection is not None:
        projection_text = ast.unparse(practice_projection)
        for fragment in ("total < 2", "accuracy >= 0.65", "< 0.45", "total / 10.0"):
            if fragment not in projection_text:
                violations.append(f"practice projection lost {fragment}")

    state_view = functions.get("_knowledge_state_view")
    if state_view is not None:
        view_text = ast.unparse(state_view)
        for fragment in (
            "subject_name",
            "serialize_utc_datetime",
            "round(state.accuracy, 4)",
            "round(state.mastery_score, 2)",
            "round(state.confidence, 2)",
        ):
            if fragment not in view_text:
                violations.append(f"state view lost {fragment}")
    return violations


def test_mastery_service_keeps_function_budget_and_frozen_file_ceiling():
    source = FILE.read_text(encoding="utf-8")
    assert budget_violations(source) == []
    assert len(source.splitlines()) <= FILE_CEILING


def test_mastery_service_keeps_update_and_projection_ownership():
    assert ownership_violations(FILE.read_text(encoding="utf-8")) == []


def test_mastery_service_dependencies_stay_neutral_and_shared():
    graph, reverse = scan_application(APP)
    dependencies = graph[MODULE]
    assert not any(
        name == "app.api" or name.startswith("app.api.") for name in dependencies
    )
    assert "app.services.unique_conflict" in dependencies
    assert "app.services.subject_resolution" in dependencies
    assert ("app.services", "app.api") not in reverse
    for consumer in ("app.api.v1.knowledge_mastery", "app.api.v1.practice"):
        assert MODULE in graph[consumer]


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (
            "def injected():\n" + "\n".join("    value = 1" for _ in range(50)) + "\n",
            "injected is 51 lines",
        ),
    ],
)
def test_budget_gate_rejects_injected_long_function(mutation, expected):
    source = FILE.read_text(encoding="utf-8") + mutation
    assert expected in budget_violations(source)


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        (
            "\n    await db.flush()\n    return _build_mastery_update_summary(",
            "\n    return _build_mastery_update_summary(",
            "entry lost db.flush",
        ),
        (
            "    if not mappings or difficulty is None:\n",
            "    if False:\n",
            "entry lost the empty-input guard",
        ),
        ("if missing_mappings:", "if True:", "claim transaction is not guarded"),
        (
            "if state.mastery_score < MASTERY_NORMAL_THRESHOLD:",
            "if state.mastery_score < MASTERY_GOOD_THRESHOLD:",
            "weak entry lost MASTERY_NORMAL_THRESHOLD",
        ),
        ("if total < 2:", "if total < 1:", "practice projection lost total < 2"),
    ],
)
def test_ownership_gate_rejects_injected_mutations(old, new, expected):
    source = FILE.read_text(encoding="utf-8")
    assert old in source, old
    mutated = source.replace(old, new, 1)
    violations = ownership_violations(mutated)
    assert any(expected in violation for violation in violations), violations


def test_ownership_gate_rejects_removed_helper():
    source = FILE.read_text(encoding="utf-8")
    functions = _functions(source)
    node = functions["_ensure_knowledge_states"]
    lines = source.splitlines()
    mutated = "\n".join(lines[: node.lineno - 1] + lines[node.end_lineno :]) + "\n"
    violations = ownership_violations(mutated)
    assert "missing helper _ensure_knowledge_states" in violations
