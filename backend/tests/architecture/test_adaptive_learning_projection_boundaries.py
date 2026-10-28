"""Guard the adaptive-learning projection budgets, delegation and semantics."""

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
SERVICE = APP / "services/adaptive_learning_service.py"

ENTRIES = (
    "get_recommendation_graph_context",
    "apply_personalized_interval",
    "update_question_difficulty_state",
    "update_knowledge_interval_factor",
    "get_adaptive_overview",
    "get_hard_questions",
    "adjust_recommend_weights",
    "update_adaptive_state_after_answer",
)

HELPERS = (
    "_load_knowledge_adaptive_states",
    "_ensure_knowledge_adaptive_states",
    "_adjust_knowledge_interval_state",
    "_difficulty_delta",
    "_apply_difficulty_counters",
    "_update_avg_answer_time",
    "_apply_difficulty_answer",
    "_log_difficulty_change",
    "_load_question_kp_ids",
    "_load_user_interval_factor",
    "_load_knowledge_interval_factor",
    "_load_difficulty_interval_factor",
    "_load_user_question_state",
    "_override_next_review_at",
    "_resolve_review_flags",
    "_update_difficulty_from_answer",
    "_apply_leitner_interval_override",
    "_update_interval_factors",
    "_interval_status",
    "_count_fast_forgetting_points",
    "_count_user_hard_questions",
    "_count_path_blocked_knowledge",
    "_weight_status",
    "_hard_questions_statement",
    "_load_hard_question_labels",
    "_hard_question_item",
    "_empty_graph_context",
    "_graph_origin_ids",
    "_bounded_graph_limits",
    "_graph_edge_conditions",
    "_fetch_graph_edges",
    "_graph_relation_payload",
    "_expand_graph_layer",
    "_collect_graph_relations",
    "_load_graph_kp_info",
    "_load_graph_mastery",
    "_graph_relation_item",
    "_graph_candidate_rank",
    "_graph_current_rank",
    "_graph_candidate_eligible",
    "_graph_context",
    "_record_graph_relation",
    "_keep_graph_candidate",
    "_project_graph_relations",
    "_graph_scope_ids",
    "_preference_weights",
    "_recent_practice_stats",
    "_recent_due_stats",
    "_weight_adjustments",
    "_apply_weight_adjustments",
    "_log_weight_adjustments",
)

SIGNATURES = {
    "get_recommendation_graph_context": (
        "(db, user_id, target_kp_ids, subject_ids, max_depth, max_nodes, min_mastery, "
        "min_confidence)",
        "(None, GRAPH_MAX_DEPTH, GRAPH_MAX_EXPANSION_NODES, "
        "GRAPH_PREREQUISITE_MASTERY_THRESHOLD, GRAPH_PREREQUISITE_CONFIDENCE_THRESHOLD)",
    ),
    "apply_personalized_interval": (
        "(db, user_id, question_id, base_interval_days)",
        "()",
    ),
    "update_question_difficulty_state": (
        "(db, user_id, question_id, is_correct, answer_time_seconds, "
        "expected_time_seconds, is_overdue_review)",
        "()",
    ),
    "update_knowledge_interval_factor": (
        "(db, user_id, knowledge_point_ids, is_due_review, is_correct, is_overdue_review)",
        "()",
    ),
    "get_adaptive_overview": ("(db, user_id)", "()"),
    "get_hard_questions": ("(db, user_id, limit)", "(20)"),
    "adjust_recommend_weights": ("(db, user_id)", "()"),
    "update_adaptive_state_after_answer": (
        "(db, user_id, question_id, is_correct, answer_time_seconds, answered_at, "
        "is_due_review, is_overdue_review)",
        "(None, None)",
    ),
}


def load():
    return ast.parse(SERVICE.read_text())


def function(tree, name):
    return next(node for node in tree.body if getattr(node, "name", "") == name)


def source_of(tree, name):
    return ast.unparse(function(tree, name))


def signature_of(node):
    return "(" + ", ".join(argument.arg for argument in node.args.args) + ")"


def defaults_of(node):
    return "(" + ", ".join(ast.unparse(value) for value in node.args.defaults) + ")"


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
    for name, (expected, expected_defaults) in SIGNATURES.items():
        node = function(tree, name)
        assert isinstance(node, ast.AsyncFunctionDef), name
        assert signature_of(node) == expected, (name, signature_of(node))
        assert defaults_of(node) == expected_defaults, (name, defaults_of(node))
        for argument in node.args.args:
            assert argument.annotation is not None, (name, argument.arg)


