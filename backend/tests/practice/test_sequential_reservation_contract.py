"""Pin reservation SQL ordering, conflict recovery and transaction ownership."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy.dialects import postgresql, sqlite

import app.models  # noqa: F401 - register relationships before compiling ORM statements
from app.services.practice import sequential_service as service

NOW = datetime(2026, 10, 26, 12)


class ScriptedDB:
    def __init__(self, rows, scalars=(), dialect="sqlite"):
        self.rows = iter(rows)
        self.scalar_values = iter(scalars)
        self.dialect = dialect
        self.events = []

    async def execute(self, statement):
        self.events.append(("execute", statement))
        values = next(self.rows)
        if isinstance(values, BaseException):
            raise values
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: values))

    async def scalar(self, statement):
        self.events.append(("scalar", statement))
        value = next(self.scalar_values)
        if isinstance(value, BaseException):
            raise value
        return value

    def get_bind(self):
        self.events.append(("bind", self.dialect))
        return SimpleNamespace(dialect=SimpleNamespace(name=self.dialect))


def compiled(statement, dialect="sqlite"):
    compiler = postgresql.dialect() if dialect == "postgresql" else sqlite.dialect()
    result = statement.compile(dialect=compiler)
    return str(result), result.params


async def reserve(db, count=2):
    return await service._reserve_sequential_questions(
        db,
        user_id=11,
        subject_id=7,
        conditions=[service.Question.is_active],
        answered_ids=service._answered_ids_query(
            user_id=11, subject_id=7, reset_at=None
        ),
        count=count,
        scope_key="scope",
        start_request_id="request",
        now=NOW,
    )


def statements(db):
    return [value for event, value in db.events if event != "bind"]


@pytest.mark.asyncio
async def test_existing_request_is_read_after_expiry_cleanup_without_binding():
    db = ScriptedDB([[], ["3", "8"]])
    assert await reserve(db, count=1) == [3, 8]
    assert [event for event, _ in db.events] == ["execute", "execute"]
    delete_sql, delete_params = compiled(statements(db)[0])
    read_sql, read_params = compiled(statements(db)[1])
    assert delete_sql.startswith("DELETE FROM sequential_reservations")
    assert "expires_at <=" in delete_sql and delete_params["expires_at_1"] == NOW
    assert "start_request_id =" not in delete_sql
    assert "expires_at >" in read_sql and read_params["expires_at_1"] == NOW
    assert "start_request_id =" in read_sql
    assert read_sql.endswith("ORDER BY sequential_reservations.question_id ASC")
    for params in (delete_params, read_params):
        assert params["user_id_1"] == 11
        assert params["subject_id_1"] == 7
        assert params["scope_key_1"] == "scope"


@pytest.mark.asyncio
@pytest.mark.parametrize("dialect", ["postgresql", "sqlite", "unknown"])
async def test_atomic_insert_uses_live_factory_order_limit_active_scope_and_ttl(
    monkeypatch, dialect
):
    db = ScriptedDB([[], [], ["8", "3"]], dialect=dialect)
    pg = Mock(wraps=service.pg_insert)
    sq = Mock(wraps=service.sqlite_insert)
    monkeypatch.setattr(service, "pg_insert", pg)
    monkeypatch.setattr(service, "sqlite_insert", sq)
    monkeypatch.setattr(service, "SEQUENTIAL_RESERVATION_TTL_SEC", 17)
    assert await reserve(db) == [3, 8]
    assert [event for event, _ in db.events] == [
        "execute",
        "execute",
        "bind",
        "execute",
    ]
    assert pg.call_count == int(dialect == "postgresql")
    assert sq.call_count == int(dialect != "postgresql")
    statement = statements(db)[2]
    sql, params = compiled(statement, dialect)
    assert "INSERT INTO sequential_reservations" in sql
    assert "questions.id NOT IN (SELECT DISTINCT practice_records.question_id" in sql
    assert "NOT (EXISTS" in sql and "expires_at >" in sql
    assert "sequential_reservations.question_id = questions.id" in sql
    assert "ORDER BY questions.id ASC" in sql and "LIMIT" in sql
    assert list(statement.select.selected_columns.keys()) == [
        "user_id",
        "subject_id",
        "question_id",
        "scope_key",
        "start_request_id",
        "created_at",
        "expires_at",
    ]
    assert statement.select._limit_clause.value == 2
    assert NOW in params.values()
    assert NOW + timedelta(seconds=17) in params.values()
    assert "RETURNING" in sql
    if dialect == "postgresql":
        assert (
            "ON CONFLICT ON CONSTRAINT uq_sequential_reservation_question DO NOTHING"
            in sql
        )
    else:
        assert (
            "ON CONFLICT (user_id, subject_id, scope_key, question_id) DO NOTHING"
            in sql
        )


@pytest.mark.asyncio
async def test_partial_claim_retries_remaining_pool_without_resorting_prior_batches():
    db = ScriptedDB([[], [], [8, 3], [], [], [5]], scalars=[9])
    assert await reserve(db, count=3) == [3, 8, 5]
    assert [event for event, _ in db.events] == [
        "execute",
        "execute",
        "bind",
        "execute",
        "execute",
        "execute",
        "scalar",
        "execute",
    ]
    inserts = [stmt for stmt in statements(db) if getattr(stmt, "is_insert", False)]
    assert [stmt.select._limit_clause.value for stmt in inserts] == [3, 1, 1]
    existence = next(stmt for event, stmt in db.events if event == "scalar")
    assert existence._limit_clause.value == 1
    assert not tuple(existence._order_by_clauses)
    assert (
        compiled(inserts[1].select)[0].split("ORDER BY")[0]
        == (compiled(inserts[2].select)[0].split("ORDER BY")[0])
    )


@pytest.mark.asyncio
async def test_conflict_same_request_reread_wins_over_partially_selected_batch():
    db = ScriptedDB([[], [], [4], [], ["2", "9"]])
    assert await reserve(db, count=3) == [2, 9]
    assert [event for event, _ in db.events] == [
        "execute",
        "execute",
        "bind",
        "execute",
        "execute",
        "execute",
    ]
    assert compiled(statements(db)[1]) == compiled(statements(db)[-1])


@pytest.mark.asyncio
async def test_no_insert_rechecks_request_then_stops_only_when_pool_is_empty():
    db = ScriptedDB([[], [], [], []], scalars=[None])
    assert await reserve(db) == []
    assert [event for event, _ in db.events] == [
        "execute",
        "execute",
        "bind",
        "execute",
        "execute",
        "scalar",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, -1])
async def test_nonpositive_count_still_cleans_reads_and_binds_but_does_not_insert(
    count,
):
    db = ScriptedDB([[], []])
    assert await reserve(db, count=count) == []
    assert [event for event, _ in db.events] == ["execute", "execute", "bind"]


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", [0, 1, 2, 3, "candidate"])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_failures_and_cancellation_propagate_without_transaction_actions(
    stage, error_type
):
    error = error_type("injected")
    rows = [[], [], [], []]
    if stage != "candidate":
        rows[stage] = error
    db = ScriptedDB(rows, scalars=[error])
    with pytest.raises(error_type) as caught:
        await reserve(db)
    assert caught.value is error
    expected_calls = 4 if stage == "candidate" else stage + 1
    assert sum(event == "execute" for event, _ in db.events) == expected_calls


def test_scope_key_normalizes_without_mutating_input_and_reset_filter_is_strict():
    points = [" b ", "a", "", "a"]
    assert service._sequential_scope_key(points) == service._sequential_scope_key(
        ["a", "b"]
    )
    assert points == [" b ", "a", "", "a"]
    assert service._sequential_scope_key(None) == service._sequential_scope_key([])
    query = service._answered_ids_query(user_id=11, subject_id=7, reset_at=NOW)
    sql, params = compiled(query)
    assert "SELECT DISTINCT practice_records.question_id" in sql
    assert "practice_records.answered_at >" in sql
    assert params["answered_at_1"] == NOW
    assert params["mode_1"] == "sequential"


@pytest.mark.asyncio
async def test_sql_and_insert_factory_patches_are_resolved_after_database_awaits(
    monkeypatch,
):
    db = ScriptedDB([[], [], [], [7]])
    original_execute = db.execute
    original_select = service.select
    first_select = Mock(wraps=original_select)
    second_select = Mock(wraps=original_select)
    insert = Mock(wraps=service.sqlite_insert)
    calls = 0

    async def execute(statement):
        nonlocal calls
        result = await original_execute(statement)
        calls += 1
        if calls == 1:
            monkeypatch.setattr(service, "select", first_select)
        elif calls == 2:
            monkeypatch.setattr(service, "sqlite_insert", insert)
        elif calls == 3:
            monkeypatch.setattr(service, "select", second_select)
        return result

    db.execute = execute
    assert await reserve(db) == [7]
    assert first_select.call_count == 3
    assert second_select.call_count == 1
    insert.assert_called_once_with(service.SequentialReservation)
