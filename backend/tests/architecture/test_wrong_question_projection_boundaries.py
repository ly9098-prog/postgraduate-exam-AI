"""Guard the wrong-question service budgets, delegation and semantics.

The five entry points this batch split (``record_wrong``, ``get_stats``,
``list_wrong_enriched``, ``batch_operate``, ``get_task_flow``) keep byte-level
signatures and delegation order; thresholds, SQL scopes and the batch lock
ordering must each live in exactly one helper.
"""

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
SERVICE = APP / "services/wrong_question_service.py"
MODULE_TEXT = SERVICE.read_text(encoding="utf-8")

ENTRIES = (
    "record_wrong",
    "get_stats",
    "list_wrong_enriched",
    "batch_operate",
    "get_task_flow",
)

HELPERS = (
    "_load_wrong_question",
    "_reactivate_existing_wrong_question",
    "_new_wrong_question",
    "_wrong_book_conditions",
    "_wrong_stats_summary_statement",
    "_wrong_stats_summary",
    "_wrong_stats_by_error_type",
    "_wrong_stats_by_subject",
    "_today_due_statement_conditions",
    "_today_due_wrong_question_count",
    "_wrong_review_record_count_subquery",
    "_wrong_next_review_subquery",
    "_wrong_last_reviewed_subquery",
    "_wrong_mastery_pct_subquery",
    "_wrong_list_optional_conditions",
    "_wrong_list_base_query",
    "_apply_wrong_subject_scope",
    "_apply_wrong_topic_scope",
    "_wrong_mastery_percent",
    "_wrong_ai_analysis_status",
    "_wrong_list_item",
    "_dedupe_batch_ids",
    "_empty_batch_result",
    "_load_batch_wrong_questions",
    "_ordered_batch_wrong_questions",
    "_reactivate_wrong_question_row",
    "_rebind_wrong_review_schedule",
    "_force_schedule_due_now",
    "_add_wrong_question_to_review",
    "_batch_add_to_review",
    "_batch_set_mastered_state",
    "_batch_remove_from_book",
    "_batch_delete_wrong_questions",
    "_load_all_task_flow_items",
    "_task_flow_bucket",
    "_task_flow_groups",
    "_task_flow_summary",
)

SIGNATURES = {
    "record_wrong": (
        "(db, user_id, question_id, wrong_answer, question_version_id, commit)",
        "(True)",
    ),
    "get_stats": ("(db, user_id, allowed_subject_ids)", "(None)"),
    "list_wrong_enriched": (
        "(db, user_id, subject_id, error_type, topic, page, page_size, "
        "allowed_subject_ids, date_from, date_to)",
        "(None, None, None, 1, 20, None, None, None)",
    ),
    "batch_operate": ("(db, user_id, action, ids)", "()"),
    "get_task_flow": (
        "(db, user_id, subject_id, error_type, topic, preview_size, "
        "allowed_subject_ids, date_from, date_to)",
        "(None, None, None, 3, None, None, None)",
    ),
}


def load():
    return ast.parse(MODULE_TEXT)


def function(tree, name):
    return next(node for node in tree.body if getattr(node, "name", "") == name)


def source_of(tree, name):
    return ast.unparse(function(tree, name))


def signature_of(node):
    args = list(node.args.posonlyargs) + list(node.args.args)
    args += list(node.args.kwonlyargs)
    return "(" + ", ".join(argument.arg for argument in args) + ")"


def defaults_of(node):
    values = [value for value in node.args.defaults + node.args.kw_defaults if value]
    return "(" + ", ".join(ast.unparse(value) for value in values) + ")"


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
        for argument in node.args.kwonlyargs:
            assert argument.annotation is not None, (name, argument.arg)


