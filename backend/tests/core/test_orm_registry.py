"""Canonical ORM metadata and real local initialization must survive Base relocation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

import app.models  # noqa: F401
from app.core import database
from app.core.deployment_profile import DeploymentProfile
from app.core.orm_base import Base
from app.models.user import User


def test_all_mapped_classes_share_one_registry_and_metadata():
    assert database.Base is Base
    assert {"users", "questions", "subjects", "review_schedules", "pomodoro_sessions"} <= (
        set(database.Base.metadata.tables)
    )
    for mapper in database.Base.registry.mappers:
        assert issubclass(mapper.class_, database.Base)
        assert mapper.local_table.metadata is database.Base.metadata


@pytest.mark.asyncio
async def test_local_initialization_twice_preserves_tables_and_user_persistence(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(
        database, "detect_deployment_profile", lambda: DeploymentProfile.LOCAL_IMPORT,
    )
    try:
        await database.init_db()
        async with AsyncSession(engine, expire_on_commit=False) as session:
            user = User(openid="synthetic-orm-registry-user")
            session.add(user)
            await session.commit()
            identifier = user.id
        await database.init_db()
        async with engine.connect() as connection:
            names = await connection.run_sync(lambda conn: inspect(conn).get_table_names())
        assert set(names) == set(database.Base.metadata.tables)
        async with AsyncSession(engine) as session:
            result = await session.scalar(select(User).where(User.id == identifier))
            assert result.openid == "synthetic-orm-registry-user"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_cloud_api_initialization_does_not_issue_local_schema_ddl(monkeypatch):
    begin = MagicMock(side_effect=AssertionError("cloud profile must not create tables"))
    monkeypatch.setattr(database, "engine", SimpleNamespace(begin=begin))
    monkeypatch.setattr(
        database, "detect_deployment_profile", lambda: DeploymentProfile.CLOUD_API,
    )
    await database.init_db()
    begin.assert_not_called()


@pytest.mark.asyncio
async def test_initialization_failure_exits_transaction_context(monkeypatch):
    context = MagicMock()
    connection = SimpleNamespace(run_sync=AsyncMock(side_effect=RuntimeError("synthetic DDL failure")))
    context.__aenter__ = AsyncMock(return_value=connection)
    context.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(database, "engine", SimpleNamespace(begin=lambda: context))
    monkeypatch.setattr(
        database, "detect_deployment_profile", lambda: DeploymentProfile.LOCAL_IMPORT,
    )
    with pytest.raises(RuntimeError, match="synthetic DDL failure"):
        await database.init_db()
    context.__aexit__.assert_awaited_once()
    assert context.__aexit__.call_args.args[0] is RuntimeError
