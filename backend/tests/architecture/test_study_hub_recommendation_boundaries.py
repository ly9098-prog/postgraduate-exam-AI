"""Guard the study hub recommendation budgets, delegation and query semantics."""

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
SERVICE = APP / "services/study_hub_service.py"
ENTRIES = (
    "_build_subject_mastery",
    "_pick_chapter_recommendation",
    "_pick_weak_point",
    "_pick_path_prerequisite",
)
HELPERS = (
    "_fetch_subject_mastery_rows",
    "_subject_mastery_entry",
    "_rank_practiced_subjects",
    "_chapter_task_payload",
    "_chapter_task_for_subject",
    "_weak_point_columns",
    "_weak_point_joins",
    "_weak_point_filters",
    "_weak_point_group_by",
    "_weak_point_order_by",
    "_weak_point_statement",
    "_weak_point_payload",
    "_prerequisite_target_ids",
    "_rank_blocked_targets",
    "_rank_prerequisite_blockers",
    "_trainable_prerequisite",
)
SIGNATURES = {
    "_build_subject_mastery": "(db, user_id, core_subjects)",
    "_pick_chapter_recommendation": "(db, user_id, subject_mastery)",
    "_pick_weak_point": "(db, user_id, core_subject_ids)",
    "_pick_path_prerequisite": "(db, user_id, core_subject_ids)",
}


def load():
    return ast.parse(SERVICE.read_text())


def function(tree, name):
    return next(node for node in tree.body if getattr(node, "name", "") == name)


def source_of(tree, name):
    return ast.unparse(function(tree, name))


def signature_of(node):
    return "(" + ", ".join(argument.arg for argument in node.args.args) + ")"


def ordered(source, *items):
    for item in items:
        assert item in source, item
    indexes = [source.index(item) for item in items]
    assert indexes == sorted(indexes), items


def check_budgets(tree):
    for name in ENTRIES + HELPERS:
        node = function(tree, name)
        assert node.end_lineno - node.lineno + 1 <= 50, name


def check_signatures(tree):
    for name, expected in SIGNATURES.items():
        node = function(tree, name)
        assert isinstance(node, ast.AsyncFunctionDef), name
        assert signature_of(node) == expected, (name, signature_of(node))
        for argument in node.args.args:
            assert argument.annotation is not None, (name, argument.arg)


def check_mastery(tree):
    source = source_of(tree, "_build_subject_mastery")
    ordered(
        source,
        "core_ids = [int(subject.id) for subject in core_subjects]",
        "if not core_ids:\n        return []",
        "aggregate = await _fetch_subject_mastery_rows(db, user_id, core_ids)",
        "return [_subject_mastery_entry(subject, aggregate.get(int(subject.id)))"
        " for subject in core_subjects]",
    )
    fetch = source_of(tree, "_fetch_subject_mastery_rows")
    ordered(
        fetch,
        "select(UserKnowledgeState.subject_id, "
        "func.avg(UserKnowledgeState.mastery_score)",
        "func.avg(UserKnowledgeState.confidence)",
        "func.coalesce(func.sum(UserKnowledgeState.attempt_count), 0)",
        "func.coalesce(func.sum(UserKnowledgeState.correct_count), 0)",
        "func.coalesce(func.sum(UserKnowledgeState.wrong_count), 0)",
        "func.count(UserKnowledgeState.id)",
        "UserKnowledgeState.user_id == user_id",
        "UserKnowledgeState.subject_id.in_(core_ids)",
        "UserKnowledgeState.attempt_count > 0",
        "group_by(UserKnowledgeState.subject_id)",
        "return {int(row[0]): row for row in rows.all()}",
    )
    entry = source_of(tree, "_subject_mastery_entry")
    ordered(
        entry,
        "if row is None:",
        "'data_available': False",
        "'mastery_score': None",
        "attempts = int(row[3] or 0)",
        "correct = int(row[4] or 0)",
        "'data_available': bool(row[6] and attempts > 0)",
        "'mastery_score': round(float(row[1] or 0.0), 1)",
        "'confidence': round(float(row[2] or 0.0), 3)",
        "'accuracy': round(correct / attempts, 4) if attempts > 0 else None",
    )