FROZEN_SOURCES = {
    "_dedupe_batch_ids": 'def _dedupe_batch_ids(ids: list[int]) -> list[int]:\n    """Deduplicate ids while preserving first-seen order."""\n    seen: set[int] = set()\n    return [x for x in ids if not (x in seen or seen.add(x))]',
    "_ordered_batch_wrong_questions": "def _ordered_batch_wrong_questions(wqs: dict[int, WrongQuestion]) -> list[tuple[int, WrongQuestion]]:\n    return sorted(wqs.items(), key=lambda pair: (pair[1].question_id, pair[0]))",
    "_reactivate_wrong_question_row": "def _reactivate_wrong_question_row(wq: WrongQuestion) -> bool:\n    changed = False\n    if not wq.is_active:\n        wq.is_active = True\n        wq.removed_at = None\n        changed = True\n    if wq.mastered:\n        wq.mastered = False\n        wq.mastered_at = None\n        changed = True\n    return changed",
    "_force_schedule_due_now": "def _force_schedule_due_now(schedule: ReviewSchedule, rebound: bool) -> bool:\n    changed = False\n    now = utcnow()\n    if not schedule.is_active:\n        schedule.is_active = True\n        changed = True\n    if schedule.mastered:\n        schedule.mastered = False\n        changed = True\n    if schedule.next_review_at is None or schedule.next_review_at > now:\n        schedule.next_review_at = now\n        if not rebound:\n            schedule.occurrence_seq = int(schedule.occurrence_seq or 0) + 1\n        changed = True\n    return changed",
    "_task_flow_bucket": "def _task_flow_bucket(item: dict, today_end, fourteen_days_ago) -> str:\n    \"\"\"Priority-deduplicated bucket key for one wrong-book list item.\"\"\"\n    if item['next_review_at'] and item['next_review_at'] <= today_end and (not item['is_mastered']):\n        return 'today_due'\n    if item['wrong_count'] >= _TASK_FLOW_HIGH_FREQUENCY_MIN and (not item['is_mastered']):\n        return 'high_frequency'\n    if item['created_at'] and item['created_at'] >= fourteen_days_ago and (not item['is_mastered']):\n        return 'recent_added'\n    if not item['is_mastered']:\n        return 'to_consolidate'\n    return 'mastered'",
    "_task_flow_groups": "def _task_flow_groups(buckets: dict[str, list[dict]], preview_size: int) -> list[dict]:\n    return [{'key': key, 'title': title, 'total': len(buckets[key]), 'items': buckets[key][:preview_size]} for key, title in _TASK_FLOW_GROUPS]",
    "_task_flow_summary": "def _task_flow_summary(all_items: list[dict], total_count: int, today_due_count: int) -> dict:\n    return {'total_count': total_count, 'mastered_count': sum((1 for item in all_items if item['is_mastered'])), 'high_frequency_count': sum((1 for item in all_items if item['wrong_count'] >= _TASK_FLOW_HIGH_FREQUENCY_MIN and (not item['is_mastered']))), 'today_due_count': today_due_count}",
    "_wrong_mastery_percent": "def _wrong_mastery_percent(wq: WrongQuestion, mastery_pct) -> float:\n    if wq.mastered:\n        return 1.0\n    return round(float(mastery_pct if mastery_pct is not None else 0.2), 4)",
    "_wrong_ai_analysis_status": "def _wrong_ai_analysis_status(ai_analysis) -> str:\n    return 'ready' if isinstance(ai_analysis, dict) and ai_analysis else 'empty'",
}


def check_frozen_sources(tree):
    for name, expected in FROZEN_SOURCES.items():
        assert source_of(tree, name) == expected, name


