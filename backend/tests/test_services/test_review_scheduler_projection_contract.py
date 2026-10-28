"""Contracts for the review-scheduler projection split.

These tests pin the observable behaviour of the eleven entry points decomposed
by this refactor. They drive only entry-point seams (the database double, the
revision loaders and the review locks) so the same file also passes when the
frozen HEAD implementations are replayed through the pytest plugin.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services import review_scheduler as rs

NOW = datetime(2026, 10, 28, 3, 4, 5)
TODAY_START = datetime(2026, 10, 27, 16, 0, 0)
TODAY_END = datetime(2026, 10, 28, 15, 59, 59)
USER = 7
_UNSET = object()


class Result:
    """Result double covering every accessor the scheduler uses."""

    def __init__(self, *, rows=(), one=None, scalar=_UNSET):
        self._rows = list(rows)
        self._one = one
        self._scalar = scalar

    def all(self):
        return list(self._rows)

    def one(self):
        return self._one

    def scalar(self):
        return self._scalar

    def scalars(self):
        rows = self._rows

        class _Scalars:
            def all(self):
                return list(rows)

        return _Scalars()


class FakeDb:
    def __init__(self, execute_responses=(), scalar_responses=(), scalars_responses=()):
        self.execute_responses = list(execute_responses)
        self.scalar_responses = list(scalar_responses)
        self.scalars_responses = list(scalars_responses)
        self.statements = []
        self.events = []
        self.added = []
        self.rollbacks = 0

    async def execute(self, statement):
        self.statements.append(statement)
        self.events.append("execute")
        if self.execute_responses:
            return self.execute_responses.pop(0)
        return Result()

    async def scalar(self, statement):
        self.statements.append(statement)
        self.events.append("scalar")
        if self.scalar_responses:
            return self.scalar_responses.pop(0)
        return None

    async def scalars(self, statement):
        self.statements.append(statement)
        self.events.append("scalars")
        if self.scalars_responses:
            return self.scalars_responses.pop(0)
        return Result().scalars()

    async def commit(self):
        self.events.append("commit")

    async def flush(self):
        self.events.append("flush")

    async def rollback(self):
        self.rollbacks += 1
        self.events.append("rollback")

    async def refresh(self, obj):
        self.events.append(("refresh", getattr(obj, "id", None)))

    def add(self, obj):
        self.events.append(("add", type(obj).__name__))
        self.added.append(obj)

    @asynccontextmanager
    async def begin_nested(self):
        self.events.append("begin_nested")
        yield self

    def sql(self, index):
        return " ".join(str(self.statements[index]).split())


def schedule(**kw):
    defaults = {
        "id": 11,
        "user_id": USER,
        "question_id": 100,
        "question_version_id": 900,
        "subject_id": 1,
        "interval": 3,
        "ease_factor": 2.5,
        "repetitions": 2,
        "next_review_at": NOW - timedelta(days=1),
        "last_reviewed_at": NOW - timedelta(days=5),
        "mastered": False,
        "is_active": True,
        "occurrence_seq": 4,
        "updated_at": NOW,
    }
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def revision(**kw):
    defaults = {
        "id": 900,
        "question_id": 100,
        "subject_id": 1,
        "subject_ref": SimpleNamespace(code="MATH", name="数学"),
        "question_type": "single_choice",
        "content": {"text": "题干"},
        "options": None,
        "answer": "A",
        "image_url": None,
    }
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def review_record(**kw):
    defaults = {
        "id": 5,
        "user_id": USER,
        "question_id": 100,
        "question_version_id": 900,
        "schedule_id": 11,
        "occurrence_seq": 4,
        "rating": 4,
        "user_answer": "A",
        "is_correct": True,
        "interval_after": 6,
        "ease_factor_after": 2.6,
        "next_review_at": NOW + timedelta(days=6),
        "mastery_percent": 65,
        "mastered": False,
    }
    defaults.update(kw)
    return SimpleNamespace(**defaults)


@pytest.fixture
def seams(monkeypatch):
    """Patch timing, locks, loaders and cross-service seams for entry tests."""

    class Ctl:
        def __init__(self):
            self.calls = []
            self.wq = None
            self.sync_result = None
            self.preparations = []
            self.task_state_result = None
            self.submit_results = {}
            self.session_calls = []
            self.revision_views = {}
            self.latest_ids = {}
            self.error_meta_map = {}

        def now(self, value=NOW):
            monkeypatch.setattr(rs, "utcnow", lambda: value)
            monkeypatch.setattr(rs, "shanghai_today", lambda: value.date())
            monkeypatch.setattr(
                rs, "shanghai_today_boundaries", lambda: (TODAY_START, TODAY_END)
            )
            monkeypatch.setattr(
                rs,
                "shanghai_date_utc_range",
                lambda day: (
                    datetime.combine(day, datetime.min.time()),
                    datetime.combine(day, datetime.min.time()) + timedelta(days=1),
                ),
            )
            return self

        def locks(self):
            calls = self.calls

            async def lock_request(db, *, user_id, request_id):
                calls.append(("lock_request", user_id, request_id))

            async def lock_question(db, *, user_id, question_id):
                calls.append(("lock", user_id, question_id))

            monkeypatch.setattr(rs, "lock_review_request", lock_request)
            monkeypatch.setattr(rs, "lock_question_review_state", lock_question)
            return self

        def replay(self, existing=None):
            async def loader(db, *, user_id, request_id):
                self.calls.append(("replay", request_id))
                return existing

            monkeypatch.setattr(rs, "_get_review_record_by_request", loader)
            return self

        def sync(self, result=None):
            async def loader(db, schedule_obj, **kwargs):
                self.calls.append(("sync", schedule_obj.question_id))
                return result

            monkeypatch.setattr(rs, "_sync_schedule_to_wq", loader)
            return self

        def loaders(self):
            async def latest(db, question_ids):
                return dict(self.latest_ids)

            async def views(db, revision_ids):
                self.calls.append(("views", tuple(revision_ids)))
                return dict(self.revision_views)

            monkeypatch.setattr(rs, "load_latest_question_revision_ids", latest)
            monkeypatch.setattr(rs, "load_revision_views", views)
            return self

        def subjects(self, ids=(1,)):
            async def loader(db):
                return set(ids)

            monkeypatch.setattr(rs, "_active_408_subject_ids", loader)
            return self

        def prepare(self, prepared):
            async def loader(db, *, user_id, schedules):
                self.preparations.append(list(schedules))
                return list(prepared)

            monkeypatch.setattr(rs, "_prepare_latest_review_revisions", loader)
            return self

        def task_state(self, state):
            async def loader(db, user_id):
                return dict(state)

            monkeypatch.setattr(rs, "_get_today_review_task_state", loader)
            return self

        def submit(self, by_question):
            calls = self.calls

            async def loader(db, user_id, **kwargs):
                question_id = kwargs["question_id"]
                calls.append(("submit", question_id))
                outcome = by_question[question_id]
                if isinstance(outcome, Exception):
                    raise outcome
                return dict(outcome)

            monkeypatch.setattr(rs, "submit_review", loader)
            return self

        def session_recorder(self):
            calls = self.session_calls

            async def loader(db, user_id, session_meta, results):
                calls.append((user_id, session_meta, [r["success"] for r in results]))

            monkeypatch.setattr(rs, "_record_review_session", loader)
            return self

        def error_meta(self, mapping):
            monkeypatch.setattr(
                rs,
                "_review_item_error_meta",
                lambda text: mapping.get(text, ("CODE", False, False)),
            )
            return self

        def normalize_session(self, window):
            monkeypatch.setattr(rs, "_normalize_review_session", lambda meta: window)
            return self

    return Ctl()


# ── submit_review ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_submit_review_applies_sm2_and_appends_record(monkeypatch, seams):
    seams.now().locks().loaders().replay(existing=None)
    sched = schedule()
    db = FakeDb(scalar_responses=[sched, 900])
    answer_calls = []

    async def update_state(db_, user_id, question_id, is_correct, answered_at=None):
        answer_calls.append((user_id, question_id, is_correct, answered_at))

    from app.services import question_review_service

    monkeypatch.setattr(
        question_review_service, "update_user_question_state_after_answer", update_state
    )
    seams.sync(result=None)

    payload = await rs.submit_review(
        db,
        USER,
        schedule_id=11,
        question_id=100,
        question_version_id=900,
        occurrence_seq=4,
        rating=4,
        request_id="req-1",
        user_answer="A",
    )

    expected = rs.calc_sm2(
        quality=4,
        efactor=2.5,
        interval=3,
        repetitions=2,
        review_date=NOW.date(),
    )
    assert payload["already_submitted"] is False
    assert payload["interval_after"] == expected["interval"]
    assert payload["ease_factor_after"] == expected["efactor"]
    assert (
        payload["next_review_at"]
        == rs.shanghai_date_utc_range(expected["next_review_date"])[0]
    )
    assert payload["is_correct"] is True
    assert payload["mastery_percent"] == rs.review_mastery_percent(
        expected["repetitions"]
    )
    assert sched.interval == expected["interval"]
    assert sched.repetitions == expected["repetitions"]
    assert sched.occurrence_seq == 5
    assert sched.last_reviewed_at == NOW
    assert answer_calls == [(USER, 100, True, NOW)]
    assert seams.calls[0] == ("lock_request", USER, "req-1")
    assert seams.calls[1] == ("lock", USER, 100)
    assert db.events.count("commit") == 1
    assert ("refresh", 11) in db.events
    added = [obj for obj in db.added if type(obj).__name__ == "ReviewRecord"]
    assert len(added) == 1
    record = added[0]
    assert record.user_id == USER
    assert record.question_id == 100
    assert record.question_version_id == 900
    assert record.occurrence_seq == 4
    assert record.rating == 4
    assert record.interval_before == 3
    assert record.interval_after == expected["interval"]
    assert record.ease_factor_before == 2.5
    assert record.ease_factor_after == expected["efactor"]
    assert record.is_correct is True
    assert record.schedule_id == 11
    assert record.request_id == "req-1"


@pytest.mark.asyncio
async def test_submit_review_skips_commit_when_auto_commit_false(monkeypatch, seams):
    seams.now().locks().loaders().replay(existing=None).sync()
    sched = schedule(repetitions=0, interval=1)
    db = FakeDb(scalar_responses=[sched, None])

    payload = await rs.submit_review(
        db,
        USER,
        schedule_id=11,
        question_id=100,
        question_version_id=900,
        occurrence_seq=4,
        rating=1,
        request_id="req-2",
        auto_commit=False,
        user_answer="",
        latest_wrong_answer="B",
    )

    assert payload["is_correct"] is False
    assert payload["mastered"] is False
    assert db.events.count("commit") == 0
    assert not any(
        isinstance(event, tuple) and event[0] == "refresh" for event in db.events
    )
    assert any(call[0] == "sync" for call in seams.calls)


@pytest.mark.asyncio
async def test_submit_review_replays_identical_request(monkeypatch, seams):
    existing = review_record()
    seams.now().locks().loaders().replay(existing=existing)
    db = FakeDb()

    payload = await rs.submit_review(
        db,
        USER,
        schedule_id=11,
        question_id=100,
        question_version_id=900,
        occurrence_seq=4,
        rating=4,
        request_id="req-1",
        user_answer="A",
    )

    assert payload["already_submitted"] is True
    assert payload["interval_after"] == existing.interval_after
    assert payload["ease_factor_after"] == existing.ease_factor_after
    assert payload["mastery_percent"] == 65
    assert payload["mastered"] is False
    assert db.statements == []
    assert db.events == []


@pytest.mark.asyncio
async def test_submit_review_rejects_replay_reuse(monkeypatch, seams):
    existing = review_record(rating=3, user_answer="B")
    seams.now().locks().loaders().replay(existing=existing)
    db = FakeDb()

    with pytest.raises(ValueError, match="已用于不同提交"):
        await rs.submit_review(
            db,
            USER,
            schedule_id=11,
            question_id=100,
            question_version_id=900,
            occurrence_seq=4,
            rating=4,
            request_id="req-1",
            user_answer="A",
        )
    assert db.statements == []


@pytest.mark.parametrize(
    ("sched_kwargs", "expected"),
    [
        (None, "复习记录不存在"),
        ({"question_id": 999}, "题目与复习记录不匹配"),
        ({"is_active": False}, "已从复习队列移除"),
        ({"mastered": True}, "已标记掌握"),
        ({"question_version_id": 901}, "版本已更新"),
        ({"occurrence_seq": 9}, "已经提交或已失效"),
    ],
)
@pytest.mark.asyncio
async def test_submit_review_rejects_invalid_schedule(
    monkeypatch, seams, sched_kwargs, expected
):
    seams.now().locks().loaders().replay(existing=None)
    sched = None if sched_kwargs is None else schedule(**sched_kwargs)
    db = FakeDb(scalar_responses=[sched])

    with pytest.raises(ValueError, match=expected):
        await rs.submit_review(
            db,
            USER,
            schedule_id=11,
            question_id=100,
            question_version_id=900,
            occurrence_seq=4,
            rating=4,
            request_id="req-1",
            user_answer="A",
        )
    assert db.events.count("commit") == 0


@pytest.mark.asyncio
async def test_submit_review_rejects_out_of_range_rating_before_locking(seams):
    db = FakeDb()
    with pytest.raises(ValueError, match="评分必须在 0-5 之间"):
        await rs.submit_review(
            db,
            USER,
            schedule_id=11,
            question_id=100,
            question_version_id=900,
            occurrence_seq=4,
            rating=6,
            request_id="req-1",
        )
    assert seams.calls == []
    assert db.statements == []


# ── _prepare_latest_review_revisions ────────────────────────────────


@pytest.mark.asyncio
async def test_prepare_revisions_empty_list(seams):
    assert (
        await rs._prepare_latest_review_revisions(FakeDb(), user_id=USER, schedules=[])
        == []
    )


@pytest.mark.asyncio
async def test_prepare_revisions_rebinds_stale_schedule(monkeypatch, seams):
    seams.now().locks().loaders().sync()
    seams.latest_ids = {100: 901}
    seams.revision_views = {901: revision(id=901)}
    stale = schedule(question_version_id=900, subject_id=1)
    locked = schedule(question_version_id=900, subject_id=1, occurrence_seq=7)
    db = FakeDb(scalar_responses=[locked])

    prepared = await rs._prepare_latest_review_revisions(
        db, user_id=USER, schedules=[stale]
    )

    assert prepared == [(locked, seams.revision_views[901])]
    assert locked.question_version_id == 901
    assert locked.subject_id == 1
    assert locked.occurrence_seq == 8
    assert db.events.count("flush") == 1
    assert db.events.count("commit") == 1
    assert any(call[0] == "sync" for call in seams.calls)


@pytest.mark.asyncio
async def test_prepare_revisions_skips_missing_revision(monkeypatch, seams):
    warnings = []

    class Logger:
        def warning(self, msg, *args, **kwargs):
            warnings.append(msg % args)

    seams.now().locks().loaders()
    seams.latest_ids = {100: 901}
    seams.revision_views = {}
    monkeypatch.setattr(rs, "logger", Logger())
    db = FakeDb()

    prepared = await rs._prepare_latest_review_revisions(
        db, user_id=USER, schedules=[schedule()]
    )

    assert prepared == []
    assert warnings == [
        "review.latest_revision_missing uid=7 schedule_id=11 question_id=100"
    ]


@pytest.mark.asyncio
async def test_prepare_revisions_skips_inactive_or_mastered_locked_row(
    monkeypatch, seams
):
    seams.now().locks().loaders()
    seams.latest_ids = {100: 901}
    seams.revision_views = {901: revision(id=901)}
    db = FakeDb(scalar_responses=[schedule(is_active=False, occurrence_seq=7)])

    prepared = await rs._prepare_latest_review_revisions(
        db, user_id=USER, schedules=[schedule(question_version_id=900)]
    )

    assert prepared == []
    assert db.events.count("commit") == 0


@pytest.mark.asyncio
async def test_prepare_revisions_uses_row_rebound_by_other_request(monkeypatch, seams):
    seams.now().locks().loaders().sync()
    seams.latest_ids = {100: 901}
    seams.revision_views = {901: revision(id=901)}
    locked = schedule(question_version_id=901, occurrence_seq=7)
    db = FakeDb(scalar_responses=[locked])

    prepared = await rs._prepare_latest_review_revisions(
        db, user_id=USER, schedules=[schedule(question_version_id=900)]
    )

    assert prepared == [(locked, seams.revision_views[901])]
    assert locked.occurrence_seq == 7
    assert db.events.count("commit") == 0
    assert db.events.count("flush") == 0


@pytest.mark.asyncio
async def test_prepare_revisions_keeps_pinned_revision_without_latest_index(seams):
    seams.now().locks().loaders()
    seams.latest_ids = {}
    seams.revision_views = {900: revision(id=900)}
    db = FakeDb()

    prepared = await rs._prepare_latest_review_revisions(
        db, user_id=USER, schedules=[schedule(question_version_id=900)]
    )

    assert len(prepared) == 1
    assert prepared[0][0].question_version_id == 900
    assert db.events.count("commit") == 0


# ── set_mastered_state ───────────────────────────────────────────────


def wrong_question(**kw):
    defaults = {
        "id": 3,
        "user_id": USER,
        "question_id": 100,
        "question_version_id": 900,
        "mastered": False,
        "mastered_at": None,
        "is_active": True,
    }
    defaults.update(kw)
    return SimpleNamespace(**defaults)


@pytest.mark.asyncio
async def test_set_mastered_state_transitions_and_stamps_event(monkeypatch, seams):
    seams.now().locks()
    wq = wrong_question()
    sched = schedule(mastered=False, occurrence_seq=2)
    db = FakeDb(scalar_responses=[wq, sched])

    changed = await rs.set_mastered_state(
        db, user_id=USER, question_id=100, mastered=True
    )

    assert changed is True
    assert wq.mastered is True
    assert wq.mastered_at == NOW
    assert sched.mastered is True
    assert sched.occurrence_seq == 3
    assert db.events.count("flush") == 1
    assert seams.calls == [("lock", USER, 100)]


@pytest.mark.asyncio
async def test_set_mastered_state_repair_is_not_a_transition(monkeypatch, seams):
    seams.now().locks()
    wq = wrong_question(mastered=True, mastered_at=None)
    sched = schedule(mastered=True, occurrence_seq=2)
    db = FakeDb(scalar_responses=[wq, sched])

    changed = await rs.set_mastered_state(
        db, user_id=USER, question_id=100, mastered=True
    )

    assert changed is False
    assert wq.mastered_at is None
    assert sched.occurrence_seq == 2
    assert db.events.count("flush") == 1


@pytest.mark.asyncio
async def test_set_mastered_state_clears_stale_metadata_without_transition(
    monkeypatch, seams
):
    seams.now().locks()
    wq = wrong_question(mastered=False, mastered_at=NOW - timedelta(days=3))
    sched = schedule(mastered=False)
    db = FakeDb(scalar_responses=[wq, sched])

    changed = await rs.set_mastered_state(
        db, user_id=USER, question_id=100, mastered=False
    )

    assert changed is False
    assert wq.mastered_at is None


@pytest.mark.asyncio
async def test_set_mastered_state_restores_missing_schedule(monkeypatch, seams):
    seams.now().locks().loaders()
    seams.revision_views = {900: revision(id=900)}
    wq = wrong_question()
    db = FakeDb(scalar_responses=[wq, None])

    changed = await rs.set_mastered_state(
        db, user_id=USER, question_id=100, mastered=False
    )

    assert changed is True
    added = [obj for obj in db.added if type(obj).__name__ == "ReviewSchedule"]
    assert len(added) == 1
    created = added[0]
    assert created.user_id == USER
    assert created.question_id == 100
    assert created.question_version_id == 900
    assert created.next_review_at == NOW
    assert created.interval == 1
    assert created.repetitions == 0
    assert created.occurrence_seq == 0
    assert created.mastered is False
    assert created.is_active is True


@pytest.mark.asyncio
async def test_set_mastered_state_raises_when_revision_missing(monkeypatch, seams):
    seams.now().locks().loaders()
    seams.revision_views = {}
    db = FakeDb(scalar_responses=[wrong_question(), None])

    with pytest.raises(ValueError, match="错题版本不存在"):
        await rs.set_mastered_state(db, user_id=USER, question_id=100, mastered=False)


@pytest.mark.asyncio
async def test_set_mastered_state_without_schedule_still_tracks_wrong_book(
    monkeypatch, seams
):
    seams.now().locks()
    wq = wrong_question()
    db = FakeDb(scalar_responses=[wq, None])

    changed = await rs.set_mastered_state(
        db, user_id=USER, question_id=100, mastered=True
    )

    assert changed is True
    assert wq.mastered is True
    assert wq.mastered_at == NOW
    assert not any(type(obj).__name__ == "ReviewSchedule" for obj in db.added)


# ── get_today_review ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_today_review_rejects_foreign_subject(monkeypatch, seams):
    seams.now().subjects({1})
    db = FakeDb()

    payload = await rs.get_today_review(db, USER, subject_id=9)

    assert payload == {"total_today": 0, "questions": []}
    assert db.statements == []


@pytest.mark.asyncio
async def test_get_today_review_projects_payload_and_filters(monkeypatch, seams):
    seams.now().subjects({1, 2}).loaders()
    sched = schedule()
    seams.prepare([(sched, revision())])
    db = FakeDb(
        scalar_responses=[3],
        scalars_responses=[Result(rows=[sched]).scalars()],
    )

    payload = await rs.get_today_review(db, USER, subject_id=1, limit=7)

    assert payload["total_today"] == 3
    assert payload["questions"] == [rs._review_question_payload(sched, revision())]
    assert seams.preparations == [[sched]]
    count_sql = db.sql(0).lower()
    assert "review_schedules.next_review_at <=" in count_sql
    assert "review_schedules.is_active" in count_sql
    assert "review_schedules.subject_id =" in count_sql
    assert "questions_versions" not in count_sql
    assert "limit" in db.sql(1).lower()


# ── get_review_stats ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_review_stats_projects_counts_and_subjects(monkeypatch, seams):
    seams.now()
    db = FakeDb(
        execute_responses=[
            Result(scalar=10),
            Result(scalar=4),
            Result(scalar=6),
            Result(scalar=2),
            Result(one=(4, 3)),
            Result(rows=[(1, 5, 2)]),
            Result(rows=[(1, 3)]),
            Result(rows=[SimpleNamespace(id=1, code="MATH", name="数学")]),
        ]
    )

    stats = await rs.get_review_stats(db, USER, days=7)

    assert stats == {
        "total_scheduled": 10,
        "total_reviewed_today": 4,
        "remaining_today": 6,
        "overdue": 2,
        "accuracy_last_7d": 0.75,
        "by_subject": [
            {
                "subject_id": 1,
                "subject_code": "MATH",
                "subject_name": "数学",
                "scheduled": 5,
                "reviewed": 3,
                "remaining": 2,
            }
        ],
    }
    assert len(db.statements) == 8
    assert "wrong_questions" not in db.sql(0).lower()


@pytest.mark.asyncio
async def test_review_stats_tolerates_missing_values(monkeypatch, seams):
    seams.now()
    db = FakeDb(
        execute_responses=[
            Result(scalar=None),
            Result(scalar=None),
            Result(scalar=None),
            Result(scalar=None),
            Result(one=(0, 0)),
            Result(rows=[]),
            Result(rows=[]),
        ]
    )

    stats = await rs.get_review_stats(db, USER)

    assert stats["total_scheduled"] is None
    assert stats["accuracy_last_7d"] == 0.0
    assert stats["by_subject"] == []
    assert len(db.statements) == 7  # subject code lookup skipped without ids


# ── auto_schedule_wrong_question ─────────────────────────────────────


@pytest.mark.asyncio
async def test_auto_schedule_resets_existing_schedule(monkeypatch, seams):
    seams.now().locks().loaders().sync()
    seams.revision_views = {900: revision(id=900)}
    existing = schedule(
        interval=9,
        ease_factor=1.7,
        repetitions=5,
        mastered=True,
        is_active=False,
        last_reviewed_at=NOW,
        occurrence_seq=3,
        subject_id=99,
        question_version_id=901,
    )
    db = FakeDb(scalar_responses=[existing])

    result = await rs.auto_schedule_wrong_question(db, USER, 100, 900, commit=True)

    assert result is existing
    assert existing.question_version_id == 900
    assert existing.subject_id == 1
    assert existing.interval == 1
    assert existing.ease_factor == 2.5
    assert existing.repetitions == 0
    assert existing.mastered is False
    assert existing.is_active is True
    assert existing.last_reviewed_at is None
    assert (
        existing.next_review_at
        == rs.shanghai_date_utc_range((NOW + timedelta(days=1)).date())[0]
    )
    assert existing.occurrence_seq == 4
    assert db.events.count("commit") == 1
    assert ("refresh", 11) in db.events
    assert not any(type(obj).__name__ == "ReviewSchedule" for obj in db.added)
    assert seams.calls[0] == ("lock", USER, 100)


@pytest.mark.asyncio
async def test_auto_schedule_creates_missing_schedule_with_flush_only(
    monkeypatch, seams
):
    seams.now().locks().loaders().sync()
    seams.revision_views = {900: revision(id=900)}
    db = FakeDb(scalar_responses=[None])

    result = await rs.auto_schedule_wrong_question(db, USER, 100, 900, commit=False)

    assert type(result).__name__ == "ReviewSchedule"
    assert result.user_id == USER
    assert result.question_id == 100
    assert result.question_version_id == 900
    assert result.interval == 1
    assert result.ease_factor == 2.5
    assert result.repetitions == 0
    assert result.occurrence_seq == 0
    assert result.mastered is False
    assert result.is_active is True
    assert db.events.count("commit") == 0
    assert db.events.count("flush") == 1
    assert len(db.added) == 1


@pytest.mark.asyncio
async def test_auto_schedule_rejects_revision_mismatch(monkeypatch, seams):
    seams.now().locks().loaders()
    seams.revision_views = {900: revision(id=900, question_id=999)}
    db = FakeDb()

    with pytest.raises(ValueError, match="错题版本不存在或与题目不匹配"):
        await rs.auto_schedule_wrong_question(db, USER, 100, 900)
    assert db.statements == []


# ── today review task state / overview / result ─────────────────────


@pytest.mark.asyncio
async def test_today_review_task_state_merges_due_reviewed_and_mastered(
    monkeypatch, seams
):
    seams.now().subjects({1})
    due_a = schedule(
        id=1, question_id=10, next_review_at=TODAY_END - timedelta(hours=1)
    )
    due_b = schedule(id=2, question_id=20, next_review_at=None)
    reviewed_c = schedule(id=5, question_id=30, next_review_at=TODAY_END)
    mastered_d = schedule(id=6, question_id=50, mastered=True, next_review_at=TODAY_END)
    db = FakeDb(
        execute_responses=[
            Result(rows=[(5, 30), (None, 40)]),
            Result(rows=[(30,), (50,)]),
        ],
        scalars_responses=[
            Result(rows=[due_a, due_b]).scalars(),
            Result(rows=[reviewed_c]).scalars(),
            Result(rows=[mastered_d]).scalars(),
        ],
    )

    state = await rs._get_today_review_task_state(db, USER)

    assert state["today_start"] == TODAY_START
    assert state["today_end"] == TODAY_END
    assert [s.id for s in state["task_schedules"]] == [1, 2, 5, 6]
    assert [s.id for s in state["pending_schedules"]] == [1, 2]
    assert state["task_question_ids"] == {10, 20, 30, 50}
    assert state["completed_question_ids"] == {30, 50}
    assert state["mastered_question_ids"] == {30, 50}
    assert len(db.statements) == 5
    assert "review_schedules.next_review_at <=" in db.sql(0).lower()


@pytest.mark.asyncio
async def test_today_review_task_state_skips_queries_without_rows(monkeypatch, seams):
    seams.now().subjects({1})
    db = FakeDb(
        execute_responses=[Result(rows=[]), Result(rows=[])],
        scalars_responses=[
            Result(rows=[]).scalars(),
            Result(rows=[]).scalars(),
        ],
    )

    state = await rs._get_today_review_task_state(db, USER)

    assert state["task_schedules"] == []
    assert state["pending_schedules"] == []
    assert state["completed_question_ids"] == set()
    assert len(db.statements) == 3  # reviewed-schedule and mastered-id lookups skipped


@pytest.mark.asyncio
async def test_today_review_overview_metrics(monkeypatch, seams):
    seams.now()
    tasks = [schedule(id=index, question_id=index) for index in range(1, 13)]
    pending = [
        schedule(id=1, question_id=1, next_review_at=TODAY_START - timedelta(hours=1)),
        schedule(id=2, question_id=2, next_review_at=TODAY_START - timedelta(hours=2)),
        schedule(id=3, question_id=3, next_review_at=TODAY_END),
        schedule(id=4, question_id=4, next_review_at=TODAY_END),
        schedule(id=5, question_id=5, next_review_at=TODAY_END),
    ]
    seams.task_state(
        {
            "today_start": TODAY_START,
            "today_end": TODAY_END,
            "task_schedules": tasks,
            "pending_schedules": pending,
            "task_question_ids": {s.question_id for s in tasks},
            "completed_question_ids": {6, 7, 8},
            "mastered_question_ids": {6, 7, 8},
        }
    )
    db = FakeDb()

    overview = await rs.get_today_review_overview(db, USER)

    assert overview["today_due_count"] == 12
    assert overview["today_completed_count"] == 7
    assert overview["today_remaining_count"] == 5
    assert overview["today_overdue_count"] == 2
    assert overview["today_new_due_count"] == 3
    assert overview["estimated_minutes"] == 3
    assert overview["batch_size"] == 10
    assert overview["current_batch_no"] == 1
    assert overview["total_batch_count"] == 2
    assert overview["remaining_batch_count"] == 1
    assert overview["all_question_ids"] == [s.question_id for s in tasks]
    assert overview["completed_question_ids"] == [6, 7, 8]
    assert overview["remaining_question_ids"] == [1, 2, 3, 4, 5]
    assert overview["has_due_review"] is True
    assert overview["is_completed"] is False
    assert db.statements == []


@pytest.mark.asyncio
async def test_today_review_overview_empty_and_complete_states(monkeypatch, seams):
    seams.now()
    seams.task_state(
        {
            "today_start": TODAY_START,
            "today_end": TODAY_END,
            "task_schedules": [],
            "pending_schedules": [],
            "task_question_ids": set(),
            "completed_question_ids": set(),
            "mastered_question_ids": set(),
        }
    )
    empty = await rs.get_today_review_overview(FakeDb(), USER)
    assert empty["today_due_count"] == 0
    assert empty["estimated_minutes"] == 0
    assert empty["remaining_batch_count"] == 0
    assert empty["current_batch_no"] == 1
    assert empty["total_batch_count"] == 1
    assert empty["has_due_review"] is False
    assert empty["is_completed"] is False

    tasks = [schedule(id=index, question_id=index) for index in range(1, 11)]
    seams.task_state(
        {
            "today_start": TODAY_START,
            "today_end": TODAY_END,
            "task_schedules": tasks,
            "pending_schedules": [],
            "task_question_ids": {s.question_id for s in tasks},
            "completed_question_ids": {s.question_id for s in tasks},
            "mastered_question_ids": set(),
        }
    )
    done = await rs.get_today_review_overview(FakeDb(), USER)
    assert done["today_completed_count"] == 10
    assert done["current_batch_no"] == 1
    assert done["total_batch_count"] == 1
    assert done["remaining_batch_count"] == 0
    assert done["is_completed"] is True


@pytest.mark.asyncio
async def test_today_review_result_metrics(monkeypatch, seams):
    seams.now().loaders()
    seams.revision_views = {
        900: revision(id=900),
        901: revision(
            id=901,
            question_id=101,
            subject_id=2,
            subject_ref=SimpleNamespace(code="408", name="408"),
            answer="B",
            question_type="judge",
        ),
    }
    state = {
        "today_start": TODAY_START,
        "today_end": TODAY_END,
        "task_schedules": [schedule(id=1), schedule(id=2), schedule(id=3)],
        "pending_schedules": [schedule(id=1)],
        "task_question_ids": {100, 101, 102},
        "completed_question_ids": {100, 101},
        "mastered_question_ids": {102, 103},
    }
    seams.task_state(state)
    first = review_record(
        id=1, question_id=100, is_correct=True, question_version_id=900
    )
    duplicate = review_record(
        id=2, question_id=100, is_correct=False, question_version_id=900
    )
    third = review_record(
        id=3, question_id=101, is_correct=False, question_version_id=901
    )
    db = FakeDb(
        execute_responses=[
            Result(rows=[first, duplicate, third]),
            Result(scalar=5),
        ]
    )

    payload = await rs.get_today_review_result(db, USER)

    assert payload["today_due_count"] == 3
    assert payload["today_completed_count"] == 2
    assert payload["correct_count"] == 1
    assert payload["wrong_count"] == 1
    assert payload["skipped_count"] == 0
    assert payload["mastered_count"] == 2
    assert payload["accuracy"] == 0.5
    assert payload["completion_rate"] == round(2 / 3, 4)
    assert payload["updated_schedule_count"] == 2
    assert payload["tomorrow_due_count"] == 5
    assert payload["is_completed"] is False
    assert payload["subject_stats"] == [
        {
            "subject_id": 1,
            "subject_code": "MATH",
            "subject_name": "数学",
            "reviewed": 1,
            "correct": 1,
            "wrong": 0,
            "skipped": 0,
        },
        {
            "subject_id": 2,
            "subject_code": "408",
            "subject_name": "408",
            "reviewed": 1,
            "correct": 0,
            "wrong": 1,
            "skipped": 0,
        },
    ]


@pytest.mark.asyncio
async def test_today_review_result_without_task_ids(monkeypatch, seams):
    seams.now().loaders()
    seams.task_state(
        {
            "today_start": TODAY_START,
            "today_end": TODAY_END,
            "task_schedules": [],
            "pending_schedules": [],
            "task_question_ids": set(),
            "completed_question_ids": set(),
            "mastered_question_ids": set(),
        }
    )
    db = FakeDb(execute_responses=[Result(scalar=0)])

    payload = await rs.get_today_review_result(db, USER)

    assert payload["today_due_count"] == 0
    assert payload["accuracy"] == 0.0
    assert payload["completion_rate"] == 0.0
    assert payload["subject_stats"] == []
    assert len(db.statements) == 1


# ── _record_review_session ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_review_session_records_per_subject_rows(monkeypatch, seams):
    window = {
        "request_id": "seg-1",
        "started_at": NOW - timedelta(seconds=100),
        "finished_at": NOW,
        "duration_sec": 100,
    }
    seams.normalize_session(window)
    db = FakeDb(
        execute_responses=[Result(rows=[(11, 1), (12, 1), (13, 2)])],
        scalar_responses=[0],
    )
    results = [
        {"success": True, "schedule_id": 11, "is_correct": True},
        {"success": True, "schedule_id": 12, "is_correct": True},
        {"success": True, "schedule_id": 13, "is_correct": False},
        {"success": False, "schedule_id": 14, "is_correct": False},
    ]

    await rs._record_review_session(db, USER, {"request_id": "seg-1"}, results)

    sessions = [obj for obj in db.added if type(obj).__name__ == "ReviewSession"]
    assert [session.subject_id for session in sessions] == [1, 2]
    assert [session.question_count for session in sessions] == [2, 1]
    assert [session.correct_count for session in sessions] == [2, 0]
    assert [session.wrong_count for session in sessions] == [0, 1]
    assert [session.duration_sec for session in sessions] == [67, 33]
    assert [session.request_id for session in sessions] == ["seg-1:1", "seg-1:2"]
    assert all(session.status == "completed" for session in sessions)
    assert all(session.started_at == window["started_at"] for session in sessions)
    assert db.events.count("commit") == 1


@pytest.mark.asyncio
async def test_review_session_skips_replays_and_unsuccessful_results(
    monkeypatch, seams
):
    seams.normalize_session(
        {
            "request_id": "seg-2",
            "started_at": NOW,
            "finished_at": NOW,
            "duration_sec": 60,
        }
    )
    db = FakeDb(
        execute_responses=[Result(rows=[(11, 1)])],
        scalar_responses=[2],
    )
    await rs._record_review_session(
        db, USER, {"request_id": "seg-2"}, [{"success": True, "schedule_id": 11}]
    )
    assert db.added == []
    assert db.events.count("commit") == 0

    seams.normalize_session(
        {
            "request_id": "seg-3",
            "started_at": NOW,
            "finished_at": NOW,
            "duration_sec": 30,
        }
    )
    warnings = []
    monkeypatch.setattr(
        rs.logger, "warning", lambda msg, *args, **kwargs: warnings.append(msg % args)
    )
    db2 = FakeDb(
        execute_responses=[Result(rows=[(11, 1)])],
        scalar_responses=[0],
    )

    async def failing_commit():
        raise RuntimeError("commit down")

    monkeypatch.setattr(db2, "commit", failing_commit)
    await rs._record_review_session(
        db2, USER, {"request_id": "seg-3"}, [{"success": True, "schedule_id": 11}]
    )
    assert db2.rollbacks == 1
    assert warnings == ["review session timing record failed uid=7"]


# ── grade_batch_review ───────────────────────────────────────────────


def batch_item(index, **kw):
    defaults = {
        "schedule_id": 11,
        "question_id": 100,
        "question_version_id": 900,
        "occurrence_seq": 4,
        "request_id": f"req-{index}",
        "user_answer": "A",
    }
    defaults.update(kw)
    return defaults


@pytest.mark.asyncio
async def test_grade_batch_review_rejects_empty_batch(monkeypatch, seams):
    db = FakeDb()
    with pytest.raises(ValueError, match="复习列表不能为空"):
        await rs.grade_batch_review(db, USER, [])
    assert db.statements == []


@pytest.mark.asyncio
async def test_grade_batch_review_grades_orders_and_prewarms(monkeypatch, seams):
    seams.loaders().error_meta({})
    seams.revision_views = {
        900: revision(id=900),
        901: revision(id=901, question_id=101, answer="B", question_type="judge"),
    }
    seams.submit(
        {
            100: {
                "schedule_id": 11,
                "question_id": 100,
                "question_version_id": 900,
                "occurrence_seq": 4,
                "rating": 4,
                "interval_after": 6,
                "ease_factor_after": 2.6,
                "next_review_at": NOW + timedelta(days=6),
                "is_correct": True,
                "mastery_percent": 65,
                "mastered": False,
                "wrong_question_id": None,
                "wrong_review_count": None,
                "wrong_answer": None,
            },
            101: {
                "schedule_id": 12,
                "question_id": 101,
                "question_version_id": 901,
                "occurrence_seq": 2,
                "rating": 1,
                "interval_after": 1,
                "ease_factor_after": 2.3,
                "next_review_at": NOW + timedelta(days=1),
                "is_correct": False,
                "mastery_percent": 20,
                "mastered": False,
                "wrong_question_id": 55,
                "wrong_review_count": 3,
                "wrong_answer": "B",
            },
        }
    )
    seams.session_recorder()
    prewarm_calls = []

    from app import ai  # noqa: F401  (import path anchor)
    from app.services import ai_prewarm_worker

    async def enqueue(wq_id, user_id, *, revision):
        prewarm_calls.append((wq_id, user_id, revision))

    monkeypatch.setattr(ai_prewarm_worker, "enqueue_prewarm", enqueue)
    import app.ai.prewarm_revision as prewarm_revision_module

    monkeypatch.setattr(
        prewarm_revision_module,
        "build_prewarm_revision",
        lambda *, review_count, wrong_answer: f"rev:{review_count}:{wrong_answer}",
    )
    db = FakeDb()

    payload = await rs.grade_batch_review(
        db,
        USER,
        [
            batch_item(1, question_id=101, schedule_id=12, question_version_id=901),
            batch_item(2),
            batch_item(3, question_id=102, question_version_id=902),
        ],
        session_meta={"request_id": "seg-9"},
    )

    assert [item["question_id"] for item in payload["results"]] == [101, 100, 102]
    assert payload["total"] == 3
    assert payload["correct_count"] == 1
    assert payload["wrong_count"] == 1
    assert [call[1] for call in seams.calls if call[0] == "submit"] == [100, 101]
    assert db.events.count("commit") == 1
    assert prewarm_calls == [(55, USER, "rev:3:B")]
    assert seams.session_calls[0][0] == USER
    assert seams.session_calls[0][2] == [True, True, False]
    missing = payload["results"][2]
    assert missing["error_code"] == "REVIEW_VERSION_MISSING"
    assert missing["refresh_required"] is True
    assert missing["success"] is False
    wrong = payload["results"][0]
    assert wrong["success"] is True
    assert wrong["is_correct"] is False
    assert wrong["correct_answer"] == "B"
    assert wrong["rating"] == 1
    assert wrong["mastery_percent"] == 20


@pytest.mark.asyncio
async def test_grade_batch_review_maps_submit_errors(monkeypatch, seams):
    seams.loaders().session_recorder()
    seams.error_meta(
        {"复习题版本已更新，请刷新后重试": ("REVIEW_VERSION_MISMATCH", True, True)}
    )
    seams.revision_views = {900: revision(id=900)}
    seams.submit({100: ValueError("复习题版本已更新，请刷新后重试")})
    db = FakeDb()

    payload = await rs.grade_batch_review(db, USER, [batch_item(1)])

    result = payload["results"][0]
    assert result["success"] is False
    assert result["error_code"] == "REVIEW_VERSION_MISMATCH"
    assert result["retryable"] is True
    assert result["refresh_required"] is True
    assert result["correct_answer"] == "A"
    assert result["rating"] == 4
    assert payload["correct_count"] == 0
    assert payload["wrong_count"] == 0
    assert db.events.count("commit") == 1


# ── hardening assertions (mutation-killing coverage) ─────────────────


@pytest.mark.asyncio
async def test_submit_review_mastered_transition_projects_to_schedule_and_record(
    monkeypatch, seams
):
    """A rating that crosses the auto-mastery threshold must reach every projection."""
    seams.now().locks().loaders().replay(existing=None).sync()
    sched = schedule(repetitions=2, interval=3, ease_factor=2.5, mastered=False)
    db = FakeDb(scalar_responses=[sched, 900])

    from app.services import question_review_service

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(
        question_review_service, "update_user_question_state_after_answer", noop
    )

    payload = await rs.submit_review(
        db,
        USER,
        schedule_id=11,
        question_id=100,
        question_version_id=900,
        occurrence_seq=4,
        rating=5,
        request_id="req-m",
        user_answer="A",
    )

    expected = rs.calc_sm2(
        quality=5, efactor=2.5, interval=3, repetitions=2, review_date=NOW.date()
    )
    assert rs.review_auto_mastered(expected["repetitions"]) is True
    assert sched.ease_factor == expected["efactor"]
    assert sched.repetitions == expected["repetitions"]
    assert sched.mastered is True
    assert payload["mastered"] is True
    assert payload["mastery_percent"] == rs.review_mastery_percent(
        expected["repetitions"]
    )
    record = next(obj for obj in db.added if type(obj).__name__ == "ReviewRecord")
    assert record.mastered is True
    assert record.ease_factor_after == expected["efactor"]
    assert record.interval_after == expected["interval"]


@pytest.mark.parametrize(
    "override",
    [
        {"question_id": 999},
        {"question_version_id": 901},
        {"schedule_id": 12},
        {"occurrence_seq": 5},
        {"rating": 1},
        {"user_answer": "B"},
    ],
)
@pytest.mark.asyncio
async def test_submit_review_rejects_any_replay_field_mismatch(
    monkeypatch, seams, override
):
    """Every replay identity field is part of the idempotency key."""
    existing = review_record(**override)
    seams.now().locks().loaders().replay(existing=existing)
    db = FakeDb()

    with pytest.raises(ValueError, match="已用于不同提交"):
        await rs.submit_review(
            db,
            USER,
            schedule_id=11,
            question_id=100,
            question_version_id=900,
            occurrence_seq=4,
            rating=4,
            request_id="req-1",
            user_answer="A",
        )
    assert db.statements == []


@pytest.mark.asyncio
async def test_submit_review_replay_payload_defaults_and_flags(monkeypatch, seams):
    """Replay payload falls back to stored defaults and keeps the stored outcome."""
    existing = review_record(
        interval_after=None,
        ease_factor_after=None,
        mastery_percent=None,
        is_correct=False,
        mastered=False,
    )
    seams.now().locks().loaders().replay(existing=existing)
    db = FakeDb()

    payload = await rs.submit_review(
        db,
        USER,
        schedule_id=11,
        question_id=100,
        question_version_id=900,
        occurrence_seq=4,
        rating=4,
        request_id="req-1",
        user_answer="A",
    )

    assert payload == {
        "schedule_id": 11,
        "question_id": 100,
        "question_version_id": 900,
        "occurrence_seq": 4,
        "request_id": "req-1",
        "rating": 4,
        "interval_after": 0,
        "ease_factor_after": 2.5,
        "next_review_at": existing.next_review_at,
        "is_correct": False,
        "mastery_percent": 20,
        "mastered": False,
        "already_submitted": True,
    }


@pytest.mark.asyncio
async def test_submit_review_missing_schedule_error_names_the_schedule(seams):
    seams.now().locks().loaders().replay(existing=None)
    db = FakeDb(scalar_responses=[None])

    with pytest.raises(ValueError) as excinfo:
        await rs.submit_review(
            db,
            USER,
            schedule_id=11,
            question_id=100,
            question_version_id=900,
            occurrence_seq=4,
            rating=4,
            request_id="req-1",
            user_answer="A",
        )
    assert str(excinfo.value) == "复习记录不存在: 11"


@pytest.mark.asyncio
async def test_submit_review_mirrors_state_only_for_the_latest_revision(
    monkeypatch, seams
):
    """The per-question mirror forwards the real outcome, and only for the newest id."""
    calls = []

    async def update_state(db_, user_id, question_id, is_correct, answered_at=None):
        calls.append((user_id, question_id, is_correct))

    from app.services import question_review_service

    monkeypatch.setattr(
        question_review_service, "update_user_question_state_after_answer", update_state
    )

    seams.now().locks().loaders().replay(existing=None).sync()
    stale = FakeDb(scalar_responses=[schedule(), 901])
    await rs.submit_review(
        stale,
        USER,
        schedule_id=11,
        question_id=100,
        question_version_id=900,
        occurrence_seq=4,
        rating=1,
        request_id="req-s",
        user_answer="B",
    )
    assert calls == []

    current = FakeDb(scalar_responses=[schedule(), 900])
    await rs.submit_review(
        current,
        USER,
        schedule_id=11,
        question_id=100,
        question_version_id=900,
        occurrence_seq=4,
        rating=1,
        request_id="req-c",
        user_answer="B",
    )
    assert calls == [(USER, 100, False)]


def test_review_session_window_clamps_and_drops_impossible_durations(seams):
    """The timing window is clamped to the review-session cap and rejects <= 0."""
    seams.now()
    cap = rs.REVIEW_SESSION_MAX_DURATION_SEC
    meta = {
        "request_id": "seg-cap",
        "started_at": NOW - timedelta(seconds=10),
        "finished_at": NOW,
        "duration_sec": cap + 9999,
    }

    window = rs._normalize_review_session(meta)

    assert window["duration_sec"] == cap
    assert window["finished_at"] == NOW
    assert window["request_id"] == "seg-cap"

    assert rs._normalize_review_session(dict(meta, duration_sec=0)) is None
    assert rs._normalize_review_session(dict(meta, duration_sec=-5)) is None
    assert rs._normalize_review_session({"request_id": "  "}) is None
    assert rs._normalize_review_session(None) is None


@pytest.mark.asyncio
async def test_review_session_remainder_prefers_the_largest_group(monkeypatch, seams):
    """Left-over seconds go to the largest group, not to insertion order."""
    window = {
        "request_id": "seg-r",
        "started_at": NOW - timedelta(seconds=100),
        "finished_at": NOW,
        "duration_sec": 100,
    }
    seams.normalize_session(window)
    db = FakeDb(
        execute_responses=[Result(rows=[(11, 1), (12, 2), (13, 2)])],
        scalar_responses=[0],
    )
    results = [
        {"success": True, "schedule_id": 11, "is_correct": True},
        {"success": True, "schedule_id": 12, "is_correct": True},
        {"success": True, "schedule_id": 13, "is_correct": False},
    ]

    await rs._record_review_session(db, USER, {"request_id": "seg-r"}, results)

    sessions = [obj for obj in db.added if type(obj).__name__ == "ReviewSession"]
    assert [session.subject_id for session in sessions] == [1, 2]
    assert [session.question_count for session in sessions] == [1, 2]
    assert [session.duration_sec for session in sessions] == [33, 67]
    assert sum(session.duration_sec for session in sessions) == 100


@pytest.mark.asyncio
async def test_grade_batch_review_submits_with_the_grading_contract(monkeypatch, seams):
    """Per-item grading always submits uncommitted, with the derived answer/rating."""
    seams.loaders().session_recorder()
    seams.revision_views = {
        900: revision(id=900, answer="A"),
        901: revision(id=901, question_id=101, answer="B", question_type="judge"),
    }
    calls = []

    async def submit(db, user_id, **kwargs):
        calls.append(kwargs)
        return {
            "schedule_id": kwargs["schedule_id"],
            "question_id": kwargs["question_id"],
            "question_version_id": kwargs["question_version_id"],
            "occurrence_seq": kwargs["occurrence_seq"],
            "rating": kwargs["rating"],
            "interval_after": 6,
            "ease_factor_after": 2.6,
            "next_review_at": NOW + timedelta(days=6),
            "is_correct": kwargs["rating"] >= 3,
            "mastery_percent": 65,
            "mastered": False,
            "wrong_question_id": None if kwargs["rating"] >= 3 else 55,
            "wrong_review_count": None,
            "wrong_answer": None,
        }

    monkeypatch.setattr(rs, "submit_review", submit)
    db = FakeDb()

    await rs.grade_batch_review(
        db,
        USER,
        [
            batch_item(1, user_answer="A"),
            batch_item(2, question_id=101, schedule_id=12, question_version_id=901),
        ],
    )

    assert [call["question_id"] for call in calls] == [100, 101]
    assert all(call["auto_commit"] is False for call in calls)
    assert calls[0]["rating"] == 4
    assert calls[0]["latest_wrong_answer"] is None
    assert calls[1]["rating"] == 1
    assert calls[1]["latest_wrong_answer"] == "A"


@pytest.mark.asyncio
async def test_grade_batch_review_prewarms_only_wrong_successes(monkeypatch, seams):
    seams.loaders().session_recorder()
    seams.revision_views = {
        900: revision(id=900, answer="A"),
        901: revision(id=901, question_id=101, answer="A"),
    }
    seams.submit(
        {
            100: {
                "schedule_id": 11,
                "question_id": 100,
                "question_version_id": 901,
                "occurrence_seq": 4,
                "rating": 4,
                "interval_after": 6,
                "ease_factor_after": 2.6,
                "next_review_at": NOW + timedelta(days=6),
                "is_correct": True,
                "mastery_percent": 65,
                "mastered": False,
                "wrong_question_id": 55,
                "wrong_review_count": 3,
                "wrong_answer": "B",
            }
        }
    )
    prewarm_calls = []

    from app.services import ai_prewarm_worker

    async def enqueue(wq_id, user_id, *, revision):
        prewarm_calls.append((wq_id, user_id, revision))

    monkeypatch.setattr(ai_prewarm_worker, "enqueue_prewarm", enqueue)
    db = FakeDb()

    payload = await rs.grade_batch_review(db, USER, [batch_item(1)])

    assert payload["correct_count"] == 1
    assert prewarm_calls == []
    assert "wrong_question_id" not in payload["results"][0]


@pytest.mark.asyncio
async def test_review_stats_zeroes_unresolved_subject_id(monkeypatch, seams):
    """A schedule whose subject cannot be resolved reports subject_id 0."""
    seams.now()
    db = FakeDb(
        execute_responses=[
            Result(scalar=1),
            Result(scalar=1),
            Result(scalar=1),
            Result(scalar=0),
            Result(one=(1, 1)),
            Result(rows=[(None, 5, 2)]),
            Result(rows=[]),
        ]
    )

    stats = await rs.get_review_stats(db, USER)

    assert stats["by_subject"] == [
        {
            "subject_id": 0,
            "subject_code": "",
            "subject_name": "",
            "scheduled": 5,
            "reviewed": 0,
            "remaining": 2,
        }
    ]
    assert len(db.statements) == 7


@pytest.mark.asyncio
async def test_set_mastered_state_skips_restore_for_inactive_wrong_question(
    monkeypatch, seams
):
    """Undo never resurrects a review schedule for a removed wrong-book row."""
    seams.now().locks()
    wq = wrong_question(is_active=False)
    db = FakeDb(scalar_responses=[wq, None])

    changed = await rs.set_mastered_state(
        db, user_id=USER, question_id=100, mastered=False
    )

    assert changed is False
    assert not any(type(obj).__name__ == "ReviewSchedule" for obj in db.added)


@pytest.mark.asyncio
async def test_grade_batch_review_payload_field_contract(monkeypatch, seams):
    """Missing/error/success payloads keep every client-visible field."""
    seams.loaders().session_recorder()
    seams.error_meta(
        {"复习题版本已更新，请刷新后重试": ("REVIEW_VERSION_MISMATCH", True, True)}
    )
    seams.revision_views = {
        900: revision(id=900, answer="A"),
        901: revision(id=901, question_id=101, answer="A"),
    }
    seams.submit(
        {
            100: ValueError("复习题版本已更新，请刷新后重试"),
            101: {
                "schedule_id": 12,
                "question_id": 101,
                "question_version_id": 901,
                "occurrence_seq": 4,
                "rating": 4,
                "interval_after": 6,
                "ease_factor_after": 2.6,
                "next_review_at": NOW + timedelta(days=6),
                "is_correct": True,
                "mastery_percent": 80,
                "mastered": True,
                "wrong_question_id": None,
                "wrong_review_count": None,
                "wrong_answer": None,
            },
        }
    )
    db = FakeDb()

    payload = await rs.grade_batch_review(
        db,
        USER,
        [
            batch_item(1),
            batch_item(2, question_id=101, schedule_id=12, question_version_id=901),
            batch_item(3, question_id=102, question_version_id=902),
        ],
    )

    by_question = {item["question_id"]: item for item in payload["results"]}
    missing = by_question[102]
    assert missing["error"] == "复习题版本不存在"
    assert missing["error_code"] == "REVIEW_VERSION_MISSING"
    assert missing["retryable"] is False
    assert missing["refresh_required"] is True
    assert missing["is_correct"] is False
    assert missing["mastery_percent"] == 20
    assert missing["correct_answer"] == ""
    assert missing["rating"] == 0

    error = by_question[100]
    assert error["error"] == "复习题版本已更新，请刷新后重试"
    assert error["error_code"] == "REVIEW_VERSION_MISMATCH"
    assert error["is_correct"] is False
    assert error["success"] is False
    assert error["rating"] == 4
    assert error["correct_answer"] == "A"
    assert error["mastery_percent"] == 20
    assert error["interval_after"] == 0
    assert error["ease_factor_after"] == 0.0

    success = by_question[101]
    assert success["success"] is True
    assert success["error"] is None
    assert success["mastery_percent"] == 80
    assert success["mastered"] is True
    assert success["is_correct"] is True
    assert success["rating"] == 4
    assert success["correct_answer"] == "A"


@pytest.mark.asyncio
async def test_today_review_overview_caps_the_time_estimate(monkeypatch, seams):
    """The entry-page estimate is capped at two hours regardless of backlog size."""
    seams.now()
    pending = [schedule(id=index, question_id=index) for index in range(1, 401)]
    seams.task_state(
        {
            "today_start": TODAY_START,
            "today_end": TODAY_END,
            "task_schedules": list(pending),
            "pending_schedules": list(pending),
            "task_question_ids": {item.question_id for item in pending},
            "completed_question_ids": set(),
            "mastered_question_ids": set(),
        }
    )
    db = FakeDb()

    overview = await rs.get_today_review_overview(db, USER)

    assert overview["today_remaining_count"] == 400
    assert overview["estimated_minutes"] == 120
    assert overview["total_batch_count"] == 40
    assert overview["remaining_batch_count"] == 40
    assert overview["current_batch_no"] == 1


@pytest.mark.asyncio
async def test_today_result_subject_stats_falls_back_to_zero_subject(
    monkeypatch, seams
):
    """A revision whose subject is NULL reports subject_id 0 instead of failing."""
    seams.loaders()
    seams.revision_views = {900: revision(id=900, subject_id=None, subject_ref=None)}
    db = FakeDb()

    stats = await rs._today_result_subject_stats(db, [review_record()])

    assert stats == [
        {
            "subject_id": 0,
            "subject_code": "",
            "subject_name": "",
            "reviewed": 1,
            "correct": 1,
            "wrong": 0,
            "skipped": 0,
        }
    ]


@pytest.mark.asyncio
async def test_submit_review_rating_two_is_still_incorrect(monkeypatch, seams):
    """The pass threshold is exactly rating >= 3; rating 2 must stay a failure."""
    seams.now().locks().loaders().replay(existing=None).sync()
    sched = schedule(interval=3, ease_factor=2.5, repetitions=2)
    db = FakeDb(scalar_responses=[sched, None])

    payload = await rs.submit_review(
        db,
        USER,
        schedule_id=11,
        question_id=100,
        question_version_id=900,
        occurrence_seq=4,
        rating=2,
        request_id="req-2",
        user_answer="B",
    )

    assert payload["is_correct"] is False
    assert payload["mastered"] is False
    record = next(obj for obj in db.added if type(obj).__name__ == "ReviewRecord")
    assert record.is_correct is False
    assert record.user_answer == "B"


@pytest.mark.asyncio
async def test_submit_review_only_reports_wrong_book_fields_for_wrong_answers(
    monkeypatch, seams
):
    """A synced wrong-book row is echoed only when the answer was incorrect."""
    synced = SimpleNamespace(id=55, review_count=3, wrong_answer="B")
    seams.now().locks().loaders().replay(existing=None).sync(result=synced)

    correct = FakeDb(scalar_responses=[schedule(), None])
    payload = await rs.submit_review(
        correct,
        USER,
        schedule_id=11,
        question_id=100,
        question_version_id=900,
        occurrence_seq=4,
        rating=4,
        request_id="req-ok",
        user_answer="A",
    )
    assert payload["wrong_question_id"] is None
    assert payload["wrong_review_count"] is None
    assert payload["wrong_answer"] is None

    wrong = FakeDb(scalar_responses=[schedule(), None])
    payload = await rs.submit_review(
        wrong,
        USER,
        schedule_id=11,
        question_id=100,
        question_version_id=900,
        occurrence_seq=4,
        rating=1,
        request_id="req-bad",
        user_answer="B",
        latest_wrong_answer="B",
    )
    assert payload["wrong_question_id"] == 55
    assert payload["wrong_review_count"] == 3
    assert payload["wrong_answer"] == "B"


@pytest.mark.asyncio
async def test_submit_review_records_the_submitted_answer(monkeypatch, seams):
    """The immutable record must keep the client's answer verbatim."""
    seams.now().locks().loaders().replay(existing=None).sync()
    db = FakeDb(scalar_responses=[schedule(), None])

    await rs.submit_review(
        db,
        USER,
        schedule_id=11,
        question_id=100,
        question_version_id=900,
        occurrence_seq=4,
        rating=4,
        request_id="req-1",
        user_answer="A",
    )

    record = next(obj for obj in db.added if type(obj).__name__ == "ReviewRecord")
    assert record.user_answer == "A"
