"""Guard AI learning service delegation, budgets and branch semantics."""

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
SERVICE = APP / "services/ai_learning_service.py"
ENTRY = "generate_learning_report"
DETAIL_ENTRIES = ("ai_explain", "ai_analyze_mistake", "recommend_similar_questions")
HELPERS = (
    "_load_active_question",
    "_question_stem",
    "_explain_unavailable_payload",
    "_explain_success_payload",
    "_build_explain_messages",
    "_mistake_unavailable_payload",
    "_mistake_success_payload",
    "_build_mistake_messages",
    "_vector_recommendation_payload",
    "_load_answered_question_ids",
    "_load_similar_candidates",
    "_score_similar_candidates",
    "_select_top_scored",
    "_similar_recommendation_payload",
    "_rule_recommendation_payload",
    "_load_learning_report_subject",
    "_load_learning_report_records",
    "_empty_learning_report",
    "_knowledge_point_accuracy_list",
    "_report_weak_points",
    "_report_strong_points",
    "_low_volume_learning_report",
    "_token_limited_learning_report",
    "_ai_fallback_learning_report",
    "_project_parsed_report_points",
    "_ai_learning_report",
    "_learning_report_metrics",
)


def load():
    return ast.parse(SERVICE.read_text())


def function(tree, name):
    return next(node for node in tree.body if getattr(node, "name", "") == name)


def source_of(tree, name):
    return ast.unparse(function(tree, name))


def ordered(source, *items):
    for item in items:
        assert item in source, item
    indexes = [source.index(item) for item in items]
    assert indexes == sorted(indexes), items


def check_budgets(tree):
    for name in (ENTRY,) + DETAIL_ENTRIES + HELPERS:
        node = function(tree, name)
        assert node.end_lineno - node.lineno + 1 <= 50, name


def check_detail_entries(tree):
    explain = source_of(tree, "ai_explain")
    ordered(
        explain,
        "q = await _load_active_question(db, question_id)",
        "kp_map = await load_question_kps(db, [q.id])",
        "messages = _build_explain_messages(",
        "if not await check_token_limit(db, user_id, 500):",
        "return _explain_unavailable_payload(",
        "result = await _call_ai(messages, db)",
        "if result is None:",
        "await record_token_usage(",
        "return _explain_success_payload(",
    )
    for forbidden in ("db.execute", "select(", "build_explain_prompt("):
        assert forbidden not in explain, forbidden

    mistake = source_of(tree, "ai_analyze_mistake")
    ordered(
        mistake,
        "q = await _load_active_question(db, question_id)",
        "messages = _build_mistake_messages(",
        "if not await check_token_limit(db, user_id, 300):",
        "return _mistake_unavailable_payload(",
        "result = await _call_ai(messages, db)",
        "if result is None:",
        "await record_token_usage(",
        "return _mistake_success_payload(",
    )
    for forbidden in ("db.execute", "select(", "build_mistake_analysis_prompt("):
        assert forbidden not in mistake, forbidden

    recommendation = source_of(tree, "recommend_similar_questions")
    ordered(
        recommendation,
        "vector_payload = await _vector_recommendation_payload(",
        "if vector_payload is not None:",
        "q = await _load_active_question(db, question_id)",
        "answered_ids = await _load_answered_question_ids(",
        "candidates = await _load_similar_candidates(",
        "kp_map = await load_question_kps(",
        "scored = _score_similar_candidates(",
        "top = _select_top_scored(scored, count)",
        "return _rule_recommendation_payload(",
    )
    for forbidden in (
        "db.execute",
        "select(",
        "PracticeRecord",
        "resolve_subject_ids(",
        "random.shuffle(",
    ):
        assert forbidden not in recommendation, forbidden