def check_chapter(tree):
    ranking = source_of(tree, "_rank_practiced_subjects")
    ordered(
        ranking,
        "item.get('data_available')",
        "int(item.get('attempt_count') or 0) > 0",
        "if not practiced:\n        return []",
        "practiced.sort(",
        "item.get('mastery_score')",
        "else 100.0",
        "float(item.get('confidence') or 0.0)",
        "-int(item.get('attempt_count') or 0)",
        "int(item.get('subject_id') or 0)",
        "return practiced",
    )
    picker = source_of(tree, "_pick_chapter_recommendation")
    ordered(
        picker,
        "practiced = _rank_practiced_subjects(subject_mastery)",
        "if not practiced:\n        return None",
        "from app.services import knowledge_diagnosis_service",
        "for subject in practiced[:2]:",
        "task = await _chapter_task_for_subject(db, user_id, subject, "
        "knowledge_diagnosis_service)",
        "if task is not None:\n            return task",
    )
    probe = source_of(tree, "_chapter_task_for_subject")
    ordered(
        probe,
        "subject_id = int(subject.get('subject_id') or 0)",
        "if subject_id <= 0:\n        return None",
        "diagnosis = await diagnosis_module.get_knowledge_diagnosis("
        "db, user_id, subject_id, days=30)",
        "recommendation = diagnosis.get('primary_recommendation') if diagnosis else None",
        "if not isinstance(recommendation, dict):\n        return None",
        "kp_id = int(recommendation.get('knowledge_point_id') or 0)",
        "if kp_id <= 0:\n        return None",
        "count = min(SMART_TASK_COUNT, max(3,",
        "return _chapter_task_payload(",
    )
    payload = source_of(tree, "_chapter_task_payload")
    ordered(
        payload,
        "'key': f'chapter:{subject_id}:{kp_id}'",
        "'task_type': 'knowledge_chapter'",
        "'priority': 0",
        "'route_params': _practice_params(",
        "mode='random'",
        "knowledge_point_id=kp_id",
        "include_descendants=True",
        "allow_repeat=True",
        "'estimated_question_count': count",
        "'estimated_minutes': _minutes_for_questions(count)",
        "'subject_code': str(diagnosis.get('subject_code') or "
        "subject.get('subject_code') or '')",
        "'subject_name': str(diagnosis.get('subject_name') or "
        "subject.get('subject_name') or '')",
        "'knowledge_point_name': str(recommendation.get('knowledge_point_name') or '')",
    )
    assert "'route': 'practice'" in payload


def check_weak_point(tree):
    picker = source_of(tree, "_pick_weak_point")
    ordered(
        picker,
        "row = (await db.execute(_weak_point_statement(user_id, core_subject_ids))).first()",
        "if row is None:\n        return None",
        "return _weak_point_payload(row)",
    )
    statement = source_of(tree, "_weak_point_statement")
    ordered(
        statement,
        "available_count = func.count(func.distinct(Question.id))",
        "statement = select(*_weak_point_columns(available_count))",
        "for entity, onclause in _weak_point_joins():\n"
        "        statement = statement.join(entity, onclause)",
        "statement.where(*_weak_point_filters(user_id, core_subject_ids))",
        ".group_by(*_weak_point_group_by())",
        ".having(available_count >= 3)",
        ".order_by(*_weak_point_order_by())",
        ".limit(1)",
    )
    filters = source_of(tree, "_weak_point_filters")
    ordered(
        filters,
        "UserKnowledgeState.user_id == user_id",
        "UserKnowledgeState.subject_id.in_(core_subject_ids)",
        "UserKnowledgeState.attempt_count >= 2",
        "UserKnowledgeState.mastery_score < 70",
        "KnowledgePoint.is_active.is_(True)",
        "KnowledgePoint.subject_id == UserKnowledgeState.subject_id",
        "Question.subject_id == UserKnowledgeState.subject_id",
        "Question.is_active.is_(True)",
        "Question.review_status == 'approved'",
        "QuestionVersion.question_id == Question.id",
        "QuestionVersion.subject_id == Question.subject_id",
        "QuestionVersion.question_type == Question.question_type",
        "QuestionVersion.question_type.in_(_ANSWERABLE_TYPES)",
        "QuestionVersion.is_active.is_(True)",
    )
    joins = source_of(tree, "_weak_point_joins")
    ordered(
        joins,
        "KnowledgePoint.id == UserKnowledgeState.knowledge_point_id",
        "Subject.id == UserKnowledgeState.subject_id",
        "QuestionKnowledgePoint.knowledge_point_id == "
        "UserKnowledgeState.knowledge_point_id",
        "Question.id == QuestionKnowledgePoint.question_id",
        "QuestionVersion.id == Question.current_version_id",
    )
    columns = source_of(tree, "_weak_point_columns")
    ordered(
        columns,
        "UserKnowledgeState.knowledge_point_id",
        "KnowledgePoint.name",
        "UserKnowledgeState.subject_id",
        "Subject.code",
        "Subject.name",
        "UserKnowledgeState.mastery_score",
        "UserKnowledgeState.confidence",
        "UserKnowledgeState.attempt_count",
        "UserKnowledgeState.wrong_count",
        "UserKnowledgeState.recent_wrong_count",
        "available_count.label('available_question_count')",
    )
    group_by = source_of(tree, "_weak_point_group_by")
    ordered(
        group_by,
        "UserKnowledgeState.knowledge_point_id",
        "KnowledgePoint.name",
        "UserKnowledgeState.subject_id",
        "Subject.code",
        "Subject.name",
    )
    order_by = source_of(tree, "_weak_point_order_by")
    ordered(
        order_by,
        "case((UserKnowledgeState.recent_wrong_count >= 2, 0), else_=1)",
        "UserKnowledgeState.recent_wrong_count.desc()",
        "UserKnowledgeState.mastery_score.asc()",
        "UserKnowledgeState.wrong_count.desc()",
        "UserKnowledgeState.knowledge_point_id.asc()",
    )
    payload = source_of(tree, "_weak_point_payload")
    ordered(
        payload,
        "'knowledge_point_id': int(row[0])",
        "'knowledge_point_name': str(row[1])",
        "'subject_id': int(row[2])",
        "'mastery_score': round(float(row[5] or 0.0), 1)",
        "'confidence': round(float(row[6] or 0.0), 3)",
        "'recent_wrong_count': int(row[9] or 0)",
        "'available_question_count': int(row[10] or 0)",
    )


