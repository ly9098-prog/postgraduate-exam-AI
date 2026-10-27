"""Guard the study-report overview decomposition and query ownership."""

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
SERVICE = APP / "services/study_report_service.py"
HELPERS = (
    "_practice_counts_query",
    "_load_practice_counts",
    "_review_state_count_query",
    "_count_review_states",
    "_wrong_state_count_query",
    "_count_wrong_states",
    "_knowledge_state_count_query",
    "_count_knowledge_states",
)
QUERY_BUILDERS = (
    "_practice_counts_query",
    "_review_state_count_query",
    "_wrong_state_count_query",
    "_knowledge_state_count_query",
)


def load():
    return ast.parse(SERVICE.read_text())


def function(tree, name):
    return next(node for node in tree.body if getattr(node, "name", "") == name)


def source_of(tree, name):
    return ast.unparse(function(tree, name))


def check_budgets(tree):
    assert len(SERVICE.read_text().splitlines()) <= 700
    for name in ("get_overview",) + HELPERS:
        node = function(tree, name)
        assert node.end_lineno - node.lineno + 1 <= 50, name


def check_overview_orchestration(tree):
    source = source_of(tree, "get_overview")
    for forbidden in ("select(", "case(", "func.count", "scalar_one("):
        assert forbidden not in source, forbidden
    order = [
        source.index("_load_practice_counts("),
        source.index("_count_review_states("),
        source.index("_count_wrong_states("),
    ]
    assert order == sorted(order)
    assert "weak_count = unstable_count = mastered_count = 0" in source
    branches = next(
        node for node in function(tree, "get_overview").body if isinstance(node, ast.If)
    )
    assert ast.unparse(branches.test) == "subject_id is None"
    assert "_count_knowledge_states" in ast.unparse(branches.body)
    probe_branch = branches.orelse[0]
    assert isinstance(probe_branch, ast.If)
    assert "await _subject_exists(db, subject_id)" in ast.unparse(probe_branch.test)
    assert "_count_knowledge_states" in ast.unparse(probe_branch.body)


def check_query_ownership(tree):
    owners = "\n".join(source_of(tree, name) for name in HELPERS)
    for threshold in (
        "UserQuestionState.next_review_at <=",
        "UserQuestionState.next_review_at < overdue_threshold",
        "UserQuestionState.wrong_count > 0",
        "UserQuestionState.wrong_count >= 3",
        "UserKnowledgeState.mastery_score < 40",
        "UserKnowledgeState.mastery_score >= 40",
        "UserKnowledgeState.mastery_score < 85",
        "UserKnowledgeState.mastery_score >= 85",
    ):
        assert owners.count(threshold) == 1, threshold
    overview_source = source_of(tree, "get_overview")
    assert "mastery_score" not in overview_source
    assert "wrong_count" not in overview_source
    assert "next_review_at" not in overview_source
    whole_service = SERVICE.read_text()
    for forbidden in ("db.commit", "db.flush", "db.add(", "db.delete"):
        assert forbidden not in whole_service, forbidden


def test_overview_and_helpers_stay_within_budget():
    check_budgets(load())


def test_overview_delegates_queries_and_keeps_subject_probe_order():
    check_overview_orchestration(load())


def test_thresholds_live_only_in_query_builders():
    check_query_ownership(load())


def test_gate_rejects_threshold_leak_and_inverted_probe():
    tree = load()
    overview = function(tree, "get_overview")
    overview.body.insert(
        0,
        ast.parse("leaked = UserQuestionState.wrong_count >= 3").body[0],
    )
    with pytest.raises(AssertionError):
        check_query_ownership(tree)

    tree = load()
    branches = next(
        node for node in function(tree, "get_overview").body if isinstance(node, ast.If)
    )
    branches.test = ast.parse("False").body[0].value
    with pytest.raises(AssertionError):
        check_overview_orchestration(tree)
