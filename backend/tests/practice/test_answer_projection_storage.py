"""Pin the explicit projection SQL contract and cached schema verification."""

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql, sqlite

from app.services.practice import answer_projection_service as service


@pytest.mark.asyncio
@pytest.mark.parametrize("dialect", ["postgresql", "sqlite", None])
async def test_source_lock_selects_only_event_columns_and_locks_only_postgres(dialect):
    row = {
        "id": "1",
        "user_id": "2",
        "question_id": "3",
        "question_version_id": "4",
        "subject_id": "5",
        "user_answer": None,
        "is_correct": 0,
        "used_time": 0,
        "answered_at": datetime(2026, 10, 26),
        "mode": None,
        "projection_state": "pending",
    }
    db = SimpleNamespace(
        get_bind=lambda: (
            None
            if dialect is None
            else SimpleNamespace(dialect=SimpleNamespace(name=dialect))
        ),
        execute=AsyncMock(
            return_value=SimpleNamespace(
                mappings=lambda: SimpleNamespace(one_or_none=lambda: row),
            )
        ),
    )
    record = await service._lock_projection_source(db, 1)
    assert record == service._ProjectionSource(
        id=1,
        user_id=2,
        question_id=3,
        question_version_id=4,
        subject_id=5,
        user_answer="",
        is_correct=False,
        used_time=0,
        answered_at=row["answered_at"],
        mode=None,
        projection_state="pending",
    )
    stmt = db.execute.await_args.args[0]
    assert [column.key for column in stmt.selected_columns] == list(row)
    assert stmt.compile().params["id_1"] == 1
    compiler = postgresql.dialect() if dialect == "postgresql" else sqlite.dialect()
    sql = str(stmt.compile(dialect=compiler))
    assert ("FOR UPDATE OF practice_records" in sql) == (dialect == "postgresql")


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 1, 2])
async def test_finish_updates_only_pending_and_requires_exact_row_ownership(count):
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(rowcount=count))
    )
    call = service._finish_projection(
        db, practice_record_id=7, target_state="revision_only"
    )
    if count == 1:
        await call
    else:
        with pytest.raises(
            RuntimeError, match=f"record_id=7 target=revision_only rowcount={count}"
        ):
            await call
    stmt = db.execute.await_args.args[0]
    assert stmt.compile().params == {
        "projection_state": "revision_only",
        "id_1": 7,
        "projection_state_1": "pending",
    }


@pytest.fixture
def schema(monkeypatch):
    state = SimpleNamespace(
        columns=set(service.REQUIRED_PROJECTION_COLUMNS),
        tables=["practice_records"],
        calls=[],
        inspected=object(),
    )

    def inspect(connection):
        assert connection is state.inspected
        return SimpleNamespace(
            get_table_names=lambda: state.tables,
            get_columns=lambda table: [{"name": name} for name in state.columns],
        )

    async def run_sync(callback):
        state.calls.append("inspect")
        return callback(state.inspected)

    async def connection():
        state.calls.append("connection")
        return SimpleNamespace(run_sync=run_sync)

    state.db = SimpleNamespace(connection=connection)
    monkeypatch.setattr(service, "inspect", inspect)
    monkeypatch.setattr(service, "_schema_contract_verified", False)
    monkeypatch.setattr(service, "_schema_contract_lock", asyncio.Lock())
    return state


@pytest.mark.asyncio
async def test_schema_verifies_once_under_concurrent_calls(schema):
    await asyncio.gather(
        *(service._verify_projection_schema_contract(schema.db) for _ in range(3))
    )
    assert schema.calls == ["connection", "inspect"]
    assert service._schema_contract_verified is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind", ["missing-table", "missing-columns", "retired-columns", "both"]
)
async def test_schema_failure_does_not_cache_a_receipt_and_can_retry(schema, kind):
    if kind == "missing-table":
        schema.tables = []
        message = "practice_records table does not exist"
    else:
        details = []
        if kind in {"missing-columns", "both"}:
            schema.columns -= {"question_id", "user_id"}
            details.append("missing=question_id,user_id")
        if kind in {"retired-columns", "both"}:
            schema.columns |= {"answers", "question_ids"}
            details.append("retired_present=answers,question_ids")
        message = (
            "practice_records per-answer schema invariant failed ("
            + "; ".join(details)
            + "). Apply Alembic upgrade to head before running answer_projection workers."
        )
    with pytest.raises(RuntimeError) as caught:
        await service._verify_projection_schema_contract(schema.db)
    assert str(caught.value) == message
    assert service._schema_contract_verified is False
    schema.tables = ["practice_records"]
    schema.columns = set(service.REQUIRED_PROJECTION_COLUMNS)
    await service._verify_projection_schema_contract(schema.db)
    assert schema.calls == ["connection", "inspect"] * 2


@pytest.mark.asyncio
async def test_retired_orm_columns_fail_before_connection(schema, monkeypatch):
    monkeypatch.setattr(
        service,
        "PracticeRecord",
        SimpleNamespace(
            __table__=SimpleNamespace(columns={"answers": None, "question_ids": None}),
        ),
    )
    with pytest.raises(
        RuntimeError, match="ORM maps retired batch columns: answers, question_ids"
    ):
        await service._verify_projection_schema_contract(schema.db)
    assert schema.calls == []


@pytest.mark.asyncio
async def test_schema_cancellation_propagates_releases_lock_and_allows_retry(schema):
    async def cancelled_connection():
        raise asyncio.CancelledError("cancel")

    original = schema.db.connection
    schema.db.connection = cancelled_connection
    with pytest.raises(asyncio.CancelledError):
        await service._verify_projection_schema_contract(schema.db)
    assert service._schema_contract_verified is False
    assert not service._schema_contract_lock.locked()
    schema.db.connection = original
    await service._verify_projection_schema_contract(schema.db)
    assert service._schema_contract_verified is True