FROZEN_SOURCES = {
    "_bounded_graph_limits": (
        "def _bounded_graph_limits(max_depth: int, max_nodes: int) -> tuple[int, int]:\n"
        '    """深度与节点数上限 clamp。"""\n'
        "    bounded_depth = max(1, min(int(max_depth or 1), GRAPH_MAX_DEPTH))\n"
        "    bounded_nodes = max(1, int(max_nodes or GRAPH_MAX_EXPANSION_NODES))\n"
        "    return (bounded_depth, bounded_nodes)"
    ),
    "_graph_candidate_eligible": (
        "def _graph_candidate_eligible(rel: dict, item: dict) -> bool:\n"
        '    """候选扩展条件：确认缺口，或直接未知前置（软诊断）。"""\n'
        "    return bool(item['confirmed_gap'] or (rel['depth'] == 1 and "
        "item['unknown_gap']))"
    ),
    "_graph_candidate_rank": (
        "def _graph_candidate_rank(item: dict) -> tuple:\n"
        '    """候选排序键：确认缺口优先，其次路径质量，最后浅层优先。"""\n'
        "    return (1 if item['confirmed_gap'] else 0, item['path_quality'], "
        "-item['depth'])"
    ),
    "_graph_current_rank": (
        "def _graph_current_rank(current: dict | None) -> tuple:\n"
        '    """已存候选的排序键；无候选时返回最小键。"""\n'
        "    return (1 if current and current.get('confirmed_gap') else 0, "
        "current.get('path_quality', 0.0) if current else -1.0, "
        "-current.get('depth', 99) if current else -99)"
    ),
    "_interval_status": (
        "def _interval_status(interval_factor: float) -> str:\n"
        '    """按用户间隔倍率给出记忆状态标签。"""\n'
        "    if interval_factor < 0.9:\n        return 'fast_forgetting'\n"
        "    if interval_factor < 0.98:\n        return 'slightly_fast_forgetting'\n"
        "    if interval_factor > 1.1:\n        return 'stable_memory'\n"
        "    return 'normal'"
    ),
}


def check_frozen_sources(tree):
    for name, expected in FROZEN_SOURCES.items():
        assert source_of(tree, name) == expected, name


