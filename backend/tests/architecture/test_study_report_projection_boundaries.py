"""Study-report projections must remain pure and consumed by the service."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from tests.architecture.dependency_scan import scan_application

BACKEND = Path(__file__).resolve().parents[2]
APP = BACKEND / "app"
MODULE = "app.services.study_report_projection"
SERVICE = "app.services.study_report_service"


def test_projection_dependencies_and_budgets():
    graph, _ = scan_application(APP)
    assert graph[MODULE] == set()
    assert MODULE in graph[SERVICE]
    source = (APP / "services/study_report_projection.py").read_text()
    assert len(source.splitlines()) <= 252
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50
        if isinstance(node, ast.Call):
            assert getattr(node.func, "attr", "") not in {
                "execute",
                "commit",
                "rollback",
                "flush",
                "create_task",
            }


def test_service_aliases_point_to_actual_projection_definitions():
    from app.services import study_report_projection, study_report_service

    assert study_report_service._safe_accuracy is study_report_projection.safe_accuracy
    assert study_report_service._extract_title is study_report_projection.extract_title
    assert (
        study_report_service._classify_mastery
        is study_report_projection.classify_mastery
    )
    assert (
        study_report_service._mastery_suggestion
        is study_report_projection.mastery_suggestion
    )
    assert study_report_service._calc_priority is study_report_projection.calc_priority

    tree = ast.parse(Path(study_report_service.__file__).read_text())
    definitions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert not definitions & {
        "safe_accuracy",
        "extract_title",
        "classify_mastery",
        "mastery_suggestion",
        "calc_priority",
        "build_leitner_distribution_response",
        "normalize_study_trend_counts",
    }


def test_import_has_no_runtime_resources_or_side_effects():
    probe = """
import asyncio
import os
import sys
before = dict(os.environ)
def forbidden(*args, **kwargs):
    raise AssertionError("study report projection import must not create tasks")