def check_path(tree):
    picker = source_of(tree, "_pick_path_prerequisite")
    ordered(
        picker,
        "target_ids = await _prerequisite_target_ids(db, core_subject_ids)",
        "if not target_ids:\n        return None",
        "context = await adaptive_learning_service.get_recommendation_graph_context(",
        "blocked_targets = context.get('blocked_targets') or {}",
        "if not blocked_targets:\n        return None",
        "target_id, blockers = _rank_blocked_targets(blocked_targets)[0]",
        "ranked_blockers = _rank_prerequisite_blockers(blockers)",
        "for prereq in ranked_blockers:",
        "payload = await _trainable_prerequisite(db, prereq, target_id, core_subject_ids)",
        "if payload is not None:\n            return payload",
    )
    assert picker.rstrip().endswith("return None")
    targets = source_of(tree, "_prerequisite_target_ids")
    ordered(
        targets,
        "select(KnowledgeEdge.target_knowledge_point_id)",
        "KnowledgeEdge.subject_id.in_(core_subject_ids)",
        "KnowledgeEdge.relation_type == 'prerequisite'",
        "KnowledgeEdge.is_active.is_(True)",
        ".distinct()",
        "order_by(KnowledgeEdge.target_knowledge_point_id.asc())",
        "return [int(row[0]) for row in target_rows.all()]",
    )
    ranked_targets = source_of(tree, "_rank_blocked_targets")
    assert "key=lambda item: (-len(item[1] or []), item[0])" in ranked_targets
    ranked_blockers = source_of(tree, "_rank_prerequisite_blockers")
    ordered(
        ranked_blockers,
        "float(item.get('mastery_score', 50.0))",
        "-float(item.get('path_quality', 0.0))",
        "int(item.get('knowledge_point_id') or 0)",
    )
    candidate = source_of(tree, "_trainable_prerequisite")
    ordered(
        candidate,
        "prereq_subject_id = int(prereq.get('subject_id') or 0)",
        "prereq_kp_id = int(prereq.get('knowledge_point_id') or 0)",
        "if prereq_subject_id not in core_subject_ids or prereq_kp_id <= 0:\n"
        "        return None",
        "available_count = await _count_trainable_kp_questions(",
        "knowledge_point_id=prereq_kp_id",
        "subject_id=prereq_subject_id",
        "if available_count < 3:\n        return None",
        "await db.execute(select(Subject).where(Subject.id == prereq_subject_id))",
        "if subject is None:\n        return None",
        "'target_knowledge_point_id': target_id",
        "'target_knowledge_point_name': str(prereq.get('origin_name') or '')",
        "'knowledge_point_id': prereq_kp_id",
        "'knowledge_point_name': str(prereq.get('name') or '')",
        "'mastery_score': round(float(prereq.get('mastery_score') or 0.0), 1)",
        "'available_question_count': available_count",
    )


def test_recommendation_helpers_stay_within_budget():
    check_budgets(load())


def test_recommendation_delegation_and_query_semantics():
    tree = load()
    check_signatures(tree)
    check_mastery(tree)
    check_chapter(tree)
    check_weak_point(tree)
    check_path(tree)


def test_gate_rejects_widened_chapter_probe_and_reordered_blockers():
    tree = load()
    chapter = function(tree, "_pick_chapter_recommendation")
    for node in ast.walk(chapter):
        if isinstance(node, ast.Slice) and ast.unparse(node) == ":2":
            node.upper = ast.Constant(value=3)
            break
    with pytest.raises(AssertionError):
        check_chapter(tree)

    tree = load()
    blockers = function(tree, "_rank_prerequisite_blockers")
    for node in ast.walk(blockers):
        if (
            isinstance(node, ast.Call)
            and ast.unparse(node) == "float(item.get('mastery_score', 50.0))"
        ):
            node.args[0] = ast.UnaryOp(op=ast.USub(), operand=node.args[0])
            break
    with pytest.raises(AssertionError):
        check_path(tree)


def test_gate_rejects_relaxed_weak_point_filters():
    tree = load()
    filters = function(tree, "_weak_point_filters")
    for node in ast.walk(filters):
        if (
            isinstance(node, ast.Compare)
            and ast.unparse(node.left) == "UserKnowledgeState.attempt_count"
        ):
            node.comparators = [ast.Constant(value=1)]
            break
    with pytest.raises(AssertionError):
        check_weak_point(tree)
