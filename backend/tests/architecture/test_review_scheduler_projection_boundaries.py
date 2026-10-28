"""Guard the review-scheduler budgets, delegation order and single-source rules.

The eleven entry points this batch split (``grade_batch_review``, ``submit_review``,
``_get_today_review_task_state``, ``get_review_stats``, ``get_today_review_result``,
``_prepare_latest_review_revisions``, ``_record_review_session``,
``set_mastered_state``, ``get_today_review_overview``, ``get_today_review``,
``auto_schedule_wrong_question``) keep byte-level signatures and delegation order.
SM-2 application, today's task union, the review-session best-effort boundary and the
per-subject statistics scopes must each live in exactly one helper.
"""

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
SERVICE = APP / "services/review_scheduler.py"
MODULE_TEXT = SERVICE.read_text(encoding="utf-8")

ENTRIES = (
    "grade_batch_review",
    "submit_review",
    "_get_today_review_task_state",
    "get_review_stats",
    "get_today_review_result",
    "_prepare_latest_review_revisions",
    "_record_review_session",
    "set_mastered_state",
    "get_today_review_overview",
    "get_today_review",
    "auto_schedule_wrong_question",
)

HELPERS = (
    "_latest_revision_candidates",
    "_latest_revision_view",
    "_log_missing_review_revision",
    "_lock_and_rebind_latest_revision",
    "_rebind_if_stale",
    "_apply_manual_mastery_to_wrong_question",
    "_toggle_schedule_mastery",
    "_restore_review_schedule",
    "_apply_manual_mastery_to_schedule",
    "_today_review_conditions",
    "_valid_revision_schedule_filters",
    "_count_today_review_schedules",
    "_load_today_review_schedules",
    "_validate_review_replay",
    "_review_replay_payload",
    "_resolve_review_replay",
    "_load_locked_review_schedule",
    "_apply_sm2_update",
    "_maybe_update_user_question_state",
    "_build_review_record",
    "_review_submit_payload",
    "_apply_review_grade",
    "_review_session_subject_map",
    "_review_session_stats_by_subject",
    "_review_session_already_recorded",
    "_add_review_session_rows",
    "_batch_review_missing_payload",
    "_batch_review_question_answer",
    "_batch_review_success_payload",
    "_batch_review_error_payload",
    "_batch_review_prewarm_candidate",
    "_grade_batch_review_item",
    "_prewarm_review_wrong_answers",
    "_ordered_review_items",
    "_grade_batch_review_loop",
    "_count_active_review_schedules",
    "_count_reviews_between",
    "_count_remaining_today",
    "_count_overdue_reviews",
    "_review_accuracy_since",
    "_review_schedule_subject_rows",
    "_reviewed_by_subject_today",
    "_subject_code_names",
    "_review_stats_by_subject",
    "_load_wrong_question_revision",
    "_first_wrong_review_at",
    "_new_wrong_review_schedule",
    "_reset_wrong_review_schedule",
    "_today_due_review_statement",
    "_today_due_review_schedules",
    "_today_reviewed_rows",
    "_today_reviewed_schedules",
    "_today_mastered_schedules",
    "_merge_today_task_schedules",
    "_today_mastered_question_ids",
    "_today_reviewed_context",
    "_pending_today_schedules",
    "_today_review_overdue_split",
    "_today_review_batch_metrics",
    "_today_result_records",
    "_dedupe_records_by_question",
    "_today_result_subject_stats",
    "_tomorrow_due_count",
    "_today_result_metrics",
    "_today_completion_metrics",
)

SQL_FREE_ENTRIES = (
    "grade_batch_review",
    "submit_review",
    "_get_today_review_task_state",
    "get_review_stats",
    "get_today_review_result",
    "_prepare_latest_review_revisions",
    "_record_review_session",
    "get_today_review_overview",
    "get_today_review",
)