def check_delegation(tree):
    record = source_of(tree, "_record_graph_relation")
    ordered(
        record,
        "origin_id = rel['origin_knowledge_point_id']",
        "prerequisites_by_target.setdefault(origin_id, []).append(item)",
        "if rel['depth'] == 1 and item['confirmed_gap']:",
        "blocked_targets.setdefault(origin_id, []).append(item)",
    )
    keeper = source_of(tree, "_keep_graph_candidate")
    ordered(
        keeper,
        "prereq_id = rel['knowledge_point_id']",
        "current = prerequisite_candidates.get(prereq_id)",
        "if current is None or _graph_candidate_rank(item) > "
        "_graph_current_rank(current):",
        "prerequisite_candidates[prereq_id] = item",
    )

    graph = source_of(tree, "get_recommendation_graph_context")
    ordered(
        graph,
        "origin_ids = _graph_origin_ids(target_kp_ids)",
        "if not origin_ids:\n        return _empty_graph_context()",
        "max_depth, max_nodes = _bounded_graph_limits(max_depth, max_nodes)",
        "relations = await _collect_graph_relations(",
        "if not relations:\n        return _empty_graph_context()",
        "all_kp_ids = _graph_scope_ids(origin_ids, relations)",
        "kp_info = await _load_graph_kp_info(db, all_kp_ids)",
        "mastery = await _load_graph_mastery(db, user_id, all_kp_ids)",
        "return _project_graph_relations(",
    )
    assert graph.rstrip().endswith(")")

    traversal = source_of(tree, "_collect_graph_relations")
    ordered(
        traversal,
        "frontier: dict[tuple[int, int], dict[str, float]] = {",
        "(origin, origin): {'weight': 1.0, 'confidence': 1.0}",
        "visited: set[tuple[int, int]] = set(frontier)",
        "relations: list[dict] = []",
        "for depth in range(1, max_depth + 1):",
        "if not frontier or len(relations) >= max_nodes:",
        "current_targets = list({node_id for node_id, _origin in frontier})",
        "edges_by_target = await _fetch_graph_edges(",
        "frontier = _expand_graph_layer(",
        "return relations",
    )

    layer = source_of(tree, "_expand_graph_layer")
    ordered(
        layer,
        "next_frontier: dict[tuple[int, int], dict[str, float]] = {}",
        "for (current_id, origin_id), parent_quality in frontier.items():",
        "for edge in edges_by_target.get(current_id, []):",
        "prereq_id = edge.source_knowledge_point_id",
        "pair = (prereq_id, origin_id)",
        "if pair in visited:\n                continue",
        "relations.append(payload)",
        "visited.add(pair)",
        "if len(relations) >= max_nodes:\n                break",
        "if depth < max_depth:",
        "next_frontier[pair] = {",
        "return next_frontier",
    )

    payload = source_of(tree, "_graph_relation_payload")
    ordered(
        payload,
        "edge_weight = normalize_edge_weight(edge.weight)",
        "edge_confidence = _clamp01(edge.confidence)",
        "cumulative_weight = parent_quality['weight'] * edge_weight",
        "cumulative_confidence = parent_quality['confidence'] * edge_confidence",
        "depth_decay = 1.0 if depth == 1 else 0.65",
        "path_quality = cumulative_weight * cumulative_confidence * depth_decay",
        "'path_quality': max(0.0, min(path_quality, 1.0))",
        "return (payload, cumulative_weight, cumulative_confidence)",
    )

    interval = source_of(tree, "apply_personalized_interval")
    ordered(
        interval,
        "if not settings.ADAPTIVE_LEARNING_ENABLED or not "
        "settings.ADAPTIVE_INTERVAL_ENABLED:\n        return None",
        "user_factor = await _load_user_interval_factor(db, user_id)",
        "kp_ids = await _load_question_kp_ids(db, question_id)",
        "knowledge_factor = await _load_knowledge_interval_factor(db, user_id, kp_ids)",
        "difficulty_factor = await _load_difficulty_interval_factor(db, user_id, question_id)",
        "final_days = calculate_personalized_interval_days(",
        "await _override_next_review_at(",
        "return final_days",
    )

    knowledge = source_of(tree, "update_knowledge_interval_factor")
    ordered(
        knowledge,
        "if not knowledge_point_ids:\n        return",
        "if not is_due_review:\n        return",
        "state_map = await _load_knowledge_adaptive_states(db, user_id, knowledge_point_ids)",
        "await _ensure_knowledge_adaptive_states(db, user_id, knowledge_point_ids, state_map)",
        "for kp_id in dict.fromkeys(knowledge_point_ids):",
        "_adjust_knowledge_interval_state(",
        "await db.flush()",
    )

    difficulty = source_of(tree, "update_question_difficulty_state")
    ordered(
        difficulty,
        "state = await _get_or_create_difficulty(db, user_id, question_id)",
        "old_score = state.personal_difficulty_score",
        "new_score = _apply_difficulty_answer(",
        "state.last_updated_at = utcnow()",
        "await db.flush()",
        "_log_difficulty_change(user_id, question_id, old_score, new_score, state)",
        "return state",
    )

    overview = source_of(tree, "get_adaptive_overview")
    ordered(
        overview,
        "profile_result = await db.execute(",
        "interval_status = _interval_status(interval_factor)",
        "fast_forgetting_count = await _count_fast_forgetting_points(db, user_id)",
        "hard_count = await _count_user_hard_questions(db, user_id)",
        "path_blocked_count = await _count_path_blocked_knowledge(db, user_id)",
        "weights_adjusted, weight_summary = await _weight_status(db, user_id)",
        "return {",
    )

    hard = source_of(tree, "get_hard_questions")
    ordered(
        hard,
        "rows = (await db.execute(_hard_questions_statement(user_id, limit))).all()",
        "q_ids = [r.question_id for r in rows]",
        "kp_map, review_map = await _load_hard_question_labels(db, user_id, q_ids)",
        "items = [_hard_question_item(r, kp_map, review_map) for r in rows]",
        "return {'total': len(items), 'items': items}",
    )

    weights = source_of(tree, "adjust_recommend_weights")
    ordered(
        weights,
        "if not settings.ADAPTIVE_LEARNING_ENABLED or not "
        "settings.ADAPTIVE_WEIGHT_ENABLED:\n        return default_weights()",
        "pref = await _get_or_create_preference(db, user_id)",
        "recent_count, recent_correct = await _recent_practice_stats(",
        "if recent_count < 5:",
        "return _preference_weights(pref)",
        "due_count, due_correct = await _recent_due_stats(db, user_id, recent_start)",
        "adjustments = _weight_adjustments(",
        "_apply_weight_adjustments(pref, adjustments)",
        "pref.last_adjusted_at = now",
        "await db.flush()",
        "result_weights = _preference_weights(pref)",
        "_log_weight_adjustments(user_id, adjustments, result_weights)",
        "return result_weights",
    )

    after = source_of(tree, "update_adaptive_state_after_answer")
    ordered(
        after,
        "if not settings.ADAPTIVE_LEARNING_ENABLED:\n        return",
        "uqs = await _load_user_question_state(db, user_id, question_id)",
        "is_due_review, is_overdue_review = _resolve_review_flags(",
        "if settings.ADAPTIVE_INTERVAL_ENABLED and is_due_review:",
        "await _update_interval_factors(",
        "if settings.ADAPTIVE_DIFFICULTY_ENABLED:",
        "await _update_difficulty_from_answer(",
        "if not settings.ADAPTIVE_DRY_RUN and uqs is not None:",
        "await _apply_leitner_interval_override(db, user_id, question_id, uqs)",
    )

    factors = source_of(tree, "_update_interval_factors")
    ordered(
        factors,
        "await update_user_interval_factor(",
        "is_due_review=True",
        "kp_ids = await _load_question_kp_ids(db, question_id)",
        "if kp_ids:",
        "await update_knowledge_interval_factor(",
    )

    flags = source_of(tree, "_resolve_review_flags")
    ordered(
        flags,
        "nra = getattr(uqs, 'next_review_at', None) if uqs is not None else None",
        "if is_due_review is None:",
        "is_due_review = bool(nra is not None and answered_at >= nra)",
        "if is_overdue_review is None:",
        "is_overdue_review = bool(nra is not None and answered_at >= nra "
        "+ timedelta(days=1))",
        "return (is_due_review, is_overdue_review)",
    )

    selector = source_of(tree, "_hard_questions_statement")
    ordered(
        selector,
        "UserQuestionDifficultyState.question_id",
        "UserQuestionDifficultyState.personal_difficulty_score",
        "UserQuestionDifficultyState.difficulty_label",
        "UserQuestionDifficultyState.wrong_count",
        "UserQuestionDifficultyState.avg_answer_time_seconds",
        "UserQuestionDifficultyState.difficulty_label == 'hard'",
        "UserQuestionDifficultyState.personal_difficulty_score.desc()",
        ".limit(limit)",
    )

    labels = source_of(tree, "_load_hard_question_labels")
    ordered(
        labels,
        "if not q_ids:\n        return (kp_map, review_map)",
        "QuestionKnowledgePoint.question_id",
        "QuestionKnowledgePoint.knowledge_point_id",
        "KnowledgePoint.name",
        "QuestionKnowledgePoint.knowledge_point_id == KnowledgePoint.id",
        "QuestionKnowledgePoint.question_id.in_(q_ids)",
        "QuestionKnowledgePoint.question_id, QuestionKnowledgePoint.id",
        "if r.question_id not in kp_map:",
        "serialize_utc_datetime(r.next_review_at) if r.next_review_at else None",
    )
    assert labels.rstrip().endswith("return (kp_map, review_map)")

    recency = source_of(tree, "_recent_practice_stats")
    ordered(
        recency,
        "func.count(PracticeRecord.id)",
        "PracticeRecord.is_correct == True",
        "PracticeRecord.user_id == user_id",
        "PracticeRecord.answered_at >= recent_start",
        "recent_count, recent_correct = recent_result.one()",
        "return (int(recent_count or 0), int(recent_correct or 0))",
    )
    due = source_of(tree, "_recent_due_stats")
    ordered(
        due,
        "func.count(UserQuestionState.id)",
        "UserQuestionState.last_is_correct == True",
        "UserQuestionState.user_id == user_id",
        "UserQuestionState.last_answered_at >= recent_start",
        "return (int(due_count or 0), int(due_correct or 0))",
    )