def check_detail_helpers(tree):
    loader = source_of(tree, "_load_active_question")
    assert "Question.id == question_id" in loader
    assert "Question.is_active" in loader
    assert "raise ValueError('题目不存在')" in loader

    stem = source_of(tree, "_question_stem")
    assert "question.content.get('text', '')" in stem
    assert "str(question.content or '')" in stem

    explain_payload = source_of(tree, "_explain_unavailable_payload")
    assert "'tokens_used': 0" in explain_payload
    assert "'from_fallback': True" in explain_payload
    assert "'key_knowledge_points': knowledge_points" in explain_payload

    mistake_payload = source_of(tree, "_mistake_unavailable_payload")
    assert "'tokens_used': 0" in mistake_payload
    assert "'from_fallback': True" in mistake_payload

    vector = source_of(tree, "_vector_recommendation_payload")
    ordered(
        vector,
        "vector_result = await vector_retrieval_service.search_similar_questions(",
        "if vector_result.get('enabled') and vector_result.get('recommendations'):",
        "'strategy': 'vector_plus_rule'",
        "except Exception:",
        "logger.warning('向量推荐异常，回退到规则推荐', exc_info=True)",
        "return None",
    )

    answered = source_of(tree, "_load_answered_question_ids")
    ordered(
        answered,
        "select(PracticeRecord.question_id)",
        "PracticeRecord.user_id == user_id",
        "answered_ids.add(question_id)",
    )

    candidates = source_of(tree, "_load_similar_candidates")
    ordered(
        candidates,
        "Question.subject_id.in_(await resolve_subject_ids(",
        "Question.is_active",
        "Question.review_status == 'approved'",
        "return candidates_result.scalars().all()",
    )

    scoring = source_of(tree, "_score_similar_candidates")
    ordered(
        scoring,
        "if candidate.id in answered_ids:",
        "kp_overlap = len(source_kps & candidate_kps)",
        "difficulty_match = 1 if candidate.difficulty == source_difficulty else 0",
        "score = kp_overlap * 2 + difficulty_match",
        "if score > 0:",
    )

    selection = source_of(tree, "_select_top_scored")
    ordered(
        selection,
        "scored.sort(key=lambda item: item[0], reverse=True)",
        "top = scored[:count]",
        "random.shuffle(top)",
    )

    projection = source_of(tree, "_similar_recommendation_payload")
    ordered(
        projection,
        "if set(kps) & source_kps:",
        "if candidate.difficulty == source_difficulty:",
        "if not match_reasons:",
        "match_reasons.append('同科目')",
        "return {",
    )

    envelope = source_of(tree, "_rule_recommendation_payload")
    assert "'strategy': 'rule_based'" in envelope
    assert "'tokens_used': 0" in envelope


def check_entry(tree):
    entry = source_of(tree, ENTRY)
    ordered(
        entry,
        "= await _load_learning_report_subject(db, subject_id)",
        "since = utcnow() - timedelta(days=days)",
        "records = await _load_learning_report_records(db, user_id, subject_id, since)",
        "total = len(records)",
        "if total == 0:",
        "return _empty_learning_report(subject_payload, days)",
        "accuracy, kp_list = await _learning_report_metrics(db, records, total)",
        "if total < 5:",
        "return _low_volume_learning_report(",
        "messages = build_report_prompt(subject_code, days, total, accuracy, kp_list)",
        "if not await check_token_limit(db, user_id, 1000):",
        "return _token_limited_learning_report(",
        "result = await _call_ai(messages, db)",
        "if result is None:",
        "return _ai_fallback_learning_report(",
        "return await _ai_learning_report(",
    )
    for forbidden in (
        "db.get(",
        "select(",
        "PracticeRecord",
        "record_token_usage",
        "_parse_json_response",
    ):
        assert forbidden not in entry, forbidden


def check_subject_and_records(tree):
    subject = source_of(tree, "_load_learning_report_subject")
    ordered(
        subject,
        "from app.models.admin import Subject",
        "subj = await db.get(Subject, subject_id)",
        "subject_code = subj.code if subj else ''",
        "subject_name = subj.name if subj else ''",
        "subject_payload = {",
        "return (subject_code, subject_name, subject_payload)",
    )

    records = source_of(tree, "_load_learning_report_records")
    ordered(
        records,
        "PracticeRecord.question_id",
        "PracticeRecord.is_correct",
        "PracticeRecord.user_id == user_id",
        "PracticeRecord.subject_id == subject_id",
        "PracticeRecord.answered_at >= since",
        ".order_by(PracticeRecord.answered_at.desc())",
        "return records_result.all()",
    )
    assert "is_correct=is_correct" not in records


def check_metrics_and_aggregation(tree):
    metrics = source_of(tree, "_learning_report_metrics")
    ordered(
        metrics,
        "correct = sum((1 for r in records if r.is_correct))",
        "accuracy = correct / total if total > 0 else 0.0",
        "qids = list({r.question_id for r in records})",
        "q_map = await load_question_kps(db, qids)",
        "_knowledge_point_accuracy_list(records, q_map)",
        "return (accuracy, kp_list)",
    )

    aggregation = source_of(tree, "_knowledge_point_accuracy_list")
    ordered(
        aggregation,
        "kp_stats: dict[str, dict] = {}",
        "kp_stats[kp]['total'] += 1",
        "if r.is_correct:",
        "kp_stats[kp]['correct'] += 1",
        "'accuracy': stats['correct'] / stats['total'] if stats['total'] > 0 else 0",
        "kp_list.sort(key=lambda x: x['accuracy'])",
        "return kp_list",
    )

    assert metrics.count("load_question_kps(") == 1