def check_delegation(tree):
    record = source_of(tree, "record_wrong")
    ordered(
        record,
        "await review_scheduler.lock_question_review_state(",
        "wq = await _load_wrong_question(db, user_id, question_id)",
        "_reactivate_existing_wrong_question(wq, wrong_answer, question_version_id)",
        "wq = _new_wrong_question(",
        "db.add(wq)",
        "await review_scheduler.auto_schedule_wrong_question(",
        "if not commit:",
        "await db.flush()",
        "await db.refresh(wq)",
        "return wq",
    )

    stats = source_of(tree, "get_stats")
    ordered(
        stats,
        "conditions = _wrong_book_conditions(user_id, allowed_subject_ids)",
        "total, unmastered, mastered, high_frequency_count = await _wrong_stats_summary(",
        "by_error_type = await _wrong_stats_by_error_type(db, conditions)",
        "by_subject = await _wrong_stats_by_subject(db, conditions)",
        "today_due_count = await _today_due_wrong_question_count(",
        "return {",
    )

    listing = source_of(tree, "list_wrong_enriched")
    ordered(
        listing,
        "conditions = _wrong_book_conditions(user_id, allowed_subject_ids)",
        "conditions.extend(_wrong_list_optional_conditions(",
        "base_query = _wrong_list_base_query(conditions)",
        "base_query = await _apply_wrong_subject_scope(db, base_query, subject_id)",
        "base_query = _apply_wrong_topic_scope(base_query, topic)",
        "base_query.order_by(",
        "total_q = select(func.count()).select_from(base_query.subquery())",
        "q = base_query.offset((page - 1) * page_size).limit(page_size)",
        "rows = (await db.execute(q)).all()",
        "kp_map = await load_question_kps(db, question_ids)",
        "items = [_wrong_list_item(row, kp_map) for row in rows]",
        "return (items, total)",
    )

    batch = source_of(tree, "batch_operate")
    ordered(
        batch,
        "deduped_ids = _dedupe_batch_ids(ids)",
        "return _empty_batch_result(action)",
        "wqs, not_found_ids = await _load_batch_wrong_questions(db, user_id, deduped_ids)",
        "ordered_wqs = _ordered_batch_wrong_questions(wqs)",
        "if action == 'add_to_review':",
        "await _batch_add_to_review(",
        "elif action in ('mark_mastered', 'unmark_mastered'):",
        "await _batch_set_mastered_state(",
        "mastered=action == 'mark_mastered'",
        "elif action == 'remove_from_book':",
        "await _batch_remove_from_book(",
        "elif action == 'delete':",
        "await _batch_delete_wrong_questions(",
        "updated_count, skipped_ids = (0, [])",
        "skipped_ids.extend(not_found_ids)",
        "await db.commit()",
        "return {",
    )

    add_one = source_of(tree, "_add_wrong_question_to_review")
    ordered(
        add_one,
        "from app.services import review_scheduler",
        "async with db.begin_nested():",
        "await review_scheduler.lock_question_review_state(",
        "changed = _reactivate_wrong_question_row(wq)",
        "schedule, rebound = await _rebind_wrong_review_schedule(db, user_id, wq)",
        "changed = _force_schedule_due_now(schedule, rebound) or changed",
        "return changed",
    )

    rebind = source_of(tree, "_rebind_wrong_review_schedule")
    ordered(
        rebind,
        "schedule = await db.scalar(",
        "if schedule is not None and int(schedule.question_version_id) == int(",
        "return (schedule, False)",
        "schedule = await review_scheduler.auto_schedule_wrong_question(",
        "return (schedule, True)",
    )

    force = source_of(tree, "_force_schedule_due_now")
    ordered(
        force,
        "now = utcnow()",
        "if not schedule.is_active:",
        "if schedule.mastered:",
        "if schedule.next_review_at is None or schedule.next_review_at > now:",
        "schedule.next_review_at = now",
        "if not rebound:",
        "schedule.occurrence_seq = int(schedule.occurrence_seq or 0) + 1",
        "return changed",
    )

    mastered = source_of(tree, "_batch_set_mastered_state")
    ordered(
        mastered,
        "for wq_id, wq in ordered_wqs:",
        "if not wq.is_active:",
        "skipped_ids.append(wq_id)",
        "continue",
        "changed = await review_scheduler.set_mastered_state(",
        "return (updated_count, skipped_ids)",
    )

    remove = source_of(tree, "_batch_remove_from_book")
    ordered(
        remove,
        "now = utcnow()",
        "await review_scheduler.lock_question_review_state(",
        "if not wq.is_active:",
        "wq.is_active = False",
        "wq.removed_at = now",
        "schedule = await db.scalar(",
        "schedule.is_active = False",
        "schedule.occurrence_seq = int(schedule.occurrence_seq or 0) + 1",
        "return (updated_count, skipped_ids)",
    )

    delete = source_of(tree, "_batch_delete_wrong_questions")
    ordered(
        delete,
        "await review_scheduler.lock_question_review_state(",
        "delete(ReviewRecord)",
        "delete(ReviewSchedule)",
        "delete(WrongQuestion)",
        "return (len(ordered_wqs), [])",
    )

    loader = source_of(tree, "_load_all_task_flow_items")
    ordered(
        loader,
        "all_items: list[dict] = []",
        "while True:",
        "page_items, total_count = await list_wrong_enriched(",
        "page_size=_TASK_FLOW_PAGE_SIZE",
        "all_items.extend(page_items)",
        "if not page_items or len(all_items) >= total_count:",
        "page += 1",
        "return (all_items, total_count)",
    )

    bucket = source_of(tree, "_task_flow_bucket")
    ordered(
        bucket,
        "return 'today_due'",
        "return 'high_frequency'",
        "return 'recent_added'",
        "return 'to_consolidate'",
        "return 'mastered'",
    )

    flow = source_of(tree, "get_task_flow")
    ordered(
        flow,
        "_, today_end = shanghai_today_boundaries()",
        "fourteen_days_ago = utcnow() - timedelta(days=_TASK_FLOW_RECENT_DAYS)",
        "all_items, total_count = await _load_all_task_flow_items(",
        "buckets: dict[str, list[dict]] = {key: [] for key, _ in _TASK_FLOW_GROUPS}",
        "buckets[_task_flow_bucket(item, today_end, fourteen_days_ago)].append(item)",
        "return {",
        "'summary': _task_flow_summary(",
        "'groups': _task_flow_groups(buckets, preview_size)",
    )

    add_all = source_of(tree, "_batch_add_to_review")
    ordered(
        add_all,
        "for wq_id, wq in ordered_wqs:",
        "try:",
        "if await _add_wrong_question_to_review(db, user_id, wq):",
        "updated_count += 1",
        "else:",
        "except Exception:",
        "return (updated_count, skipped_ids)",
    )
    # The swallow-all branch must land in skipped_ids, never in updated_count.
    swallow_tail = add_all.split("except Exception:", 1)[1].split("return ", 1)[0]
    assert "skipped_ids.append(wq_id)" in swallow_tail
    assert "updated_count" not in swallow_tail