SIGNATURES = {
    "grade_batch_review": ("(db, user_id, reviews, session_meta)", "(None)"),
    "submit_review": (
        "(db, user_id, schedule_id, question_id, question_version_id, occurrence_seq, rating, request_id, auto_commit, user_answer, latest_wrong_answer)",
        "(True, None, None)",
    ),
    "_get_today_review_task_state": ("(db, user_id)", "()"),
    "get_review_stats": ("(db, user_id, days)", "(7)"),
    "get_today_review_result": ("(db, user_id)", "()"),
    "_prepare_latest_review_revisions": ("(db, user_id, schedules)", "()"),
    "_record_review_session": ("(db, user_id, session_meta, results)", "()"),
    "set_mastered_state": ("(db, user_id, question_id, mastered)", "()"),
    "get_today_review_overview": ("(db, user_id)", "()"),
    "get_today_review": ("(db, user_id, subject_id, limit)", "(None, 20)"),
    "auto_schedule_wrong_question": (
        "(db, user_id, question_id, question_version_id, commit)",
        "(True)",
    ),
}

FROZEN_SOURCES = {
    "_first_wrong_review_at": "def _first_wrong_review_at() -> datetime:\n    first_review_date = shanghai_today() + timedelta(days=1)\n    return shanghai_date_utc_range(first_review_date)[0]",
    "_active_408_subject_ids": "async def _active_408_subject_ids(db: AsyncSession) -> set[int]:\n    result = await db.execute(select(Subject))\n    return selected_408_subject_ids(result.scalars().all())",
    "_count_remaining_today": "async def _count_remaining_today(db: AsyncSession, user_id: int, today_end: datetime):\n    q = select(func.count(func.distinct(ReviewSchedule.question_id))).where(ReviewSchedule.user_id == user_id, ReviewSchedule.is_active, ReviewSchedule.next_review_at <= today_end, ~ReviewSchedule.mastered)\n    return (await db.execute(q)).scalar()",
    "_count_overdue_reviews": "async def _count_overdue_reviews(db: AsyncSession, user_id: int, today_start: datetime):\n    q = select(func.count(func.distinct(ReviewSchedule.question_id))).where(ReviewSchedule.user_id == user_id, ReviewSchedule.is_active, ReviewSchedule.next_review_at < today_start, ~ReviewSchedule.mastered)\n    return (await db.execute(q)).scalar()",
    "_tomorrow_due_count": "async def _tomorrow_due_count(db: AsyncSession, user_id: int, tomorrow_start: datetime) -> int:\n    tomorrow_end = tomorrow_start + timedelta(days=1) - timedelta(microseconds=1)\n    tomorrow_q = await db.execute(select(func.count(func.distinct(ReviewSchedule.question_id))).where(ReviewSchedule.user_id == user_id, ReviewSchedule.is_active, ~ReviewSchedule.mastered, ReviewSchedule.next_review_at >= tomorrow_start, ReviewSchedule.next_review_at <= tomorrow_end))\n    return tomorrow_q.scalar() or 0",
    "_today_completion_metrics": "def _today_completion_metrics(today_due_count: int, today_remaining_count: int) -> tuple[int, float, bool]:\n    today_completed_count = max(0, today_due_count - today_remaining_count)\n    completion_rate = round(today_completed_count / today_due_count, 4) if today_due_count > 0 else 0.0\n    is_completed = today_due_count > 0 and today_remaining_count == 0\n    return (today_completed_count, completion_rate, is_completed)",
    "_today_result_metrics": "def _today_result_metrics(unique: list[ReviewRecord]) -> dict:\n    correct_count = sum((1 for record in unique if bool(record.is_correct)))\n    wrong_count = sum((1 for record in unique if not bool(record.is_correct)))\n    total_unique = len(unique)\n    accuracy = round(correct_count / total_unique, 4) if total_unique > 0 else 0.0\n    return {'correct_count': correct_count, 'wrong_count': wrong_count, 'skipped_count': 0, 'accuracy': accuracy}",
    "_dedupe_records_by_question": "def _dedupe_records_by_question(records: list[ReviewRecord]) -> list[ReviewRecord]:\n    seen_q: set[int] = set()\n    unique: list[ReviewRecord] = []\n    for record in records:\n        if record.question_id in seen_q:\n            continue\n        seen_q.add(record.question_id)\n        unique.append(record)\n    return unique",
    "_pending_today_schedules": "def _pending_today_schedules(task_schedules: list[ReviewSchedule], completed_question_ids: set[int]) -> list[ReviewSchedule]:\n    return [schedule for schedule in task_schedules if int(schedule.question_id) not in completed_question_ids and (not schedule.mastered)]",
    "_merge_today_task_schedules": "def _merge_today_task_schedules(due_schedules: list[ReviewSchedule], reviewed_schedules: list[ReviewSchedule], mastered_schedules: list[ReviewSchedule], today_end: datetime) -> list[ReviewSchedule]:\n    schedule_by_id = {int(schedule.id): schedule for schedule in due_schedules + reviewed_schedules + mastered_schedules}\n    return sorted(schedule_by_id.values(), key=lambda schedule: (schedule.next_review_at or today_end, int(schedule.id)))",
    "_ordered_review_items": 'def _ordered_review_items(reviews: list[dict]) -> list[tuple[int, dict]]:\n    """Stable per-question ordering so overlapping batches cannot deadlock."""\n    return sorted(enumerate(reviews), key=lambda pair: (int(pair[1][\'question_id\']), int(pair[1][\'schedule_id\']), pair[0]))',
    "_review_session_already_recorded": "async def _review_session_already_recorded(db: AsyncSession, user_id: int, base_request_id: str) -> bool:\n    existing = await db.scalar(select(func.count(ReviewSession.id)).where(ReviewSession.user_id == user_id, ReviewSession.request_id.startswith(base_request_id + ':', autoescape=True)))\n    return bool(existing)",
    "_review_408_scope_condition": "def _review_408_scope_condition(subject_ids: set[int]):\n    return or_(QuestionVersion.subject_id.in_(subject_ids), and_(QuestionVersion.subject_id.is_(None), ReviewSchedule.subject_id.in_(subject_ids)))",
    "_valid_revision_schedule_filters": "def _valid_revision_schedule_filters(conditions: list) -> tuple:\n    return (*conditions, QuestionVersion.question_id == ReviewSchedule.question_id)",
    "_today_review_conditions": "def _today_review_conditions(user_id: int, allowed_subject_ids: set[int], today_end: datetime) -> list:\n    return [ReviewSchedule.user_id == user_id, ReviewSchedule.is_active, ReviewSchedule.next_review_at <= today_end, ~ReviewSchedule.mastered, _review_408_scope_condition(allowed_subject_ids)]",
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


def count_of(tree, name, fragment):
    return source_of(tree, name).count(fragment)


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


def check_frozen_sources(tree):
    for name, expected in FROZEN_SOURCES.items():
        assert source_of(tree, name) == expected, name


def check_delegation(tree):
    submit = source_of(tree, "submit_review")
    ordered(
        submit,
        "await lock_review_request(db, user_id=user_id, request_id=request_id)",
        "await lock_question_review_state(db, user_id=user_id, question_id=question_id)",
        "request = {",
        "replay = await _resolve_review_replay(db, user_id, request)",
        "if replay is not None:",
        "return replay",
        "schedule = await _load_locked_review_schedule(db, user_id, request)",
        "payload = await _apply_review_grade(db, user_id, schedule, request)",
        "if auto_commit:",
        "await db.commit()",
        "await db.refresh(schedule)",
        "return payload",
    )
    # The replay lookup must stay ahead of all mutable schedule reads.
    assert submit.index("_resolve_review_replay") < submit.index(
        "_load_locked_review_schedule"
    )

    batch = source_of(tree, "grade_batch_review")
    ordered(
        batch,
        "if not reviews:",
        "raise ValueError(",
        "version_ids = [int(item['question_version_id']) for item in reviews]",
        "views = await load_revision_views(db, version_ids)",
        "results_by_index, prewarm_candidates = await _grade_batch_review_loop(",
        "await db.commit()",
        "await _prewarm_review_wrong_answers(prewarm_candidates, user_id)",
        "results = [",
        "await _record_review_session(db, user_id, session_meta, results)",
        "return {",
    )

    loop = source_of(tree, "_grade_batch_review_loop")
    ordered(
        loop,
        "results_by_index: list[tuple[int, dict]] = []",
        "prewarm_candidates: list[tuple[int, int, str]] = []",
        "for original_index, item in ordered:",
        "version_id = int(item['question_version_id'])",
        "revision = views.get(version_id)",
        "if revision is None or int(revision.question_id) != int(item['question_id']):",
        "_batch_review_missing_payload(",
        "index, payload, prewarm = await _grade_batch_review_item(",
        "results_by_index.append((index, payload))",
        "if prewarm is not None:",
        "prewarm_candidates.append(prewarm)",
        "return (results_by_index, prewarm_candidates)",
    )
    # Only the item helper reaches submit_review, and only the loop reaches the item
    # helper, so per-item failure mapping cannot leak into the batch entry point.
    assert count_of(tree, "_grade_batch_review_loop", "await submit_review(") == 0
    assert count_of(tree, "_grade_batch_review_item", "await submit_review(") == 1
    assert count_of(tree, "grade_batch_review", "await submit_review(") == 0

    item = source_of(tree, "_grade_batch_review_item")
    ordered(
        item,
        "answer, _is_correct, rating = _batch_review_question_answer(revision, item)",
        "try:",
        "result = await submit_review(",
        "except ValueError as exc:",
        "payload = _batch_review_error_payload(",
        "return (original_index, payload, None)",
        "payload = _batch_review_success_payload(",
        "return (original_index, payload, _batch_review_prewarm_candidate(result))",
    )
    # The batch keeps its historical narrow catch: only ValueError becomes a per-item
    # error payload, and never the "version missing" payload.
    assert "except Exception" not in item
    assert "_batch_review_missing_payload" not in item

    stats = source_of(tree, "get_review_stats")
    ordered(
        stats,
        "today = shanghai_today()",
        "today_start, today_end = shanghai_today_boundaries()",
        "since = shanghai_date_utc_range(today - timedelta(days=days - 1))[0]",
        "total_scheduled = await _count_active_review_schedules(db, user_id)",
        "total_reviewed_today = await _count_reviews_between(",
        "remaining_today = await _count_remaining_today(db, user_id, today_end)",
        "overdue = await _count_overdue_reviews(db, user_id, today_start)",
        "accuracy = await _review_accuracy_since(db, user_id, since)",
        "subject_rows = await _review_schedule_subject_rows(db, user_id, today_end)",
        "reviewed_by_subject = await _reviewed_by_subject_today(",
        "subject_ids = [row[0] for row in subject_rows if row[0] is not None]",
        "code_name = await _subject_code_names(db, subject_ids)",
        "by_subject = _review_stats_by_subject(",
        "return {",
    )

    state = source_of(tree, "_get_today_review_task_state")
    ordered(
        state,
        "today_start, today_end = shanghai_today_boundaries()",
        "allowed_subject_ids = await _active_408_subject_ids(db)",
        "due_schedules = await _today_due_review_schedules(",
        "reviewed_schedules, reviewed_question_ids = await _today_reviewed_context(",
        "mastered_schedules = await _today_mastered_schedules(",
        "task_schedules = _merge_today_task_schedules(",
        "task_question_ids = {int(s.question_id) for s in task_schedules}",
        "mastered_question_ids = await _today_mastered_question_ids(",
        "completed_question_ids = (reviewed_question_ids | mastered_question_ids)",
        "pending_schedules = _pending_today_schedules(",
        "return {",
    )

    overview = source_of(tree, "get_today_review_overview")
    ordered(
        overview,
        "state = await _get_today_review_task_state(db, user_id)",
        "today_due_count = len(task_schedules)",
        "today_remaining_count = len(pending_schedules)",
        "= _today_completion_metrics(today_due_count, today_remaining_count)",
        "today_overdue_count, today_new_due_count = _today_review_overdue_split(",
        "batch_size = 10",
        "metrics = _today_review_batch_metrics(",
        "'all_question_ids': [int(s.question_id) for s in task_schedules]",
        "'remaining_question_ids': [int(s.question_id) for s in pending_schedules]",
        "'is_completed': is_completed",
    )
    assert "while " not in overview

    result = source_of(tree, "get_today_review_result")
    ordered(
        result,
        "state = await _get_today_review_task_state(db, user_id)",
        "tomorrow_start = today_end + timedelta(microseconds=1)",
        "records = await _today_result_records(",
        "unique = _dedupe_records_by_question(records)",
        "metrics = _today_result_metrics(unique)",
        "subject_stats = await _today_result_subject_stats(db, unique)",
        "tomorrow_due_count = await _tomorrow_due_count(db, user_id, tomorrow_start)",
        "today_completed_count, completion_rate, is_completed = "
        "_today_completion_metrics(",
        "return {",
    )

    session = source_of(tree, "_record_review_session")
    ordered(
        session,
        "window = _normalize_review_session(session_meta)",
        "if window is None:",
        "return",
        "succeeded = [item for item in results if item.get('success')]",
        "if not succeeded:",
        "try:",
        "subject_by_schedule = await _review_session_subject_map(db, user_id, succeeded)",
        "stats_by_subject = _review_session_stats_by_subject(",
        "if await _review_session_already_recorded(db, user_id, window['request_id']):",
        "_add_review_session_rows(db, user_id, stats_by_subject, window)",
        "await db.commit()",
        "except Exception:",
        "await db.rollback()",
        "logger.warning(",
    )
    # A statistics write failure must never undo SM-2 progress.
    assert "raise" not in session

    today_review = source_of(tree, "get_today_review")
    ordered(
        today_review,
        "_, today_end = shanghai_today_boundaries()",
        "allowed_subject_ids = await _active_408_subject_ids(db)",
        "conditions = _today_review_conditions(user_id, allowed_subject_ids, today_end)",
        "if subject_id:",
        "if subject_id not in allowed_subject_ids:",
        "return {'total_today': 0, 'questions': []}",
        "conditions.append(ReviewSchedule.subject_id == subject_id)",
        "total = await _count_today_review_schedules(db, conditions)",
        "schedules = await _load_today_review_schedules(db, conditions, limit)",
        "prepared = await _prepare_latest_review_revisions(",
        "questions = [",
        "return {'total_today': total, 'questions': questions}",
    )

    prepared = source_of(tree, "_prepare_latest_review_revisions")
    ordered(
        prepared,
        "if not schedules:",
        "return []",
        "latest_ids = await load_latest_question_revision_ids(",
        "latest_views = await load_revision_views(db, _latest_revision_candidates(",
        "changed = False",
        "for schedule in schedules:",
        "revision = _latest_revision_view(latest_views, latest_version_id, schedule)",
        "_log_missing_review_revision(user_id, schedule, question_id)",
        "schedule, rebind_changed = await _rebind_if_stale(",
        "changed = rebind_changed or changed",
        "prepared.append((schedule, revision))",
        "if changed:",
        "await db.commit()",
        "return prepared",
    )

    mastered = source_of(tree, "set_mastered_state")
    ordered(
        mastered,
        "await lock_question_review_state(db, user_id=user_id, question_id=question_id)",
        "now = utcnow()",
        "wq = await db.scalar(",
        "schedule = await db.scalar(",
        "changed = _apply_manual_mastery_to_wrong_question(wq, mastered)",
        "schedule_changed, schedule = await _apply_manual_mastery_to_schedule(",
        "changed = schedule_changed or changed",
        "if mastered and changed",
        "wq.mastered_at = now",
        "await db.flush()",
        "return changed",
    )

    schedule_write = source_of(tree, "auto_schedule_wrong_question")
    ordered(
        schedule_write,
        "await lock_question_review_state(db, user_id=user_id, question_id=question_id)",
        "revision = await _load_wrong_question_revision(",
        "first_review_at = _first_wrong_review_at()",
        "schedule = await db.scalar(",
        "if schedule is None:",
        "schedule = _new_wrong_review_schedule(",
        "db.add(schedule)",
        "_reset_wrong_review_schedule(",
        "await _sync_schedule_to_wq(db, schedule)",
        "if commit:",
        "await db.commit()",
        "await db.refresh(schedule)",
        "await db.flush()",
        "return schedule",
    )


def check_single_source(tree):
    # Completion projection: one floor, one "is_completed" rule.
    assert MODULE_TEXT.count("max(0, today_due_count - today_remaining_count)") == 1
    assert MODULE_TEXT.count("today_due_count > 0 and today_remaining_count == 0") == 1
    assert count_of(tree, "_today_completion_metrics", "max(0, today_due_count") == 1
    for name in ENTRIES:
        assert "today_remaining_count == 0" not in source_of(tree, name), name

    # SM-2 application and the resulting mastery projection live in one helper.
    assert MODULE_TEXT.count("calc_sm2(") == 1
    assert MODULE_TEXT.count("review_auto_mastered(") == 1
    assert MODULE_TEXT.count("review_mastery_percent(") == 1
    assert count_of(tree, "_apply_sm2_update", "calc_sm2(") == 1
    assert count_of(tree, "_apply_review_grade", "review_auto_mastered(") == 1
    assert count_of(tree, "_apply_review_grade", "review_mastery_percent(") == 1
    assert count_of(tree, "_apply_review_grade", "occurrence_seq = int(") == 1

    # Row construction is single-sourced.
    assert MODULE_TEXT.count("ReviewRecord(") == 1
    assert MODULE_TEXT.count("ReviewSession(") == 1
    assert count_of(tree, "_build_review_record", "ReviewRecord(") == 1
    assert count_of(tree, "_add_review_session_rows", "ReviewSession(") == 1
    assert count_of(tree, "_add_review_session_rows", "db.add(") == 1

    # Best-effort boundary: one rollback, one warning, three warnings module-wide.
    assert MODULE_TEXT.count("rollback()") == 1
    assert count_of(tree, "_record_review_session", "rollback()") == 1
    assert MODULE_TEXT.count("logger.warning(") == 3

    # Entry points orchestrate; they must not inline SQL or loops.
    for name in SQL_FREE_ENTRIES:
        source = source_of(tree, name)
        assert "select(" not in source, name
        assert ".where(" not in source, name
    assert count_of(tree, "set_mastered_state", "select(") == 2
    assert count_of(tree, "set_mastered_state", "db.scalar(") == 2
    assert count_of(tree, "auto_schedule_wrong_question", "select(") == 1
    assert count_of(tree, "auto_schedule_wrong_question", "db.scalar(") == 1

    # Each today/tomorrow window keeps its own statement scope.
    assert count_of(tree, "_count_remaining_today", "select(") == 1
    assert count_of(tree, "_count_overdue_reviews", "select(") == 1
    assert count_of(tree, "_tomorrow_due_count", "select(") == 1
    assert MODULE_TEXT.count("next_review_at < today_start") == 2
    assert count_of(tree, "_count_overdue_reviews", "next_review_at < today_start") == 1
    assert count_of(tree, "_today_review_overdue_split", "today_start") == 2
    assert (
        count_of(tree, "_tomorrow_due_count", "next_review_at >= tomorrow_start") == 1
    )
    assert count_of(tree, "_tomorrow_due_count", "next_review_at <= tomorrow_end") == 1

    # Row and window scopes that must survive exactly as written: dropping a guard or
    # shifting a boundary silently changes what today's/statistics counters include.
    assert (
        count_of(tree, "_count_active_review_schedules", "ReviewSchedule.is_active")
        == 1
    )
    assert (
        count_of(tree, "_count_reviews_between", "ReviewRecord.reviewed_at >= start")
        == 1
    )
    assert (
        count_of(tree, "_count_reviews_between", "ReviewRecord.reviewed_at <= end") == 1
    )
    assert count_of(tree, "_review_accuracy_since", "ReviewRecord.rating >= 3") == 1
    assert (
        count_of(
            tree, "_review_accuracy_since", "round(correct_reviews / total_reviews, 4)"
        )
        == 1
    )
    assert (
        count_of(
            tree, "_reviewed_by_subject_today", "ReviewRecord.reviewed_at <= today_end"
        )
        == 1
    )
    assert (
        count_of(tree, "_today_reviewed_rows", "ReviewRecord.reviewed_at <= today_end")
        == 1
    )
    assert (
        count_of(
            tree,
            "_today_mastered_schedules",
            "WrongQuestion.mastered_at >= today_start, "
            "WrongQuestion.mastered_at <= today_end",
        )
        == 1
    )
    assert count_of(tree, "_today_mastered_schedules", "timedelta") == 0
    assert count_of(tree, "_today_mastered_schedules", "WrongQuestion.is_active") == 1
    assert count_of(tree, "_today_mastered_schedules", "ReviewSchedule.is_active") == 1
    assert count_of(tree, "_load_locked_review_schedule", ".with_for_update()") == 1
    assert (
        count_of(
            tree,
            "_maybe_update_user_question_state",
            ".order_by(QuestionVersion.version.desc(), QuestionVersion.id.desc())",
        )
        == 1
    )
    assert count_of(tree, "_today_result_metrics", "'skipped_count': 0") == 1

    # Today's scope predicate and the revision guard are single helpers.
    assert (
        count_of(tree, "_today_review_conditions", "_review_408_scope_condition(") == 1
    )
    assert (
        count_of(
            tree, "_valid_revision_schedule_filters", "QuestionVersion.question_id =="
        )
        == 1
    )
    assert count_of(tree, "_review_408_scope_condition", "subject_id.in_") == 2

    # Batch insert order and prewarm stay in their own helpers.
    assert count_of(tree, "grade_batch_review", "await db.commit()") == 1
    assert count_of(tree, "grade_batch_review", "await _grade_batch_review_loop(") == 1
    assert count_of(tree, "grade_batch_review", "_prewarm_review_wrong_answers(") == 1
    assert count_of(tree, "_prewarm_review_wrong_answers", "enqueue_prewarm(") == 1
    assert count_of(tree, "_prewarm_review_wrong_answers", "logger.warning(") == 1
    assert count_of(tree, "_ordered_review_items", "sorted(") == 1
    assert MODULE_TEXT.count("batch_size = 10") == 1
    assert count_of(tree, "get_today_review_overview", "batch_size = 10") == 1
    assert count_of(tree, "_today_review_batch_metrics", "current_batch_no") == 6


def test_projection_helpers_stay_within_budget():
    check_budgets(load())


def test_entry_signatures_and_delegation_order():
    tree = load()
    check_signatures(tree)
    check_frozen_sources(tree)
    check_delegation(tree)


def test_thresholds_and_sql_have_a_single_source():
    check_single_source(load())


def test_gate_rejects_widened_helper_budget():
    padding = "".join(f"    _pad_{index} = {index}\n" for index in range(60))
    text = MODULE_TEXT.replace(
        "def _today_result_metrics(unique: list[ReviewRecord]) -> dict:",
        "def _today_result_metrics(unique: list[ReviewRecord]) -> dict:\n" + padding,
    )
    assert text != MODULE_TEXT
    with pytest.raises(AssertionError):
        check_budgets(ast.parse(text))


def test_gate_rejects_replay_lookup_after_schedule_read():
    tree = load()
    submit = function(tree, "submit_review")
    body = [
        node
        for node in submit.body
        if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))
    ]
    replay_index = next(
        index
        for index, node in enumerate(body)
        if "_resolve_review_replay" in ast.unparse(node)
    )
    schedule_index = next(
        index
        for index, node in enumerate(body)
        if "_load_locked_review_schedule" in ast.unparse(node)
    )
    body.insert(schedule_index + 1, body.pop(replay_index))
    submit.body = body
    with pytest.raises(AssertionError):
        check_delegation(tree)


def test_gate_rejects_inline_sql_in_stats_entry():
    tree = load()
    stats = function(tree, "get_review_stats")
    stats.body.insert(
        3,
        ast.parse("rows = await db.execute(select(Subject))").body[0],
    )
    with pytest.raises(AssertionError):
        check_single_source(tree)


def test_gate_rejects_lost_best_effort_review_session_boundary():
    tree = load()
    session = function(tree, "_record_review_session")
    for node in ast.walk(session):
        if isinstance(node, ast.Raise):
            break
    else:
        handler = next(
            node for node in ast.walk(session) if isinstance(node, ast.ExceptHandler)
        )
        handler.body.append(ast.parse("raise").body[0])
    with pytest.raises(AssertionError):
        check_delegation(tree)


def test_gate_rejects_reordered_tomorrow_window():
    tree = load()
    tomorrow = function(tree, "_tomorrow_due_count")
    for node in ast.walk(tomorrow):
        if isinstance(node, ast.Compare) and "next_review_at >=" in ast.unparse(node):
            node.ops = [type(node.ops[0])()]
            node.comparators = [ast.Name(id="tomorrow_end", ctx=ast.Load())]
            break
    with pytest.raises(AssertionError):
        check_frozen_sources(tree)
