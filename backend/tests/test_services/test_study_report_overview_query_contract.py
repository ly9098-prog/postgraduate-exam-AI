"""Query-shape contracts for study_report_service.get_overview."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.dialects import postgresql, sqlite

from app.services import study_report_service

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
TODAY_START = datetime(2026, 10, 27, 16, 0, tzinfo=UTC)
RECENT_START = TODAY_START - timedelta(days=7)
OVERDUE_THRESHOLD = NOW - timedelta(days=1)


class CaptureDb:
    def __init__(self, results):
        self.statements = []
        self._results = list(results)
        self.connection = AsyncMock(
            return_value=SimpleNamespace(
                sync_connection=SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
            )
        )

    async def execute(self, statement):
        self.statements.append(statement)
        return self._results.pop(0)


class Row:
    def __init__(self, **values):
        self.__dict__.update(values)


def result(*, one=None, scalar=None):
    mock = MagicMock()
    if one is not None:
        mock.one.return_value = one
    if scalar is not None:
        mock.scalar_one.return_value = scalar
        mock.scalar_one_or_none.return_value = scalar
    return mock


def missing():
    mock = MagicMock()
    mock.scalar_one_or_none.return_value = None
    return mock


PRACTICE_ROW = Row(
    today_count=1,
    today_correct=1,
    recent_count=2,
    recent_correct=2,
    total_count=3,
    total_correct=3,
)


def install_fixed_clock(monkeypatch):
    monkeypatch.setattr(study_report_service, "utcnow", lambda: NOW)
    monkeypatch.setattr(study_report_service, "_today_utc", lambda: TODAY_START)


def compiled(statement, dialect):
    return statement.compile(dialect=dialect)


@pytest.mark.asyncio
@pytest.mark.parametrize("dialect", [sqlite.dialect(), postgresql.dialect()])
async def test_overview_query_order_and_filters(monkeypatch, dialect):
    install_fixed_clock(monkeypatch)
    db = CaptureDb(
        [
            result(one=PRACTICE_ROW),
            result(scalar=0),
            result(scalar=0),
            result(scalar=0),
            result(scalar=0),
            result(scalar=0),
            result(scalar=0),
            result(scalar=0),
        ]
    )

    await study_report_service.get_overview(db, user_id=9, days=7)

    assert len(db.statements) == 8
    practice, due, overdue, wrong, repeated, weak, unstable, mastered = (
        compiled(statement, dialect) for statement in db.statements
    )

    assert "practice_records.user_id" in str(practice)
    assert "practice_records.subject_id" not in str(practice)
    for expected in (TODAY_START, RECENT_START):
        assert expected in practice.params.values()

    assert "user_question_state.next_review_at <=" in str(due)
    assert NOW in due.params.values()
    assert "user_question_state.next_review_at <" in str(overdue)
    assert OVERDUE_THRESHOLD in overdue.params.values()

    assert "user_question_state.wrong_count >" in str(wrong)
    assert "user_question_state.wrong_count >=" in str(repeated)
    assert 0 in wrong.params.values()
    assert 3 in repeated.params.values()

    assert "user_knowledge_states.mastery_score <" in str(weak)
    assert 40 in weak.params.values()
    assert 0.3 in weak.params.values()
    assert "user_knowledge_states.mastery_score >=" in str(unstable)
    assert 85 in unstable.params.values()
    assert "user_knowledge_states.mastery_score >=" in str(mastered)
    assert 0.5 in mastered.params.values()


@pytest.mark.asyncio
async def test_overview_subject_filter_joins_and_existence_probe(monkeypatch):
    install_fixed_clock(monkeypatch)
    db = CaptureDb(
        [
            result(one=PRACTICE_ROW),
            result(scalar=0),
            result(scalar=0),
            result(scalar=0),
            result(scalar=0),
            result(scalar=1),
            result(scalar=0),
            result(scalar=0),
            result(scalar=0),
        ]
    )

    await study_report_service.get_overview(db, user_id=9, subject_id=3)

    assert len(db.statements) == 9
    dialect = sqlite.dialect()
    practice = compiled(db.statements[0], dialect)
    due = compiled(db.statements[1], dialect)
    overdue = compiled(db.statements[2], dialect)
    wrong = compiled(db.statements[3], dialect)
    repeated = compiled(db.statements[4], dialect)
    existence = compiled(db.statements[5], dialect)
    weak = compiled(db.statements[6], dialect)

    assert "practice_records.subject_id" in str(practice)
    assert "JOIN questions" in str(due)
    assert "JOIN questions" in str(overdue)
    assert "JOIN questions" in str(wrong)
    assert "JOIN questions" in str(repeated)
    assert "subjects.id" in str(existence)
    assert 3 in existence.params.values()
    assert "user_knowledge_states.subject_id" in str(weak)
    assert 3 in weak.params.values()


@pytest.mark.asyncio
async def test_overview_missing_subject_skips_knowledge_queries(monkeypatch):
    install_fixed_clock(monkeypatch)
    db = CaptureDb(
        [
            result(one=PRACTICE_ROW),
            result(scalar=0),
            result(scalar=0),
            result(scalar=7),
            result(scalar=2),
            missing(),
        ]
    )

    payload = await study_report_service.get_overview(db, user_id=9, subject_id=404)

    assert len(db.statements) == 6
    assert payload["wrong_question_count"] == 7
    assert payload["repeated_wrong_question_count"] == 2
    assert payload["weak_knowledge_count"] == 0
    assert payload["unstable_knowledge_count"] == 0
    assert payload["mastered_knowledge_count"] == 0


# ── real SQLite differential ────────────────────────────────────────


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def monkeypatch_module():
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest_asyncio.fixture(scope="module")
async def sqlite_session(monkeypatch_module, tmp_path_factory):
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    import app.models  # noqa: F401 - registers all models on Base
    from app.core.database import Base

    db_path = tmp_path_factory.mktemp("study_overview") / "overview.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield SimpleNamespace(engine=engine, async_session=session_factory, Base=Base)
    await engine.dispose()


async def _seed(db, *, now, today_start):
    from app.models.admin import Subject
    from app.models.knowledge_point import KnowledgePoint
    from app.models.practice_record import PracticeRecord
    from app.models.question import Question
    from app.models.user_knowledge_state import UserKnowledgeState
    from app.models.user_question_state import UserQuestionState

    db.add_all(
        [
            Subject(
                id=1,
                name="数据结构",
                code="data_structure",
                path="/data_structure",
            ),
            Subject(
                id=2,
                name="计算机网络",
                code="computer_network",
                path="/computer_network",
            ),
        ]
    )
    await db.flush()
    db.add_all(
        [
            KnowledgePoint(
                id=1,
                subject_id=1,
                name="栈",
                normalized_name="栈",
                is_active=True,
            ),
            KnowledgePoint(
                id=2,
                subject_id=1,
                name="队列",
                normalized_name="队列",
                is_active=True,
            ),
            KnowledgePoint(
                id=3,
                subject_id=1,
                name="树",
                normalized_name="树",
                is_active=True,
            ),
            KnowledgePoint(
                id=4,
                subject_id=2,
                name="TCP",
                normalized_name="tcp",
                is_active=True,
            ),
            KnowledgePoint(
                id=5,
                subject_id=2,
                name="IP",
                normalized_name="ip",
                is_active=True,
            ),
        ]
    )
    db.add_all(
        [
            Question(
                id=1,
                subject_id=1,
                question_type="choice",
                content={"stem": "栈的特点"},
                answer="A",
            ),
            Question(
                id=2,
                subject_id=1,
                question_type="choice",
                content={"stem": "队列的特点"},
                answer="B",
            ),
            Question(
                id=3,
                subject_id=2,
                question_type="choice",
                content={"stem": "TCP 特点"},
                answer="C",
            ),
            Question(
                id=4,
                subject_id=1,
                question_type="choice",
                content={"stem": "树的特点"},
                answer="D",
            ),
            Question(
                id=5,
                subject_id=2,
                question_type="choice",
                content={"stem": "IP 特点"},
                answer="A",
            ),
        ]
    )
    await db.flush()

    def record(question_id, subject_id, correct, answered_at):
        return PracticeRecord(
            user_id=9,
            question_id=question_id,
            question_version_id=question_id,
            subject_id=subject_id,
            question_type="choice",
            user_answer="A",
            is_correct=correct,
            answered_at=answered_at,
        )

    db.add_all(
        [
            record(1, 1, True, now - timedelta(hours=1)),
            record(1, 1, True, now - timedelta(hours=2)),
            record(2, 1, False, now - timedelta(hours=3)),
            record(1, 1, True, today_start - timedelta(days=3, hours=1)),
            record(2, 1, False, today_start - timedelta(days=3, hours=2)),
            record(3, 2, True, today_start - timedelta(days=10)),
        ]
    )

    def state(question_id, next_review_at, wrong_count):
        return UserQuestionState(
            user_id=9,
            question_id=question_id,
            next_review_at=next_review_at,
            wrong_count=wrong_count,
        )

    db.add_all(
        [
            state(1, now - timedelta(days=2), 3),
            state(2, now - timedelta(hours=1), 1),
            state(4, None, 2),
            state(5, now - timedelta(days=3), 0),
        ]
    )

    def knowledge(kp_id, subject_id, score, confidence):
        return UserKnowledgeState(
            user_id=9,
            subject_id=subject_id,
            knowledge_point_id=kp_id,
            mastery_score=score,
            confidence=confidence,
        )

    db.add_all(
        [
            knowledge(1, 1, 30.0, 0.5),
            knowledge(2, 1, 60.0, 0.4),
            knowledge(3, 1, 90.0, 0.9),
            knowledge(4, 2, 20.0, 0.1),
            knowledge(5, 2, 90.0, 0.9),
        ]
    )
    await db.commit()


@pytest_asyncio.fixture
async def seeded_session(sqlite_session, monkeypatch):
    # Keep the SQLite fixture deterministic across China/UTC midnight; the
    # production code under test must use the same fixed clock as the seed.
    monkeypatch.setattr(study_report_service, "utcnow", lambda: NOW)
    monkeypatch.setattr(study_report_service, "_today_utc", lambda: TODAY_START)
    async with sqlite_session.async_session() as db:
        for table in reversed(list(sqlite_session.Base.metadata.tables.values())):
            await db.execute(table.delete())
        await db.commit()
        await _seed(db, now=NOW, today_start=TODAY_START)
    return sqlite_session


@pytest.mark.asyncio
async def test_overview_sqlite_counts_without_subject(seeded_session):
    async with seeded_session.async_session() as db:
        payload = await study_report_service.get_overview(db, user_id=9, days=7)

    assert payload["today_answer_count"] == 3
    assert payload["today_correct_count"] == 2
    assert payload["recent_answer_count"] == 5
    assert payload["recent_correct_count"] == 3
    assert payload["total_answer_count"] == 6
    assert payload["total_correct_count"] == 4
    assert payload["due_review_count"] == 3
    assert payload["overdue_review_count"] == 2
    assert payload["wrong_question_count"] == 3
    assert payload["repeated_wrong_question_count"] == 1
    assert payload["weak_knowledge_count"] == 1
    assert payload["unstable_knowledge_count"] == 1
    assert payload["mastered_knowledge_count"] == 2


@pytest.mark.asyncio
async def test_overview_sqlite_counts_with_subject_filter(seeded_session):
    async with seeded_session.async_session() as db:
        payload = await study_report_service.get_overview(
            db, user_id=9, subject_id=1, days=7
        )

    assert payload["today_answer_count"] == 3
    assert payload["recent_answer_count"] == 5
    assert payload["total_answer_count"] == 5
    assert payload["total_correct_count"] == 3
    assert payload["due_review_count"] == 2
    assert payload["overdue_review_count"] == 1
    assert payload["wrong_question_count"] == 3
    assert payload["repeated_wrong_question_count"] == 1
    assert payload["weak_knowledge_count"] == 1
    assert payload["unstable_knowledge_count"] == 1
    assert payload["mastered_knowledge_count"] == 1


@pytest.mark.asyncio
async def test_overview_sqlite_missing_subject_returns_zero_knowledge(
    seeded_session,
):
    async with seeded_session.async_session() as db:
        payload = await study_report_service.get_overview(
            db, user_id=9, subject_id=999, days=7
        )

    assert payload["weak_knowledge_count"] == 0
    assert payload["unstable_knowledge_count"] == 0
    assert payload["mastered_knowledge_count"] == 0
    assert payload["wrong_question_count"] == 0