def check_single_source(tree):
    """Thresholds, bucket keys and SQL scopes must each live in one place."""

    def count(name, fragment):
        return source_of(tree, name).count(fragment)

    assert count("_task_flow_bucket", "_TASK_FLOW_HIGH_FREQUENCY_MIN") == 1
    assert count("_task_flow_summary", "_TASK_FLOW_HIGH_FREQUENCY_MIN") == 1
    assert MODULE_TEXT.count("_TASK_FLOW_HIGH_FREQUENCY_MIN") == 3
    assert MODULE_TEXT.count("_TASK_FLOW_RECENT_DAYS") == 2
    assert MODULE_TEXT.count("_TASK_FLOW_PAGE_SIZE") == 2
    assert "wrong_count >= 3" not in MODULE_TEXT
    for title in ("今日应复习", "高频错题", "最近新增", "待巩固", "已经掌握"):
        assert MODULE_TEXT.count(title) == 1, title
    assert MODULE_TEXT.count('"today_due"') == 3
    assert MODULE_TEXT.count('"high_frequency"') == 2
    assert MODULE_TEXT.count('"recent_added"') == 2
    assert MODULE_TEXT.count('"to_consolidate"') == 2
    assert MODULE_TEXT.count('"mastered"') == 4

    # Entry points orchestrate; they must not inline SQL or savepoints.
    for name in ("record_wrong", "get_stats", "batch_operate", "get_task_flow"):
        source = source_of(tree, name)
        assert "select(" not in source, name
        assert ".where(" not in source, name
    listing = source_of(tree, "list_wrong_enriched")
    assert listing.count("select(") == 1
    assert "delete(" not in listing

    batch = source_of(tree, "batch_operate")
    assert batch.count("await db.commit()") == 1
    assert "begin_nested" not in batch

    # Batch delete/removal keep their own statement scopes in one helper.
    assert count("_batch_delete_wrong_questions", "delete(") == 3
    assert count("_batch_remove_from_book", "occurrence_seq") == 2
    assert count("_force_schedule_due_now", "occurrence_seq") == 2
    assert count("_rebind_wrong_review_schedule", "db.scalar(") == 1
    assert count("_add_wrong_question_to_review", "begin_nested") == 1
    assert MODULE_TEXT.count("from app.services import review_scheduler") == 6

    # The list-item projection keeps the single source of the mastery floor.
    item = source_of(tree, "_wrong_list_item")
    assert item.count("_wrong_mastery_percent(") == 1
    assert item.count("_wrong_ai_analysis_status(") == 1


