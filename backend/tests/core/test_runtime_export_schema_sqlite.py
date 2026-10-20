"""Exercise original export schema repair on temporary SQLite tables and data."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from alembic.operations import BatchOperations
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core import database
from tests.core.runtime_schema_probe import schema_operations

CASES = [
    ("absent", None, [], False),
    ("no-index", "", [], False),
    ("plain", "", ["CREATE INDEX ix_existing ON export_tasks (idempotency_key)"], False),
    ("unnamed", ", UNIQUE (idempotency_key)", [], True),
    ("named", ", CONSTRAINT uq_export_key UNIQUE (idempotency_key)", [], True),
    ("unique-index", "", ["CREATE UNIQUE INDEX uq_export_key ON export_tasks (idempotency_key)"], True),
    ("both", ", UNIQUE (idempotency_key)", ["CREATE UNIQUE INDEX uq_export_key ON export_tasks (idempotency_key)"], True),
    ("existing-plain", ", UNIQUE (idempotency_key)", ["CREATE INDEX ix_existing ON export_tasks (idempotency_key)"], True),
    ("composite", ", CONSTRAINT uq_export_composite UNIQUE (idempotency_key, payload)", ["CREATE UNIQUE INDEX uq_composite ON export_tasks (idempotency_key, payload)"], False),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("name,unique,indexes,repaired", CASES, ids=[case[0] for case in CASES])
async def test_sqlite_schema_data_and_idempotent_second_run(monkeypatch, tmp_path, name, unique, indexes, repaired):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / (name + '.db')}")
    monkeypatch.setattr(database, "engine", engine)
    logger = SimpleNamespace(info=Mock(), warning=Mock(), debug=Mock())
    factory = Mock(side_effect=AssertionError("SQLite repair must use engine.begin/run_sync"))
    operations = schema_operations(monkeypatch, logger, factory)
    try:
        if unique is not None:
            async with engine.begin() as connection:
                await connection.execute(text("CREATE TABLE export_tasks (id INTEGER PRIMARY KEY, idempotency_key TEXT, payload TEXT" + unique + ")"))
                for statement in indexes:
                    await connection.execute(text(statement))
                await connection.execute(text("INSERT INTO export_tasks VALUES (1, 'synthetic-key-a', 'payload-a'), (2, 'synthetic-key-b', 'payload-b')"))
        await operations.repair()
        await operations.repair()
        logger.warning.assert_not_called()
        assert logger.info.call_count == int(repaired)
        factory.assert_not_called()
        if unique is None:
            async with engine.connect() as connection:
                assert await connection.run_sync(lambda conn: "export_tasks" not in inspect(conn).get_table_names())
            return
        async with engine.begin() as connection:
            rows = (await connection.execute(text("SELECT id, idempotency_key, payload FROM export_tasks ORDER BY id"))).all()
            assert [tuple(row) for row in rows] == [(1, "synthetic-key-a", "payload-a"), (2, "synthetic-key-b", "payload-b")]
            constraints = await connection.run_sync(lambda conn: inspect(conn).get_unique_constraints("export_tasks"))
            actual_indexes = await connection.run_sync(lambda conn: inspect(conn).get_indexes("export_tasks"))
            if repaired:
                assert not [c for c in constraints if c["column_names"] == ["idempotency_key"]]
                assert not [ix for ix in actual_indexes if ix["column_names"] == ["idempotency_key"] and ix["unique"]]
                assert any(ix["column_names"] == ["idempotency_key"] and not ix["unique"] for ix in actual_indexes)
                await connection.execute(text("INSERT INTO export_tasks VALUES (3, 'synthetic-key-a', 'payload-c')"))
            elif name == "no-index":
                assert not actual_indexes
            elif name == "composite":
                assert constraints[0]["column_names"] == ["idempotency_key", "payload"]
                assert actual_indexes[0]["unique"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_sqlite_batch_planning_failure_preserves_data_and_allows_retry(
    monkeypatch, tmp_path, error_type,
):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'batch-failure.db'}")
    monkeypatch.setattr(database, "engine", engine)
    logger = SimpleNamespace(info=Mock(), warning=Mock(), debug=Mock())
    operations = schema_operations(monkeypatch, logger, Mock())
    error = error_type("synthetic batch planning failure")

    def fail_create_index(*args, **kwargs):
        raise error

    try:
        async with engine.begin() as connection:
            await connection.execute(text(
                "CREATE TABLE export_tasks (id INTEGER PRIMARY KEY, idempotency_key TEXT, "
                "payload TEXT, CONSTRAINT uq_export_key UNIQUE (idempotency_key))",
            ))
            await connection.execute(text(
                "INSERT INTO export_tasks VALUES (1, 'synthetic-key', 'payload')",
            ))
        with monkeypatch.context() as failure_patch:
            failure_patch.setattr(BatchOperations, "create_index", fail_create_index)
            if error_type is asyncio.CancelledError:
                with pytest.raises(asyncio.CancelledError) as caught:
                    await operations.repair()
                assert caught.value is error
            else:
                await operations.repair()
        async with engine.connect() as connection:
            rows = (await connection.execute(text("SELECT * FROM export_tasks"))).all()
            assert [tuple(row) for row in rows] == [(1, "synthetic-key", "payload")]
            constraints = await connection.run_sync(
                lambda conn: inspect(conn).get_unique_constraints("export_tasks"),
            )
            assert constraints[0]["column_names"] == ["idempotency_key"]
        assert logger.warning.call_count == int(error_type is RuntimeError)
        await operations.repair()
        logger.info.assert_called_once()
        async with engine.begin() as connection:
            await connection.execute(text(
                "INSERT INTO export_tasks VALUES (2, 'synthetic-key', 'payload-after-retry')",
            ))
    finally:
        await engine.dispose()
