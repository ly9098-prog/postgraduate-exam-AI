"""Characterize PostgreSQL repair/diagnostic SQL and original failure semantics."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.core import database
from tests.core.runtime_schema_probe import schema_operations

COLUMNS = {
    "questions": ["question_hash", "sync_uuid", "sync_version"],
    "question_imports": ["question_hash", "duplicate_status", "duplicate_of_question_id", "duplicate_of_import_id"],
    "users": ["is_banned", "deleted_at"],
}


@pytest.fixture
def ports(monkeypatch):
    state = SimpleNamespace(
        events=[], failures={}, constraint=None, columns={k: list(v) for k, v in COLUMNS.items()},
        logger=SimpleNamespace(info=Mock(), warning=Mock(), debug=Mock()),
    )

    def event(name, *args):
        state.events.append((name, *args))
        if name in state.failures:
            raise state.failures[name]

    async def execute(sql, params=None):
        sql = str(sql)
        if "FROM pg_constraint" in sql:
            event("select", sql)
            return SimpleNamespace(scalar_one_or_none=lambda: state.constraint)
        if sql.startswith("ALTER TABLE"):
            event("drop", sql)
        elif sql.startswith("CREATE INDEX"):
            event("create", sql)
        else:
            table = params["tbl"]
            event(table, sql, params)
            return SimpleNamespace(all=lambda: [(name,) for name in state.columns[table]])
        return None

    async def commit():
        event("commit")

    class Context:
        async def __aenter__(self):
            event("enter")
            return SimpleNamespace(execute=execute, commit=commit)

        async def __aexit__(self, error_type, error, traceback):
            event("exit", error_type)
            return False

    def factory():
        event("factory")
        return Context()

    dialect = SimpleNamespace(name="postgresql")
    monkeypatch.setattr(database, "engine", SimpleNamespace(
        dialect=dialect, sync_engine=SimpleNamespace(dialect=dialect),
        begin=Mock(side_effect=AssertionError("PostgreSQL path must use original session factory")),
    ))
    state.factory = factory
    state.operations = schema_operations(monkeypatch, state.logger, factory)
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize("constraint", [None, "", 0, "uq_export_key", 'quoted"constraint'])
async def test_postgres_repair_sql_quote_escaping_and_commit_only_after_both_statements(ports, constraint):
    ports.constraint = constraint
    await ports.operations.repair()
    names = [event[0] for event in ports.events]
    assert names == ["factory", "enter", "select", *(["drop", "create", "commit"] if constraint else []), "exit"]
    assert "conrelid = 'export_tasks'::regclass" in ports.events[2][1]
    assert "conname LIKE '%idempotency_key%'" in ports.events[2][1]
    if constraint:
        assert ports.events[3][1] == 'ALTER TABLE export_tasks DROP CONSTRAINT "' + str(constraint).replace('"', '""') + '"'
        assert ports.events[4][1] == "CREATE INDEX IF NOT EXISTS ix_export_tasks_idempotency_key ON export_tasks (idempotency_key)"
    assert ports.logger.info.call_count == int(bool(constraint))
    ports.logger.warning.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", ["factory", "enter", "select", "drop", "create", "commit", "exit"])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_postgres_repair_errors_exit_original_context_and_cancellation_propagates(ports, failed, error_type):
    error = error_type("synthetic schema repair failure")
    ports.constraint = "uq_export_key"
    ports.failures[failed] = error
    if error_type is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError) as caught:
            await ports.operations.repair()
        assert caught.value is error
        ports.logger.warning.assert_not_called()
    else:
        await ports.operations.repair()
        ports.logger.warning.assert_called_once()
        assert ports.logger.warning.call_args.args[1:] == ("RuntimeError", error)
    if failed not in {"factory", "enter"}:
        assert ports.events[-1][0] == "exit"
    if failed in {"select", "drop", "create"}:
        assert "commit" not in [event[0] for event in ports.events]


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", [False, True])
async def test_diagnostic_selects_original_tables_columns_and_stable_missing_order_without_commit(ports, missing):
    if missing:
        ports.columns = {"questions": ["sync_uuid"], "question_imports": ["question_hash"], "users": ["deleted_at"]}
    await ports.operations.diagnose()
    assert [event[0] for event in ports.events] == ["factory", "enter", "questions", "question_imports", "users", "exit"]
    for event in ports.events[2:-1]:
        assert event[1] == "SELECT column_name FROM information_schema.columns WHERE table_name=:tbl AND column_name=ANY(:cols)"
        assert event[2] == {"tbl": event[0], "cols": COLUMNS[event[0]]}
    if missing:
        ports.logger.warning.assert_called_once_with(
            "Schema divergence (runtime DDL not in Alembic): %s",
            "questions.question_hash, questions.sync_version, question_imports.duplicate_status, question_imports.duplicate_of_question_id, question_imports.duplicate_of_import_id, users.is_banned",
        )
    else:
        ports.logger.debug.assert_called_once_with("Schema divergence check: all runtime-DDL columns present")


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", ["factory", "enter", "questions", "question_imports", "users", "exit"])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_diagnostic_query_errors_are_best_effort_but_cancellation_stops_scan(ports, failed, error_type):
    error = error_type("synthetic schema diagnostic failure")
    ports.failures[failed] = error
    if error_type is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError) as caught:
            await ports.operations.diagnose()
        assert caught.value is error
        ports.logger.debug.assert_not_called()
    else:
        await ports.operations.diagnose()
        expected = "Schema divergence check: all runtime-DDL columns present" if failed in COLUMNS else "Schema divergence check skipped (not PostgreSQL or transient)"
        ports.logger.debug.assert_called_once_with(expected)
    ports.logger.warning.assert_not_called()
    assert "commit" not in [event[0] for event in ports.events]


@pytest.mark.asyncio
@pytest.mark.parametrize("dialect", ["mysql", "synthetic"])
async def test_unsupported_dialects_do_not_open_sessions_or_log_success(ports, dialect):
    database.engine.dialect.name = dialect
    await ports.operations.repair()
    await ports.operations.diagnose()
    assert ports.events == []
    ports.logger.info.assert_not_called()
    ports.logger.warning.assert_not_called()
    ports.logger.debug.assert_not_called()
