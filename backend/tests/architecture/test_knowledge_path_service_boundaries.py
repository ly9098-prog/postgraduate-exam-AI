"""Knowledge-path service ownership, budget and dependency gates."""

import ast
from pathlib import Path

import pytest

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"
MODULE = "app.services.knowledge_path_service"
FILE = APP / "services" / "knowledge_path_service.py"

FUNCTION_BUDGET = 50
# Frozen legacy ceiling: future extractions must lower it, never raise it.
FILE_CEILING = 658

PATH_ENTRY = "build_user_knowledge_path"
QUESTION_ENTRY = "attach_recommended_questions_to_path"
RESPONSE_ENTRY = "get_user_path_recommendations"
HELPERS = (
    "_resolve_start_point",
    "_collect_neighbor_nodes",
    "_apply_mastery",
    "_dedupe_and_limit_nodes",
    "_load_path_question_candidates",
    "_recommend_for_node",
    "_merge_vector_recalls",
    "_resolve_subject_labels",
    "_empty_path_response",
    "_write_path_recommendation_logs",
    "_path_response",
    "_node_priority",
    "_node_reason",
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
    for name in HELPERS:
        if name not in functions:
            violations.append(f"missing helper {name}")

    path_entry = functions.get(PATH_ENTRY)
    if path_entry is None:
        violations.append(f"missing entry {PATH_ENTRY}")
    else:
        text = ast.unparse(path_entry)
        for fragment in (
            "_resolve_start_point",
            "_collect_neighbor_nodes",
            "_attach_subject_info",
            "_apply_mastery",
            "_compute_priorities",
            "_dedupe_and_limit_nodes",
        ):
            if fragment not in text:
                violations.append(f"path entry lost {fragment}")
        if "select(" in text or ".execute(" in text:
            violations.append("path entry owns SQL")

    question_entry = functions.get(QUESTION_ENTRY)
    if question_entry is None:
        violations.append(f"missing entry {QUESTION_ENTRY}")
    else:
        text = ast.unparse(question_entry)
        for fragment in (
            "_load_path_question_candidates",
            "random.shuffle",
            "_recommend_for_node",
        ):
            if fragment not in text:
                violations.append(f"question entry lost {fragment}")
        if "select(" in text or ".execute(" in text:
            violations.append("question entry owns SQL")

    response_entry = functions.get(RESPONSE_ENTRY)
    if response_entry is None:
        violations.append(f"missing entry {RESPONSE_ENTRY}")
    else:
        text = ast.unparse(response_entry)
        for fragment in (
            "_resolve_subject_labels",
            "_empty_path_response",
            "_write_path_recommendation_logs",
            "_path_response",
        ):
            if fragment not in text:
                violations.append(f"response entry lost {fragment}")

    recommendation = functions.get("_recommend_for_node")
    if recommendation is not None:
        text = ast.unparse(recommendation)
        for fragment in (
            "_mastery_to_target_difficulty",
            "vector_retrieval_service",
            "_merge_vector_recalls",
        ):
            if fragment not in text:
                violations.append(f"question recommendation lost {fragment}")

    priority = functions.get("_node_priority")
    if priority is not None:
        text = ast.unparse(priority)
        for fragment in (
            "_weak_priority",
            "_prerequisite_priority",
            "_edge_signal",
            "_has_weak_prerequisite",
            "round(priority, 4)",
        ):
            if fragment not in text:
                violations.append(f"priority policy lost {fragment}")
    return violations


def test_knowledge_path_service_keeps_budget_and_frozen_ceiling():
    source = FILE.read_text(encoding="utf-8")
    assert budget_violations(source) == []


def test_knowledge_path_service_keeps_entry_ownership():
    assert ownership_violations(FILE.read_text(encoding="utf-8")) == []


def test_knowledge_path_service_dependencies_stay_within_service_boundary():
    graph, _ = scan_application(APP)
    dependencies = graph[MODULE]
    assert "app.services.knowledge_graph_service" in dependencies
    assert "app.services.mastery_service" in dependencies
    assert "app.services.vector_retrieval_service" in dependencies
    assert "app.services.recommendation_log_service" in dependencies
    assert not any(
        name == "app.api" or name.startswith("app.api.") for name in dependencies
    )


def test_budget_gate_rejects_injected_long_function():
    source = FILE.read_text(encoding="utf-8")
    source += "def injected():\n" + "\n".join("    value = 1" for _ in range(50)) + "\n"
    assert "injected is 51 lines" in budget_violations(source)


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        (
            "nodes += await _collect_neighbor_nodes(\n"
            '        db, knowledge_graph_service, start_kp["knowledge_point_id"]\n'
            "    )",
            "nodes += []",
            "path entry lost _collect_neighbor_nodes",
        ),
        (
            "random.shuffle(shuffled_nodes)",
            "pass",
            "question entry lost random.shuffle",
        ),
        (
            "_write_path_recommendation_logs(",
            "print(",
            "response entry lost _write_path_recommendation_logs",
        ),
        (
            "round(priority, 4)",
            "round(priority, 2)",
            "priority policy lost round(priority, 4)",
        ),
    ],
)
def test_ownership_gate_rejects_injected_mutations(old, new, expected):
    source = FILE.read_text(encoding="utf-8")
    assert old in source, old
    violations = ownership_violations(source.replace(old, new, 1))
    assert any(expected in violation for violation in violations), violations


def test_ownership_gate_rejects_removed_helper():
    source = FILE.read_text(encoding="utf-8")
    node = _functions(source)["_collect_neighbor_nodes"]
    lines = source.splitlines()
    mutated = "\n".join(lines[: node.lineno - 1] + lines[node.end_lineno :]) + "\n"
    assert "missing helper _collect_neighbor_nodes" in ownership_violations(mutated)