def check_single_source(tree):
    """Thresholds, clamps and SQL scopes must live in exactly one helper."""

    def count(name, fragment):
        return source_of(tree, name).count(fragment)

    assert count("_bounded_graph_limits", "GRAPH_MAX_DEPTH") == 1
    assert count("_graph_relation_payload", "0.65") == 1
    assert count("_adjust_knowledge_interval_state", "_clamp(factor, 0.6, 1.6)") == 1
    assert count("_difficulty_delta", "delta += 4") == 1
    assert count("_difficulty_delta", "delta += 5") == 1
    assert count("_weight_adjustments", "due_accuracy < 0.6") == 1
    assert count("_weight_adjustments", "due_accuracy >= 0.85") == 1
    assert count("_weight_adjustments", "recent_accuracy < 0.5") == 1
    assert count("_weight_adjustments", "recent_count < 10") == 1
    assert count("_weight_adjustments", "recent_count > 30") == 1
    assert count("_interval_status", "0.98") == 1
    assert count("_interval_status", "1.1") == 1
    assert count("_record_graph_relation", "rel['depth'] == 1") == 1
    assert count("_graph_candidate_eligible", "rel['depth'] == 1") == 1

    delta_source = source_of(tree, "_difficulty_delta")
    for fragment in (
        "delta -= 4",
        "delta += 8",
        "delta += 3",
        "delta += 4",
        "delta -= 3",
        "delta += 5",
    ):
        assert fragment in delta_source, fragment

    # Entries and orchestration helpers must not inline SQL or thresholds.
    for name in tuple(name for name in ENTRIES if name != "get_adaptive_overview") + (
        "_update_interval_factors",
        "_apply_leitner_interval_override",
        "_expand_graph_layer",
        "_collect_graph_relations",
        "_record_graph_relation",
        "_keep_graph_candidate",
        "_project_graph_relations",
        "_ensure_knowledge_adaptive_states",
        "_apply_difficulty_answer",
    ):
        source = source_of(tree, name)
        assert "select(" not in source, name
        assert "db.execute(select(" not in source, name
        assert ".where(" not in source, name

    for name in ("_record_graph_relation", "_keep_graph_candidate", "_graph_context"):
        source = source_of(tree, name)
        assert "KnowledgeEdge" not in source, name
        assert "UserKnowledge" not in source, name

    # The question difficulty lookup lives only in its own loader helper.
    difficulty_probe = source_of(tree, "_update_difficulty_from_answer")
    assert difficulty_probe.count("select(Question.difficulty)") == 1
    assert difficulty_probe.count("update_question_difficulty_state(") == 1

    # The overview keeps exactly the pre-existing profile lookup inline.
    overview = source_of(tree, "get_adaptive_overview")
    assert overview.count("select(") == 1
    assert overview.count("db.execute(") == 1
    assert "UserAdaptiveProfile" in overview


