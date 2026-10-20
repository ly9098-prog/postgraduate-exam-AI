"""Verify the startup session owners persist and roll back on temporary SQLite."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.core.deployment_profile import DeploymentProfile
from app.core.orm_base import Base
from app.models.admin import AdminUser, AuditLog, Role
from app.models.recommendation_strategy_config import RecommendationStrategyConfig
from app.services import admin_bootstrap_service, runtime_startup_checks


async def counts(factory):
    async with factory() as session:
        return [
            await session.scalar(select(func.count()).select_from(model))
            for model in [AdminUser, Role, AuditLog, RecommendationStrategyConfig]
        ]


@pytest.mark.asyncio
async def test_real_startup_sessions_commit_seed_data_and_are_idempotent(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'startup.db'}")
    commits = []

    class TrackedSession(AsyncSession):
        async def commit(self):
            commits.append("commit")
            await super().commit()

    factory = async_sessionmaker(engine, class_=TrackedSession, expire_on_commit=False)
    logger = SimpleNamespace(info=Mock(), warning=Mock(), error=Mock())
    monkeypatch.setattr(runtime_startup_checks, "logger", logger)
    monkeypatch.setattr(admin_bootstrap_service, "detect_deployment_profile", lambda: DeploymentProfile.LOCAL_IMPORT)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        snapshots = []
        for _ in range(2):
            await runtime_startup_checks.initialize_dev_admin(
                factory, admin_bootstrap_service.ensure_dev_super_admin,
                SimpleNamespace(APP_ENV="test"),
            )
            await runtime_startup_checks.seed_recommendation_strategies(factory)
            await runtime_startup_checks.log_ai_model_configuration(factory)
            snapshots.append(await counts(factory))
        assert all(count > 0 for count in snapshots[0])
        assert snapshots[0] == snapshots[1]
        assert len(commits) == 4  # Only the admin and strategy session owners commit.
        assert logger.error.call_count == 2
        assert all(call.args[0].startswith("AI_MODEL_NOT_CONFIGURED:") for call in logger.error.call_args_list)
        logger.warning.assert_not_called()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_real_session_exit_rolls_back_seed_writes_after_commit_failure(tmp_path, monkeypatch, error_type):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'startup-rollback.db'}")
    error = error_type("synthetic commit failure")

    class FailingSession(AsyncSession):
        async def commit(self):
            raise error

    factory = async_sessionmaker(engine, class_=FailingSession, expire_on_commit=False)
    inspect_factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(admin_bootstrap_service, "detect_deployment_profile", lambda: DeploymentProfile.LOCAL_IMPORT)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        for name in ["admin", "strategy"]:
            async def run():
                if name == "admin":
                    await runtime_startup_checks.initialize_dev_admin(
                        factory, admin_bootstrap_service.ensure_dev_super_admin,
                        SimpleNamespace(APP_ENV="test"),
                    )
                else:
                    await runtime_startup_checks.seed_recommendation_strategies(factory)
            if error_type is asyncio.CancelledError:
                with pytest.raises(asyncio.CancelledError) as caught:
                    await run()
                assert caught.value is error
            else:
                await run()
            assert await counts(inspect_factory) == [0, 0, 0, 0]
    finally:
        await engine.dispose()