asyncio.create_task = forbidden
from app.services.study_report_projection import safe_accuracy
assert callable(safe_accuracy)
assert dict(os.environ) == before
for name in (
    'app.main', 'app.core.config', 'app.core.database', 'app.models',
    'app.services.study_report_service', 'sqlalchemy', 'fastapi',
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


# ── detail-split gate (2026-10-28) ───────────────────────────────────

ENTRIES = ("get_review_plan", "get_wrong_questions_summary")

HELPERS = (
    "_review_plan_items_query",
    "_load_first_knowledge_point_map",
    "_wrong_summary_items_query",
    "_count_wrong_summary_states",
)

SIGNATURES = {
    "get_review_plan": ("(db, user_id, subject_id, limit)", "(None, 20)"),
    "get_wrong_questions_summary": (
        "(db, user_id, subject_id, limit, min_wrong_count)",
        "(None, 20, 1)",
    ),
}

FROZEN_SOURCES = {
    "_review_plan_items_query": 'def _review_plan_items_query(user_id: int, subject_id: int | None, now, limit: int):\n    """Build the priority-ordered due-review detail query."""\n    query = select(UserQuestionState.question_id, UserQuestionState.box_level, UserQuestionState.wrong_count, UserQuestionState.correct_count, UserQuestionState.next_review_at).where(UserQuestionState.user_id == user_id, UserQuestionState.next_review_at <= now, UserQuestionState.next_review_at.isnot(None))\n    if subject_id is not None:\n        query = query.join(Question, UserQuestionState.question_id == Question.id).where(Question.subject_id == subject_id)\n    return query.order_by(UserQuestionState.next_review_at.asc(), UserQuestionState.box_level.asc(), UserQuestionState.wrong_count.desc()).limit(limit)',
    "_load_first_knowledge_point_map": 'async def _load_first_knowledge_point_map(db: AsyncSession, question_ids: list[int]) -> dict[int, tuple[int, str]]:\n    """Batch-load each question\'s first knowledge point (lowest link id wins)."""\n    knowledge_points: dict[int, tuple[int, str]] = {}\n    if not question_ids:\n        return knowledge_points\n    rows = (await db.execute(select(QuestionKnowledgePoint.question_id, QuestionKnowledgePoint.knowledge_point_id, KnowledgePoint.name).join(KnowledgePoint, QuestionKnowledgePoint.knowledge_point_id == KnowledgePoint.id).where(QuestionKnowledgePoint.question_id.in_(question_ids)).order_by(QuestionKnowledgePoint.question_id, QuestionKnowledgePoint.id))).all()\n    for row in rows:\n        if row.question_id not in knowledge_points:\n            knowledge_points[row.question_id] = (row.knowledge_point_id, row.name)\n    return knowledge_points',
    "_wrong_summary_items_query": 'def _wrong_summary_items_query(user_id: int, subject_id: int | None, min_wrong_count: int, limit: int):\n    """Build the wrong-question detail query; the question join always applies."""\n    query = select(UserQuestionState.question_id, UserQuestionState.wrong_count, UserQuestionState.correct_count, UserQuestionState.answer_count, UserQuestionState.last_answered_at, UserQuestionState.next_review_at, UserQuestionState.box_level, Question.content.label(\'q_content\')).where(UserQuestionState.user_id == user_id, UserQuestionState.wrong_count >= min_wrong_count)\n    if subject_id is not None:\n        query = query.join(Question, UserQuestionState.question_id == Question.id).where(Question.subject_id == subject_id)\n    else:\n        query = query.join(Question, UserQuestionState.question_id == Question.id)\n    return query.order_by(UserQuestionState.wrong_count.desc(), UserQuestionState.box_level.asc(), UserQuestionState.last_answered_at.desc().nullslast()).limit(limit)',
    "_count_wrong_summary_states": 'async def _count_wrong_summary_states(db: AsyncSession, user_id: int, subject_id: int | None, min_wrong_count: int) -> tuple[int, int]:\n    """Count wrong-question totals and repeated ones in the original order."""\n    wrong_total = (await db.execute(_review_state_count_query(user_id, subject_id, [UserQuestionState.wrong_count >= min_wrong_count]))).scalar_one()\n    repeated_count = (await db.execute(_review_state_count_query(user_id, subject_id, [UserQuestionState.wrong_count >= 3, UserQuestionState.wrong_count >= min_wrong_count]))).scalar_one()\n    return (int(wrong_total), int(repeated_count))',
}


SERVICE_TEXT = (APP / "services/study_report_service.py").read_text(encoding="utf-8")


def service_tree():
    return ast.parse(SERVICE_TEXT)


def service_function(tree, name):
    return next(node for node in tree.body if getattr(node, "name", "") == name)


def service_source(tree, name):
    return ast.unparse(service_function(tree, name))


def count_of(tree, name, fragment):
    return service_source(tree, name).count(fragment)


def ordered(source, *items):
    for item in items:
        assert item in source, item
    indexes = [source.index(item) for item in items]
    assert indexes == sorted(indexes), items


def check_detail_budgets(tree):
    for name in ENTRIES + HELPERS:
        node = service_function(tree, name)
        assert node.end_lineno - node.lineno + 1 <= 50, name


def check_detail_signatures(tree):
    for name, (expected, expected_defaults) in SIGNATURES.items():
        node = service_function(tree, name)
        assert isinstance(node, ast.AsyncFunctionDef), name
        args = list(node.args.posonlyargs) + list(node.args.args)
        args += list(node.args.kwonlyargs)
        assert "(" + ", ".join(a.arg for a in args) + ")" == expected, name
        values = [v for v in node.args.defaults + node.args.kw_defaults if v]
        assert "(" + ", ".join(ast.unparse(v) for v in values) + ")" == (
            expected_defaults
        ), name


def check_detail_frozen_sources(tree):
    for name, expected in FROZEN_SOURCES.items():
        assert service_source(tree, name) == expected, name


def check_detail_delegation(tree):
    plan = service_source(tree, "get_review_plan")
    ordered(
        plan,
        "now = utcnow()",
        "overdue_threshold = now - timedelta(days=1)",
        "due_count, overdue_count = await _count_review_states(",
        "db, user_id, subject_id, now, overdue_threshold",
        "_review_plan_items_query(user_id, subject_id, now, limit)",
        "_load_first_knowledge_point_map(",
        "build_review_plan_item(",
        "row=row, knowledge_point=kp_map.get(row.question_id), now=now",
        "'today_recommended_count': len(items)",
    )
    # One clock read feeds both the counters and the per-row projection.
    assert plan.count("utcnow()") == 1

    summary = service_source(tree, "get_wrong_questions_summary")
    ordered(
        summary,
        "wrong_total, repeated_count = await _count_wrong_summary_states(",
        "db, user_id, subject_id, min_wrong_count",
        "_wrong_summary_items_query(user_id, subject_id, min_wrong_count, limit)",
        "_load_first_knowledge_point_map(",
        "build_wrong_question_item(",
        "'wrong_question_count': wrong_total",
        "'repeated_wrong_question_count': repeated_count",
    )


def check_detail_single_source(tree):
    # The due/overdue counters are the shared review-state counter, not a copy.
    assert count_of(tree, "get_review_plan", "_rp_count_q") == 0
    assert count_of(tree, "get_review_plan", "_count_review_states(") == 1
    assert count_of(tree, "get_overview", "_count_review_states(") == 1
    assert SERVICE_TEXT.count("def _review_state_count_query(") == 1
    # One definition + two counters for get_overview + two for the wrong summary.
    assert SERVICE_TEXT.count("_review_state_count_query(") == 5

    # One knowledge-point batch loader serves both detail readers.
    assert SERVICE_TEXT.count("def _load_first_knowledge_point_map(") == 1
    assert SERVICE_TEXT.count("_load_first_knowledge_point_map(") == 3
    for name in ("get_review_plan", "get_wrong_questions_summary"):
        assert count_of(tree, name, "QuestionKnowledgePoint") == 0, name
    loader = service_source(tree, "_load_first_knowledge_point_map")
    assert loader.count("if row.question_id not in knowledge_points") == 1
    assert loader.count("knowledge_points[row.question_id] = (") == 1

    # Statement shapes stay in exactly one builder each.
    assert count_of(tree, "_review_plan_items_query", ".limit(limit)") == 1
    assert count_of(tree, "_wrong_summary_items_query", ".limit(limit)") == 1
    # Two NULLS LAST orderings exist (knowledge states + wrong-question detail);
    # each stays inside its own builder.
    assert SERVICE_TEXT.count(".nullslast()") == 2
    assert count_of(tree, "_wrong_summary_items_query", ".nullslast()") == 1
    assert count_of(tree, "_count_wrong_summary_states", "wrong_count >= 3") == 1
    assert SERVICE_TEXT.count("wrong_count >= 3") == 2  # detail floor is the caller's
    assert count_of(tree, "_count_wrong_summary_states", ".scalar_one()") == 2
    assert count_of(tree, "_wrong_summary_items_query", "join(") == 2
    for name in ENTRIES:
        assert "select(" not in service_source(tree, name), name


def test_detail_split_budgets():
    check_detail_budgets(service_tree())


def test_detail_split_signatures_frozen_sources_and_delegation():
    tree = service_tree()
    check_detail_signatures(tree)
    check_detail_frozen_sources(tree)
    check_detail_delegation(tree)


def test_detail_split_single_source():
    check_detail_single_source(service_tree())


def test_gate_rejects_widened_detail_helper():
    padding = "".join(f"    _pad_{index} = {index}\n" for index in range(60))
    text = SERVICE_TEXT.replace(
        "    return int(wrong_total), int(repeated_count)",
        padding + "    return int(wrong_total), int(repeated_count)",
        1,
    )
    assert text != SERVICE_TEXT
    with pytest.raises(AssertionError):
        check_detail_budgets(ast.parse(text))


def test_gate_rejects_reordered_count_and_detail_reads():
    tree = service_tree()
    plan = service_function(tree, "get_review_plan")
    body = [
        node
        for node in plan.body
        if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))
    ]
    count_index = next(
        index
        for index, node in enumerate(body)
        if "_count_review_states" in ast.unparse(node)
    )
    items_index = next(
        index
        for index, node in enumerate(body)
        if "_review_plan_items_query" in ast.unparse(node)
    )
    body.insert(items_index + 1, body.pop(count_index))
    plan.body = body
    with pytest.raises(AssertionError):
        check_detail_delegation(tree)


def test_gate_rejects_copied_knowledge_point_loader():
    tree = service_tree()
    summary = service_function(tree, "get_wrong_questions_summary")
    summary.body.insert(
        3,
        ast.parse(
            "rows = (await db.execute(select(QuestionKnowledgePoint))).all()"
        ).body[0],
    )
    with pytest.raises(AssertionError):
        check_detail_single_source(tree)