def test_projection_helpers_stay_within_budget():
    check_budgets(load())


def test_entry_signatures_and_delegation_order():
    tree = load()
    check_signatures(tree)
    check_frozen_sources(tree)
    check_delegation(tree)


def test_thresholds_and_sql_have_a_single_source():
    check_single_source(load())


def test_gate_rejects_widened_graph_limits_and_reordered_recording():
    tree = load()
    limits = function(tree, "_bounded_graph_limits")
    for node in ast.walk(limits):
        if ast.unparse(node) == "GRAPH_MAX_DEPTH":
            node.value = None
            limits.body[2] = ast.parse(
                "bounded_depth = max(1, min(int(max_depth or 1), GRAPH_MAX_DEPTH + 1))"
            ).body[0]
            del node.value
            break
    with pytest.raises(AssertionError):
        check_frozen_sources(tree)

    tree = load()
    record = function(tree, "_record_graph_relation")
    body = [node for node in record.body if not isinstance(node, ast.Expr)]
    body.reverse()
    record.body = body
    with pytest.raises(AssertionError):
        check_delegation(tree)


def test_gate_rejects_relaxed_weight_and_difficulty_thresholds():
    tree = load()
    adjustments = function(tree, "_weight_adjustments")
    for node in ast.walk(adjustments):
        if isinstance(node, ast.Constant) and node.value == 0.6:
            node.value = 0.5
            break
    with pytest.raises(AssertionError):
        check_single_source(tree)

    tree = load()
    delta = function(tree, "_difficulty_delta")
    for node in ast.walk(delta):
        if isinstance(node, ast.Constant) and node.value == 8:
            node.value = 7
            break
    with pytest.raises(AssertionError):
        check_single_source(tree)


def test_gate_rejects_inline_sql_in_an_entry():
    tree = load()
    overview = function(tree, "get_adaptive_overview")
    overview.body.insert(
        3,
        ast.parse("await db.execute(select(KnowledgePoint.id))").body[0],
    )
    with pytest.raises(AssertionError):
        check_single_source(tree)