def check_rule_branches(tree):
    empty = source_of(tree, "_empty_learning_report")
    assert "'learning_suggestions': ['暂无做题记录，建议开始练习。']" in empty
    assert "'from_fallback': True" in empty and "'tokens_used': 0" in empty

    weak = source_of(tree, "_report_weak_points")
    assert "if k['accuracy'] < 0.6" in weak and "[:limit]" in weak
    strong = source_of(tree, "_report_strong_points")
    assert "if k['accuracy'] >= 0.85" in strong and "'继续保持'" in strong

    low_volume = source_of(tree, "_low_volume_learning_report")
    ordered(
        low_volume,
        "limit=3, suggestion='数据不足，继续练习以获取更准确的建议'",
        "strong = _report_strong_points(kp_list, limit=3)",
        "'数据较少，建议积累更多练习记录后再查看 AI 报告。'",
        "'from_fallback': False",
    )

    token_limited = source_of(tree, "_token_limited_learning_report")
    ordered(
        token_limited,
        "limit=5, suggestion='建议重点复习该知识点'",
        "strong = _report_strong_points(kp_list, limit=3)",
        "f'薄弱知识点有 {len(weak)} 个，建议每天重点练习'",
        "'尝试做更多同类题目的变体练习'",
        "'from_fallback': True",
    )

    fallback = source_of(tree, "_ai_fallback_learning_report")
    ordered(
        fallback,
        "fallback = get_fallback_report()",
        "fallback.get('weak_points', [])",
        "fallback.get('strong_points', [])",
        "fallback.get('learning_suggestions', [])",
        "'tokens_used': 0",
        "'from_fallback': True",
    )


def check_ai_path(tree):
    report = source_of(tree, "_ai_learning_report")
    ordered(
        report,
        "parsed = _parse_json_response(result['content'])",
        "if parsed is None:",
        "'learning_suggestions': [result['content']]",
        "await record_token_usage(",
        "'learning_report'",
        "f'subject_id={subject_id} days={days}'",
        "weak_points, strong_points = _project_parsed_report_points(parsed)",
        "'learning_suggestions': parsed.get('learning_suggestions', [])",
        "'tokens_used': result['tokens_used']",
        "'from_fallback': False",
    )

    projection = source_of(tree, "_project_parsed_report_points")
    ordered(
        projection,
        "weak_points = []",
        "'suggestion': wp.get('suggestion', '')",
        "strong_points = []",
        "'suggestion': sp.get('suggestion', '')",
        "return (weak_points, strong_points)",
    )


def test_ai_learning_report_helpers_stay_within_budget():
    check_budgets(load())


def test_ai_learning_service_delegation_and_copy_semantics():
    tree = load()
    check_detail_entries(tree)
    check_detail_helpers(tree)
    check_entry(tree)
    check_subject_and_records(tree)
    check_metrics_and_aggregation(tree)
    check_rule_branches(tree)
    check_ai_path(tree)


def test_gate_rejects_inlined_select_and_widened_low_volume_copy():
    tree = load()
    entry = function(tree, ENTRY)
    marker = ast.parse(
        "records = await db.execute(select(PracticeRecord.question_id))"
    ).body[0]
    entry.body.insert(3, marker)
    with pytest.raises(AssertionError):
        check_entry(tree)

    tree = load()
    low_volume = function(tree, "_low_volume_learning_report")
    for node in ast.walk(low_volume):
        if isinstance(node, ast.Call) and ast.unparse(node).startswith(
            "_report_weak_points("
        ):
            node.keywords[1].value = ast.Constant(value="mutant copy")
            break
    with pytest.raises(AssertionError):
        check_rule_branches(tree)


def test_gate_rejects_inlined_recommendation_query_and_missing_shuffle():
    tree = load()
    recommendation = function(tree, "recommend_similar_questions")
    marker = ast.parse(
        "answered_result = await db.execute(select(PracticeRecord.question_id))"
    ).body[0]
    recommendation.body.insert(2, marker)
    with pytest.raises(AssertionError):
        check_detail_entries(tree)

    tree = load()
    selection = function(tree, "_select_top_scored")
    for node in ast.walk(selection):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            if ast.unparse(node.value.func) == "random.shuffle":
                node.value.func = ast.Name(id="list.append")
                break
    with pytest.raises(AssertionError):
        check_detail_helpers(tree)
