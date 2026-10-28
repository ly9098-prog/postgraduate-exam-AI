"""Contracts for the wrong-question service projection split.

These tests pin the observable behaviour of the five entry points that the
refactor decomposed into documented helpers: wrong-answer recording, wrong-book
statistics, the enriched list projection, batch operations and the task-flow
grouping. They intentionally drive only the entry-point seams (the database
double and the lazily imported ``review_scheduler``) so the same file also
passes when the frozen HEAD implementations are replayed through the pytest
plugin.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services import review_scheduler
from app.services import wrong_question_service as wqs
from app.services.wrong_question_service import WrongQuestion

NOW = datetime(2026, 10, 28, 3, 4, 5)
TODAY_END = datetime(2026, 10, 28, 15, 59, 59)
USER = 7
_UNSET = object()


class Result:
    """Result double: every accessor the service uses, all preloaded."""

    def __init__(
        self,
        *,
        rows=(),
        one=None,
        scalar=_UNSET,
        scalars_first=_UNSET,
    ):
        self._rows = list(rows)
        self._one = one
        self._scalar = scalar
        self._scalars_first = scalars_first

    def all(self):
        return list(self._rows)

    def one(self):
        return self._one

    def scalar(self):
        return self._scalar

    def scalars(self):
        first = self._scalars_first
        if first is _UNSET:
            first = self._rows[0] if self._rows else None

        class _Scalars:
            def __init__(self, rows, first):
                self._rows = rows
                self._first = first

            def all(self):
                return list(self._rows)

            def first(self):
                return self._first

        return _Scalars(self._rows, first)


class FakeDb:
    """Records statements; replays prepared responses; records lifecycle calls."""

    def __init__(self, execute_responses=(), scalar_responses=()):
        self.execute_responses = list(execute_responses)
        self.scalar_responses = list(scalar_responses)
        self.statements = []
        self.events = []

    async def execute(self, statement):
        self.statements.append(statement)
        self.events.append("execute")
        if self.execute_responses:
            return self.execute_responses.pop(0)
        return Result()

    async def scalar(self, statement):
        self.statements.append(statement)
        self.events.append("scalar")
        return self.scalar_responses.pop(0)

    async def commit(self):
        self.events.append("commit")

    async def flush(self):
        self.events.append("flush")

    async def refresh(self, obj):
        self.events.append(("refresh", getattr(obj, "id", None)))

    def add(self, obj):
        self.events.append(("add", type(obj).__name__))
        self.added = getattr(self, "added", [])
        self.added.append(obj)

    @asynccontextmanager
    async def begin_nested(self):
        self.events.append("begin_nested")
        try:
            yield self
        finally:
            self.events.append("begin_nested_exit")

    def sql(self, index):
        return " ".join(str(self.statements[index]).split())

    def params(self, index):
        return dict(self.statements[index].compile().params)


def install_review_spies(
    monkeypatch,
    *,
    lock_error_ids=(),
    auto="raise",
    auto_factory=None,
    mastered_results=None,
    mastered_default=True,
):
    """Patch the review scheduler seams used by record_wrong/batch_operate."""

    calls = {"lock": [], "auto": [], "mastered": []}
    events = []

    async def lock_spy(db, *, user_id, question_id):
        calls["lock"].append((user_id, question_id))
        events.append(("lock", question_id))
        if question_id in lock_error_ids:
            raise RuntimeError("lock failure")

    async def auto_spy(db, user_id, question_id, question_version_id, *, commit=True):
        calls["auto"].append((user_id, question_id, question_version_id, commit))
        events.append(("auto", question_id))
        if callable(auto_factory):
            return auto_factory(question_id, question_version_id)
        if auto == "raise":
            raise RuntimeError("auto failure")
        return auto

    async def mastered_spy(db, *, user_id, question_id, mastered):
        calls["mastered"].append((user_id, question_id, mastered))
        events.append(("mastered", question_id))
        results = mastered_results or {}
        value = results.get(question_id, mastered_default)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(review_scheduler, "lock_question_review_state", lock_spy)
    monkeypatch.setattr(review_scheduler, "auto_schedule_wrong_question", auto_spy)
    monkeypatch.setattr(review_scheduler, "set_mastered_state", mastered_spy)
    return calls, events


def wrong_question_row(**kw):
    defaults = {
        "id": 1,
        "question_id": 100,
        "wrong_answer": "B",
        "error_type": "concept",
        "review_count": 2,
        "mastered": False,
        "mastered_at": None,
        "is_active": True,
        "removed_at": None,
        "ai_analysis": None,
        "last_review_at": NOW,
        "created_at": NOW,
        "updated_at": NOW,
        "question_version_id": 900001,
    }
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def list_row(
    wq,
    question=None,
    subject=None,
    review_record_count=0,
    next_review=None,
    last_reviewed=None,
    mastery_pct=None,
):
    return (
        wq,
        question,
        subject,
        review_record_count,
        next_review,
        last_reviewed,
        mastery_pct,
    )


def task_flow_item(**kw):
    defaults = {
        "id": 1,
        "question_id": 100,
        "wrong_count": 1,
        "is_mastered": False,
        "next_review_at": None,
        "created_at": NOW,
    }
    defaults.update(kw)
    return defaults


# ── shared helper contracts ──────────────────────────────────────────


def test_dedupe_batch_ids_preserves_first_seen_order():
    assert wqs._dedupe_batch_ids([5, 3, 5, 0, 3]) == [5, 3, 0]
    assert wqs._dedupe_batch_ids([]) == []


def test_empty_batch_result_payload_is_frozen():
    result = wqs._empty_batch_result("mark_mastered")
    assert result == {
        "success": False,
        "action": "mark_mastered",
        "requested_count": 0,
        "updated_count": 0,
        "skipped_count": 0,
        "skipped_ids": [],
    }
    assert list(result) == [
        "success",
        "action",
        "requested_count",
        "updated_count",
        "skipped_count",
        "skipped_ids",
    ]


def test_ordered_batch_wrong_questions_sort_by_question_then_row_id():
    rows = {
        9: wrong_question_row(id=9, question_id=5),
        3: wrong_question_row(id=3, question_id=5),
        1: wrong_question_row(id=1, question_id=2),
    }
    ordered = wqs._ordered_batch_wrong_questions(rows)
    assert [(wq_id, wq.question_id) for wq_id, wq in ordered] == [
        (1, 2),
        (3, 5),
        (9, 5),
    ]
    assert wqs._ordered_batch_wrong_questions({}) == []


def test_reactivate_wrong_question_row_touches_only_marked_fields():
    active = wrong_question_row(is_active=True, mastered=False)
    assert wqs._reactivate_wrong_question_row(active) is False
    assert active.is_active is True
    assert active.removed_at is None

    removed = wrong_question_row(
        is_active=False, removed_at=NOW, mastered=True, mastered_at=NOW
    )
    assert wqs._reactivate_wrong_question_row(removed) is True
    assert removed.is_active is True
    assert removed.removed_at is None
    assert removed.mastered is False
    assert removed.mastered_at is None

    mastered_only = wrong_question_row(is_active=True, mastered=True, mastered_at=NOW)
    assert wqs._reactivate_wrong_question_row(mastered_only) is True
    assert mastered_only.mastered is False
    assert mastered_only.mastered_at is None


def test_force_schedule_due_now_branches(monkeypatch):
    monkeypatch.setattr(wqs, "utcnow", lambda: NOW)

    schedule = SimpleNamespace(
        is_active=False,
        mastered=True,
        next_review_at=NOW + timedelta(days=3),
        occurrence_seq=4,
    )
    assert wqs._force_schedule_due_now(schedule, rebound=False) is True
    assert schedule.is_active is True
    assert schedule.mastered is False
    assert schedule.next_review_at == NOW
    assert schedule.occurrence_seq == 5

    rebuilt = SimpleNamespace(
        is_active=False,
        mastered=False,
        next_review_at=None,
        occurrence_seq=2,
    )
    assert wqs._force_schedule_due_now(rebuilt, rebound=True) is True
    assert rebuilt.next_review_at == NOW
    assert rebuilt.occurrence_seq == 2  # a fresh rebind must not invalidate itself

    settled = SimpleNamespace(
        is_active=True,
        mastered=False,
        next_review_at=None,
        occurrence_seq=0,
    )
    assert wqs._force_schedule_due_now(settled, rebound=False) is True
    assert settled.next_review_at == NOW
    assert settled.occurrence_seq == 1

    untouched = SimpleNamespace(
        is_active=True,
        mastered=False,
        next_review_at=NOW - timedelta(minutes=1),
        occurrence_seq=3,
    )
    assert wqs._force_schedule_due_now(untouched, rebound=False) is False
    assert untouched.next_review_at == NOW - timedelta(minutes=1)
    assert untouched.occurrence_seq == 3


def test_task_flow_bucket_priority_chain():
    due = TODAY_END - timedelta(hours=1)
    old = NOW - timedelta(days=30)
    fresh = NOW - timedelta(days=13)
    window = NOW - timedelta(days=14)
    cases = [
        (task_flow_item(next_review_at=due), "today_due"),
        (task_flow_item(next_review_at=due, wrong_count=9), "today_due"),
        (task_flow_item(next_review_at=TODAY_END), "today_due"),
        (task_flow_item(wrong_count=3), "high_frequency"),
        (task_flow_item(wrong_count=3, created_at=fresh), "high_frequency"),
        (task_flow_item(created_at=fresh), "recent_added"),
        (task_flow_item(created_at=old), "to_consolidate"),
        (task_flow_item(is_mastered=True, wrong_count=9), "mastered"),
    ]
    for item, expected in cases:
        assert wqs._task_flow_bucket(item, TODAY_END, window) == expected
    future = task_flow_item(
        next_review_at=TODAY_END + timedelta(microseconds=1), created_at=old
    )
    assert wqs._task_flow_bucket(future, TODAY_END, window) == "to_consolidate"


def test_task_flow_groups_keep_titles_and_preview_slices():
    buckets = {
        "today_due": list(range(5)),
        "high_frequency": [10, 11],
        "recent_added": [],
        "to_consolidate": [20],
        "mastered": [30, 31, 32],
    }
    groups = wqs._task_flow_groups(buckets, 2)
    assert [(g["key"], g["title"], g["total"]) for g in groups] == [
        ("today_due", "今日应复习", 5),
        ("high_frequency", "高频错题", 2),
        ("recent_added", "最近新增", 0),
        ("to_consolidate", "待巩固", 1),
        ("mastered", "已经掌握", 3),
    ]
    assert [g["items"] for g in groups] == [
        [0, 1],
        [10, 11],
        [],
        [20],
        [30, 31],
    ]


def test_task_flow_summary_counters_are_non_exclusive():
    items = [
        task_flow_item(is_mastered=True),
        task_flow_item(is_mastered=True, wrong_count=4),
        task_flow_item(wrong_count=3),
        task_flow_item(wrong_count=2),
    ]
    summary = wqs._task_flow_summary(items, total_count=99, today_due_count=1)
    assert summary == {
        "total_count": 99,
        "mastered_count": 2,
        "high_frequency_count": 1,
        "today_due_count": 1,
    }


def test_wrong_mastery_percent_prefers_canonical_mastery():
    assert wqs._wrong_mastery_percent(wrong_question_row(mastered=True), None) == 1.0
    assert wqs._wrong_mastery_percent(wrong_question_row(mastered=True), 0.45) == 1.0
    assert wqs._wrong_mastery_percent(wrong_question_row(), None) == 0.20
    assert wqs._wrong_mastery_percent(wrong_question_row(), 0.456789) == 0.4568


def test_wrong_ai_analysis_status_only_ready_for_non_empty_dict():
    assert wqs._wrong_ai_analysis_status(None) == "empty"
    assert wqs._wrong_ai_analysis_status({}) == "empty"
    assert wqs._wrong_ai_analysis_status([]) == "empty"
    assert wqs._wrong_ai_analysis_status({"summary": "ok"}) == "ready"


# ── record_wrong ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_wrong_reactivates_existing_row(monkeypatch):
    monkeypatch.setattr(wqs, "utcnow", lambda: NOW)
    calls, events = install_review_spies(monkeypatch, auto=None)
    existing = wrong_question_row(
        id=11,
        is_active=False,
        removed_at=NOW,
        mastered=True,
        mastered_at=NOW,
        ai_analysis={"stale": True},
        review_count=2,
        question_version_id=3,
    )
    db = FakeDb([Result(scalars_first=existing)])

    wq = await wqs.record_wrong(
        db, USER, 100, "C", question_version_id=777, commit=True
    )

    assert wq is existing
    assert events == [("lock", 100), ("auto", 100)]
    assert calls["lock"] == [(USER, 100)]
    assert calls["auto"] == [(USER, 100, 777, True)]
    assert db.events[0] == "execute"
    assert ("add", "WrongQuestion") not in db.events
    assert ("refresh", 11) in db.events
    assert "flush" not in db.events
    assert existing.is_active is True
    assert existing.removed_at is None
    assert existing.mastered is False
    assert existing.mastered_at is None
    assert existing.ai_analysis is None
    assert existing.wrong_answer == "C"
    assert existing.question_version_id == 777
    assert existing.review_count == 3
    assert existing.last_review_at == NOW
    load_sql = db.sql(0).lower()
    assert "wrong_questions.user_id" in load_sql
    assert "wrong_questions.question_id" in load_sql
    load_params = list(db.params(0).values())
    assert USER in load_params and 100 in load_params


@pytest.mark.asyncio
async def test_record_wrong_clears_mastery_without_touching_active_state(monkeypatch):
    monkeypatch.setattr(wqs, "utcnow", lambda: NOW)
    install_review_spies(monkeypatch, auto=None)
    existing = wrong_question_row(
        id=12,
        is_active=True,
        removed_at=None,
        mastered=True,
        mastered_at=NOW,
        review_count=4,
    )
    db = FakeDb([Result(scalars_first=existing)])

    wq = await wqs.record_wrong(db, USER, 100, "B", question_version_id=70, commit=True)

    assert wq is existing
    assert existing.is_active is True
    assert existing.removed_at is None
    assert existing.mastered is False
    assert existing.mastered_at is None
    assert existing.review_count == 5


@pytest.mark.asyncio
async def test_record_wrong_creates_row_and_flushes_when_not_committing(monkeypatch):
    monkeypatch.setattr(wqs, "utcnow", lambda: NOW)
    calls, events = install_review_spies(monkeypatch, auto=None)
    db = FakeDb([Result(scalars_first=None)])

    wq = await wqs.record_wrong(
        db, USER, 100, "D", question_version_id=888, commit=False
    )

    assert isinstance(wq, WrongQuestion)
    assert (wq.user_id, wq.question_id, wq.wrong_answer) == (USER, 100, "D")
    assert wq.question_version_id == 888
    assert wq.review_count == 1
    assert wq.last_review_at == NOW
    assert calls["auto"] == [(USER, 100, 888, False)]
    assert events == [("lock", 100), ("auto", 100)]
    assert db.events.index(("add", "WrongQuestion")) < db.events.index("flush")
    assert ("refresh", None) in db.events


# ── get_stats ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_stats_projects_summary_groups_and_due_count(monkeypatch):
    monkeypatch.setattr(wqs, "shanghai_today_boundaries", lambda: (None, TODAY_END))
    summary_row = SimpleNamespace(
        total="12", unmastered=9, mastered=3, high_frequency_count=4
    )
    db = FakeDb(
        [
            Result(one=summary_row),
            Result(rows=[("concept", 6), ("careless", 6)]),
            Result(rows=[(1, "MATH", "数学", 7), (2, "408", "408", 5)]),
            Result(scalar=8),
        ]
    )

    stats = await wqs.get_stats(db, USER)

    assert stats == {
        "total": 12,
        "unmastered": 9,
        "mastered": 3,
        "high_frequency_count": 4,
        "today_due_count": 8,
        "by_subject": [
            {
                "subject_id": 1,
                "subject_code": "MATH",
                "subject_name": "数学",
                "count": 7,
            },
            {
                "subject_id": 2,
                "subject_code": "408",
                "subject_name": "408",
                "count": 5,
            },
        ],
        "by_error_type": [
            {"type": "concept", "count": 6},
            {"type": "careless", "count": 6},
        ],
    }
    assert len(db.statements) == 4
    assert "coalesce(sum(case" in db.sql(0).lower()
    assert "wrong_questions.is_active" in db.sql(0).lower()
    assert "group by wrong_questions.error_type" in db.sql(1).lower()
    assert "join subjects" in db.sql(2).lower()
    assert "count(distinct(review_schedules.question_id))" in db.sql(3).lower()
    due_sql = db.sql(3).lower()
    assert "review_schedules.is_active" in due_sql
    assert "review_schedules.mastered" in due_sql
    summary_ints = [value for value in db.params(0).values() if isinstance(value, int)]
    assert 3 in summary_ints
    summary_sql = db.sql(0).lower()
    assert summary_sql.count("not wrong_questions.mastered") == 2
    assert "wrong_questions.user_id =" in summary_sql


@pytest.mark.asyncio
async def test_get_stats_coalesces_missing_rows_to_zero(monkeypatch):
    monkeypatch.setattr(wqs, "shanghai_today_boundaries", lambda: (None, TODAY_END))
    summary_row = SimpleNamespace(
        total=None, unmastered=None, mastered=None, high_frequency_count=None
    )
    db = FakeDb(
        [
            Result(one=summary_row),
            Result(rows=[]),
            Result(rows=[]),
            Result(scalar=None),
        ]
    )

    stats = await wqs.get_stats(db, USER)

    assert stats["total"] == 0
    assert stats["unmastered"] == 0
    assert stats["mastered"] == 0
    assert stats["high_frequency_count"] == 0
    assert stats["today_due_count"] == 0
    assert stats["by_subject"] == []
    assert stats["by_error_type"] == []


@pytest.mark.asyncio
async def test_get_stats_subject_scope_adds_subquery_condition(monkeypatch):
    monkeypatch.setattr(wqs, "shanghai_today_boundaries", lambda: (None, TODAY_END))
    summary_row = SimpleNamespace(
        total=0, unmastered=0, mastered=0, high_frequency_count=0
    )
    db = FakeDb(
        [
            Result(one=summary_row),
            Result(rows=[]),
            Result(rows=[]),
            Result(scalar=0),
        ]
    )

    await wqs.get_stats(db, USER, allowed_subject_ids={1, 2})

    for index in range(4):
        assert "in (select questions.id from questions" in db.sql(index).lower()
    params = db.params(0)
    assert any(
        set(value) == {1, 2}
        for value in params.values()
        if isinstance(value, (list, tuple, set))
    )


# ── list_wrong_enriched ──────────────────────────────────────────────


def install_list_seams(monkeypatch, kp_map=None, subject_ids=(1, 2)):
    calls = {"kps": [], "subjects": []}

    async def kp_loader(db, question_ids):
        calls["kps"].append(list(question_ids))
        return dict(kp_map or {})

    async def subject_loader(db, subject_id):
        calls["subjects"].append(subject_id)
        return list(subject_ids)

    monkeypatch.setattr(wqs, "load_question_kps", kp_loader)
    monkeypatch.setattr(wqs, "resolve_subject_ids", subject_loader)
    return calls


@pytest.mark.asyncio
async def test_list_wrong_enriched_projects_full_item(monkeypatch):
    calls = install_list_seams(monkeypatch, kp_map={100: [{"id": 5, "name": "极限"}]})
    wq = wrong_question_row(
        id=11, review_count=2, mastered=False, ai_analysis={"summary": "s"}
    )
    question = SimpleNamespace(
        id=100,
        subject_id=1,
        question_type="single_choice",
        content={"text": "题干"},
        options=[{"key": "A"}],
        answer="A",
        analysis="解析",
        image_url="https://example.test/q.png",
    )
    subject = SimpleNamespace(code="MATH", name="数学")
    db = FakeDb(
        [
            Result(scalar=3),
            Result(
                rows=[
                    list_row(
                        wq,
                        question,
                        subject,
                        review_record_count=4,
                        next_review=NOW + timedelta(days=1),
                        last_reviewed=NOW - timedelta(days=1),
                        mastery_pct=0.456789,
                    )
                ]
            ),
        ]
    )

    items, total = await wqs.list_wrong_enriched(db, USER)

    assert total == 3
    assert calls["kps"] == [[100]]
    assert items == [
        {
            "id": 11,
            "question_id": 100,
            "wrong_answer": "B",
            "error_type": "concept",
            "review_count": 2,
            "review_record_count": 4,
            "wrong_count": 2,
            "mastery_percent": 0.4568,
            "is_mastered": False,
            "next_review_at": NOW + timedelta(days=1),
            "last_reviewed_at": NOW - timedelta(days=1),
            "last_wrong_at": NOW,
            "created_at": NOW,
            "updated_at": NOW,
            "subject_id": 1,
            "subject_code": "MATH",
            "subject_name": "数学",
            "question_type": "single_choice",
            "content": {"text": "题干"},
            "options": [{"key": "A"}],
            "answer": "A",
            "analysis": "解析",
            "knowledge_points": [{"id": 5, "name": "极限"}],
            "image_url": "https://example.test/q.png",
            "ai_analysis": {"summary": "s"},
            "ai_analysis_status": "ready",
        }
    ]
    page_sql = db.sql(1).lower()
    assert (
        "order by wrong_questions.updated_at desc, wrong_questions.id desc" in page_sql
    )
    assert "left outer join subjects" in page_sql
    assert "review_records.question_version_id" in page_sql
    assert "review_schedules.mastered" in page_sql
    assert "review_schedules.is_active" in page_sql
    assert "not review_schedules.mastered" in page_sql
    page_values = list(db.params(1).values())
    for threshold in (5, 4, 3, 2, 1):
        assert threshold in page_values
    assert 0.9 in page_values and 0.2 in page_values
    assert len(db.statements) == 2


@pytest.mark.asyncio
async def test_list_wrong_enriched_handles_missing_question_and_mastery(monkeypatch):
    install_list_seams(monkeypatch, kp_map={})
    mastered = wrong_question_row(id=5, mastered=True, review_count=None)
    db = FakeDb(
        [
            Result(scalar=0),
            Result(rows=[list_row(mastered, None, None, mastery_pct=None)]),
        ]
    )

    items, total = await wqs.list_wrong_enriched(db, USER)

    assert total == 0
    item = items[0]
    assert item["mastery_percent"] == 1.0
    assert item["is_mastered"] is True
    assert item["review_count"] == 0
    assert item["wrong_count"] == 0
    assert item["review_record_count"] == 0
    assert item["subject_id"] is None
    assert item["subject_code"] is None
    assert item["subject_name"] is None
    assert item["content"] is None
    assert item["knowledge_points"] is None
    assert item["ai_analysis_status"] == "empty"


@pytest.mark.asyncio
async def test_list_wrong_enriched_applies_filters_and_pagination(monkeypatch):
    calls = install_list_seams(monkeypatch, kp_map={})
    db = FakeDb([Result(scalar=7), Result(rows=[])])

    items, total = await wqs.list_wrong_enriched(
        db,
        USER,
        subject_id=3,
        error_type="careless",
        topic="  极限  ",
        page=3,
        page_size=25,
        allowed_subject_ids={1},
        date_from=date(2026, 10, 1),
        date_to=date(2026, 10, 20),
    )

    assert items == []
    assert total == 7
    assert calls["subjects"] == [3]
    assert calls["kps"] == [[]]
    page_sql = db.sql(1).lower()
    assert "wrong_questions.error_type =" in page_sql
    assert "wrong_questions.created_at >=" in page_sql
    assert "wrong_questions.created_at <" in page_sql
    assert "knowledge_points.name like" in page_sql
    assert "limit" in page_sql and "offset" in page_sql
    from app.core.time_utils import study_day_utc_range

    page_values = list(db.params(1).values())
    limit_params = [value for value in page_values if isinstance(value, int)]
    assert 25 in limit_params and 50 in limit_params
    assert study_day_utc_range(date(2026, 10, 1))[0] in page_values
    assert study_day_utc_range(date(2026, 10, 20))[1] in page_values


# ── batch_operate ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_batch_operate_empty_ids_returns_failure_without_touching_db():
    db = FakeDb()
    result = await wqs.batch_operate(db, USER, "delete", [])
    assert result == {
        "success": False,
        "action": "delete",
        "requested_count": 0,
        "updated_count": 0,
        "skipped_count": 0,
        "skipped_ids": [],
    }
    assert db.statements == []
    assert db.events == []


@pytest.mark.asyncio
async def test_batch_operate_unknown_action_still_commits_and_reports_not_found(
    monkeypatch,
):
    calls, _events = install_review_spies(monkeypatch)
    db = FakeDb([Result(rows=[wrong_question_row(id=1, question_id=50)])])

    result = await wqs.batch_operate(db, USER, "unsupported", [1, 999])

    assert result == {
        "success": True,
        "action": "unsupported",
        "requested_count": 2,
        "updated_count": 0,
        "skipped_count": 1,
        "skipped_ids": [999],
    }
    assert calls == {"lock": [], "auto": [], "mastered": []}
    assert db.events.count("commit") == 1
    assert len(db.statements) == 1
    select_sql = db.sql(0).lower()
    assert "wrong_questions.id in" in select_sql
    assert "wrong_questions.user_id =" in select_sql


@pytest.mark.asyncio
async def test_batch_add_to_review_reactivates_row_and_rebinds_schedule(monkeypatch):
    def schedule_factory(question_id, version_id):
        return SimpleNamespace(
            question_version_id=version_id,
            is_active=False,
            mastered=False,
            next_review_at=NOW + timedelta(days=2),
            occurrence_seq=6,
        )

    monkeypatch.setattr(wqs, "utcnow", lambda: NOW)
    calls, events = install_review_spies(monkeypatch, auto_factory=schedule_factory)
    wq = wrong_question_row(
        id=4,
        question_id=50,
        is_active=False,
        removed_at=NOW,
        mastered=True,
        mastered_at=NOW,
        question_version_id=71,
    )
    db = FakeDb([Result(rows=[wq])], scalar_responses=[None])

    result = await wqs.batch_operate(db, USER, "add_to_review", [4])

    assert result["updated_count"] == 1
    assert result["skipped_ids"] == []
    assert result["requested_count"] == 1
    assert wq.is_active is True
    assert wq.removed_at is None
    assert wq.mastered is False
    assert wq.mastered_at is None
    assert calls["lock"] == [(USER, 50)]
    assert calls["auto"] == [(USER, 50, 71, False)]
    assert events == [("lock", 50), ("auto", 50)]
    assert db.events.count("begin_nested") == 1
    assert db.events.count("begin_nested_exit") == 1
    assert db.events.count("commit") == 1
    assert len(db.statements) == 2  # select + schedule lookup


@pytest.mark.asyncio
async def test_batch_add_to_review_skips_unchanged_and_swallows_errors(monkeypatch):
    monkeypatch.setattr(wqs, "utcnow", lambda: NOW)

    def schedule_factory(question_id, version_id):
        raise AssertionError("unexpected rebind")

    calls, _events = install_review_spies(
        monkeypatch,
        lock_error_ids=(60,),
        auto_factory=schedule_factory,
    )
    unchanged = wrong_question_row(
        id=1,
        question_id=50,
        is_active=True,
        mastered=False,
        question_version_id=70,
    )
    explosive = wrong_question_row(
        id=2,
        question_id=60,
        is_active=False,
        question_version_id=70,
    )
    db = FakeDb(
        [Result(rows=[unchanged, explosive])],
        scalar_responses=[
            SimpleNamespace(
                question_version_id=70,
                is_active=True,
                mastered=False,
                next_review_at=NOW - timedelta(days=1),
                occurrence_seq=9,
            )
        ],
    )

    result = await wqs.batch_operate(db, USER, "add_to_review", [1, 2])

    assert result["updated_count"] == 0
    assert result["skipped_ids"] == [1, 2]
    assert result["success"] is True
    assert db.events.count("begin_nested") == 2
    assert calls["lock"] == [(USER, 50), (USER, 60)]
    assert calls["auto"] == []
    assert db.events.count("commit") == 1


@pytest.mark.asyncio
async def test_batch_add_to_review_forces_future_schedule_and_bumps_occurrence(
    monkeypatch,
):
    monkeypatch.setattr(wqs, "utcnow", lambda: NOW)
    install_review_spies(monkeypatch)
    wq = wrong_question_row(
        id=1,
        question_id=50,
        is_active=True,
        mastered=False,
        question_version_id=70,
    )
    schedule = SimpleNamespace(
        question_version_id=70,
        is_active=True,
        mastered=False,
        next_review_at=NOW + timedelta(days=5),
        occurrence_seq=3,
    )
    db = FakeDb([Result(rows=[wq])], scalar_responses=[schedule])

    result = await wqs.batch_operate(db, USER, "add_to_review", [1])

    assert result["updated_count"] == 1
    assert schedule.next_review_at == NOW
    assert schedule.occurrence_seq == 4


@pytest.mark.asyncio
async def test_batch_add_to_review_rebinds_when_version_differs(monkeypatch):
    monkeypatch.setattr(wqs, "utcnow", lambda: NOW)

    def schedule_factory(question_id, version_id):
        return SimpleNamespace(
            question_version_id=version_id,
            is_active=True,
            mastered=False,
            next_review_at=None,
            occurrence_seq=2,
        )

    calls, _events = install_review_spies(monkeypatch, auto_factory=schedule_factory)
    wq = wrong_question_row(id=1, question_id=50, question_version_id=70)
    stale = SimpleNamespace(
        question_version_id=69,
        is_active=True,
        mastered=False,
        next_review_at=NOW + timedelta(days=5),
        occurrence_seq=2,
    )
    db = FakeDb([Result(rows=[wq])], scalar_responses=[stale])

    result = await wqs.batch_operate(db, USER, "add_to_review", [1])

    assert result["updated_count"] == 1
    assert calls["auto"] == [(USER, 50, 70, False)]
    assert stale.next_review_at == NOW + timedelta(days=5)
    assert stale.occurrence_seq == 2


@pytest.mark.asyncio
async def test_batch_mastery_actions_skip_inactive_rows(monkeypatch):
    calls, _events = install_review_spies(monkeypatch, mastered_results={60: False})
    active = wrong_question_row(id=1, question_id=50)
    inactive = wrong_question_row(id=2, question_id=40, is_active=False, removed_at=NOW)
    unchanged = wrong_question_row(id=3, question_id=60)
    db = FakeDb([Result(rows=[active, inactive, unchanged])])

    result = await wqs.batch_operate(db, USER, "mark_mastered", [1, 2, 3])

    assert result["updated_count"] == 1
    assert result["skipped_ids"] == [2, 3]
    assert calls["mastered"] == [(USER, 50, True), (USER, 60, True)]
    assert db.events.count("begin_nested") == 0
    assert db.events.count("commit") == 1


@pytest.mark.asyncio
async def test_batch_unmark_mastered_passes_false(monkeypatch):
    calls, _events = install_review_spies(monkeypatch)
    row = wrong_question_row(id=1, question_id=50)
    db = FakeDb([Result(rows=[row])])

    result = await wqs.batch_operate(db, USER, "unmark_mastered", [1])

    assert result["updated_count"] == 1
    assert calls["mastered"] == [(USER, 50, False)]


@pytest.mark.asyncio
async def test_batch_remove_from_book_deactivates_row_and_schedule(monkeypatch):
    monkeypatch.setattr(wqs, "utcnow", lambda: NOW)
    calls, _events = install_review_spies(monkeypatch)
    active = wrong_question_row(id=1, question_id=50, is_active=True)
    inactive = wrong_question_row(id=2, question_id=40, is_active=False, removed_at=NOW)
    no_schedule = wrong_question_row(id=3, question_id=60, is_active=True)
    schedule = SimpleNamespace(is_active=True, occurrence_seq=2)
    db = FakeDb(
        [Result(rows=[active, inactive, no_schedule])],
        scalar_responses=[schedule, None],
    )

    result = await wqs.batch_operate(db, USER, "remove_from_book", [1, 2, 3])

    assert result["updated_count"] == 2
    assert result["skipped_ids"] == [2]
    assert active.is_active is False
    assert active.removed_at == NOW
    assert schedule.is_active is False
    assert schedule.occurrence_seq == 3
    assert no_schedule.is_active is False
    assert no_schedule.removed_at == NOW
    assert calls["lock"] == [(USER, 40), (USER, 50), (USER, 60)]


@pytest.mark.asyncio
async def test_batch_delete_unlinks_history_then_schedule_then_wrong_question(
    monkeypatch,
):
    calls, _events = install_review_spies(monkeypatch)
    first = wrong_question_row(id=1, question_id=50)
    second = wrong_question_row(id=2, question_id=40)
    db = FakeDb([Result(rows=[first, second])])

    result = await wqs.batch_operate(db, USER, "delete", [1, 2])

    assert result["updated_count"] == 2
    assert result["skipped_ids"] == []
    assert calls["lock"] == [(USER, 40), (USER, 50)]
    assert len(db.statements) == 1 + 6
    delete_sql = [db.sql(index).lower() for index in range(1, 7)]
    assert "delete from review_records" in delete_sql[0]
    assert "delete from review_schedules" in delete_sql[1]
    assert "delete from wrong_questions" in delete_sql[2]
    assert "delete from review_records" in delete_sql[3]
    assert "delete from review_schedules" in delete_sql[4]
    assert "delete from wrong_questions" in delete_sql[5]
    assert db.events.count("commit") == 1


@pytest.mark.asyncio
async def test_batch_operate_dedupes_and_processes_in_lock_order(monkeypatch):
    calls, _events = install_review_spies(monkeypatch)
    high_id_low_question = wrong_question_row(id=9, question_id=1)
    low_id_high_question = wrong_question_row(id=2, question_id=8)
    db = FakeDb([Result(rows=[high_id_low_question, low_id_high_question])])

    result = await wqs.batch_operate(db, USER, "delete", [9, 2, 9, 404])

    assert result["requested_count"] == 3
    assert result["updated_count"] == 2
    assert result["skipped_ids"] == [404]
    assert calls["lock"] == [(USER, 1), (USER, 8)]


# ── get_task_flow ────────────────────────────────────────────────────


def install_task_flow_seams(monkeypatch, pages):
    calls = []

    async def loader(db, user_id, **kwargs):
        calls.append(dict(kwargs))
        index = kwargs.get("page", 1) - 1
        if index >= len(pages):
            return [], pages[-1][1] if pages else 0
        return pages[index]

    monkeypatch.setattr(wqs, "list_wrong_enriched", loader)
    monkeypatch.setattr(wqs, "utcnow", lambda: NOW)
    monkeypatch.setattr(wqs, "shanghai_today_boundaries", lambda: (None, TODAY_END))
    return calls


@pytest.mark.asyncio
async def test_task_flow_paginates_until_total_reached(monkeypatch):
    first_page = [task_flow_item(id=index, question_id=index) for index in range(500)]
    second_page = [task_flow_item(id=999, question_id=999)]
    calls = install_task_flow_seams(
        monkeypatch, [(first_page, 501), (second_page, 501)]
    )

    flow = await wqs.get_task_flow(FakeDb(), USER)

    assert [call["page"] for call in calls] == [1, 2]
    assert all(call["page_size"] == 500 for call in calls)
    assert flow["summary"]["total_count"] == 501
    assert flow["summary"]["mastered_count"] == 0
    groups = {group["key"]: group for group in flow["groups"]}
    assert groups["recent_added"]["total"] == 501
    assert all(
        groups[key]["total"] == 0
        for key in ("today_due", "high_frequency", "to_consolidate", "mastered")
    )


@pytest.mark.asyncio
async def test_task_flow_stops_on_empty_page(monkeypatch):
    calls = install_task_flow_seams(monkeypatch, [([], 9)])

    flow = await wqs.get_task_flow(FakeDb(), USER)

    assert [call["page"] for call in calls] == [1]
    assert flow["summary"]["total_count"] == 9
    assert all(group["total"] == 0 for group in flow["groups"])


@pytest.mark.asyncio
async def test_task_flow_groups_and_preview_and_summary(monkeypatch):
    due = TODAY_END - timedelta(hours=1)
    fresh = NOW - timedelta(days=1)
    old = NOW - timedelta(days=60)
    items = [
        task_flow_item(id=1, next_review_at=due),
        task_flow_item(id=2, next_review_at=due),
        task_flow_item(id=3, next_review_at=due, wrong_count=7, is_mastered=True),
        task_flow_item(id=4, wrong_count=3),
        task_flow_item(id=5, created_at=fresh),
        task_flow_item(id=6, created_at=old),
        task_flow_item(id=7, is_mastered=True, created_at=old),
    ]
    install_task_flow_seams(monkeypatch, [(items, len(items))])

    flow = await wqs.get_task_flow(FakeDb(), USER, preview_size=1)

    groups = {group["key"]: group for group in flow["groups"]}
    assert groups["today_due"]["total"] == 2
    assert [item["id"] for item in groups["today_due"]["items"]] == [1]
    assert groups["high_frequency"]["total"] == 1
    assert groups["recent_added"]["total"] == 1
    assert groups["to_consolidate"]["total"] == 1
    assert groups["mastered"]["total"] == 2
    assert flow["summary"] == {
        "total_count": 7,
        "mastered_count": 2,
        "high_frequency_count": 1,
        "today_due_count": 2,
    }


@pytest.mark.asyncio
async def test_task_flow_passes_filters_and_recent_window(monkeypatch):
    fresh_boundary = NOW - timedelta(days=14)
    items = [
        task_flow_item(id=1, created_at=fresh_boundary),
        task_flow_item(id=2, created_at=fresh_boundary - timedelta(microseconds=1)),
    ]
    calls = install_task_flow_seams(monkeypatch, [(items, 2)])

    flow = await wqs.get_task_flow(
        FakeDb(),
        USER,
        subject_id=2,
        error_type="careless",
        topic="极限",
        preview_size=3,
        allowed_subject_ids={1},
        date_from=date(2026, 10, 1),
        date_to=date(2026, 10, 20),
    )

    groups = {group["key"]: group for group in flow["groups"]}
    assert groups["recent_added"]["total"] == 1
    assert groups["to_consolidate"]["total"] == 1
    kwargs = calls[0]
    assert kwargs["subject_id"] == 2
    assert kwargs["error_type"] == "careless"
    assert kwargs["topic"] == "极限"
    assert kwargs["allowed_subject_ids"] == {1}
    assert kwargs["date_from"] == date(2026, 10, 1)
    assert kwargs["date_to"] == date(2026, 10, 20)
    assert kwargs["page"] == 1
    assert kwargs["page_size"] == 500