def test_projection_helpers_stay_within_budget():
    check_budgets(load())


def test_entry_signatures_and_delegation_order():
    tree = load()
    check_signatures(tree)
    check_frozen_sources(tree)
    check_delegation(tree)


def test_thresholds_and_sql_have_a_single_source():
    check_single_source(load())


def test_gate_rejects_widened_task_flow_threshold():
    tree = load()
    bucket = function(tree, "_task_flow_bucket")
    for node in ast.walk(bucket):
        if isinstance(node, ast.Name) and node.id == "_TASK_FLOW_HIGH_FREQUENCY_MIN":
            node.id = "2"
            node.ctx = ast.Load()
            break
    with pytest.raises(AssertionError):
        check_frozen_sources(tree)


def test_gate_rejects_reordered_batch_commit():
    tree = load()
    batch = function(tree, "batch_operate")
    body = [
        node
        for node in batch.body
        if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))
    ]
    commit_index = next(
        index
        for index, node in enumerate(body)
        if ast.unparse(node) == "await db.commit()"
    )
    extend_index = next(
        index
        for index, node in enumerate(body)
        if ast.unparse(node) == "skipped_ids.extend(not_found_ids)"
    )
    body[commit_index], body[extend_index] = body[extend_index], body[commit_index]
    batch.body = body
    with pytest.raises(AssertionError):
        check_delegation(tree)


def test_gate_rejects_inline_sql_in_batch_operate():
    tree = load()
    batch = function(tree, "batch_operate")
    batch.body.insert(
        2,
        ast.parse("await db.execute(select(KnowledgePoint.id))").body[0],
    )
    with pytest.raises(AssertionError):
        check_single_source(tree)


def test_gate_rejects_missing_inactive_guard_in_remove():
    tree = load()
    remove = function(tree, "_batch_remove_from_book")
    for node in ast.walk(remove):
        if isinstance(node, ast.If) and ast.unparse(node.test) == "not wq.is_active":
            node.test = ast.Constant(value=False)
            break
    with pytest.raises(AssertionError):
        check_delegation(tree)


def test_gate_rejects_exclusive_task_flow_summary():
    tree = load()
    summary = function(tree, "_task_flow_summary")
    for node in ast.walk(summary):
        if isinstance(node, ast.BoolOp) and ast.unparse(node) == (
            "item['wrong_count'] >= _TASK_FLOW_HIGH_FREQUENCY_MIN "
            "and (not item['is_mastered'])"
        ):
            node.values = node.values[:1]
            break
    with pytest.raises(AssertionError):
        check_frozen_sources(tree)
