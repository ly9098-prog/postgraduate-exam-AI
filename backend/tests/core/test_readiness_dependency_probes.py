"""Characterize infrastructure probe IO, fallbacks and cancellation."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app import main


def session_factory(*, execute=None, enter_error=None):
    class Context:
        async def __aenter__(self):
            if enter_error:
                raise enter_error
            return SimpleNamespace(execute=execute)

        async def __aexit__(self, *_args):
            return False

    return Mock(return_value=Context())


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "enter", "execute", "cancelled"])
async def test_database_probe_uses_real_select_and_original_error_boundary(monkeypatch, failure):
    error = asyncio.CancelledError() if failure == "cancelled" else RuntimeError("synthetic")
    execute = AsyncMock(side_effect=error if failure in {"execute", "cancelled"} else None)
    factory = session_factory(execute=execute, enter_error=error if failure == "enter" else None)
    monkeypatch.setattr(main, "async_session", factory)
    if failure == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            await main.check_database(main.async_session)
    else:
        assert await main.check_database(main.async_session) is (failure is None)
    if failure != "enter":
        assert str(execute.await_args.args[0]) == "SELECT 1"


@pytest.mark.asyncio
@pytest.mark.parametrize("configured", [False, True])
@pytest.mark.parametrize("production", [False, True])
@pytest.mark.parametrize("outcome", [True, False, "error", "cancelled"])
async def test_redis_probe_requires_ping_without_cache_fallback(
    monkeypatch, configured, production, outcome
):
    from app.core.cache import cache
    from app.core.deployment_profile import DeploymentProfile

    monkeypatch.setattr(main.settings, "REDIS_URL", "redis://synthetic" if configured else "")
    monkeypatch.setattr(main, "_production_mode", production)
    monkeypatch.setattr(
        "app.core.deployment_profile.detect_deployment_profile",
        lambda: DeploymentProfile.LOCAL_IMPORT,
    )
    failure = asyncio.CancelledError() if outcome == "cancelled" else RuntimeError("private")
    ping = AsyncMock(
        side_effect=failure if outcome in {"error", "cancelled"} else None,
        return_value=outcome,
    )
    monkeypatch.setattr(cache, "ping", ping)
    cache_write = Mock(side_effect=AssertionError("probe must not write cache"))
    monkeypatch.setattr(cache, "set", cache_write)
    if configured and outcome == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            await main.check_redis(redis_url=main.settings.REDIS_URL, production_mode=main._production_mode)
    else:
        expected = (not production) if not configured else (outcome is True)
        assert await main.check_redis(redis_url=main.settings.REDIS_URL, production_mode=main._production_mode) is expected
    assert ping.await_count == int(configured)
    cache_write.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["cloud_api", "invalid"])
async def test_missing_redis_still_fails_closed_for_cloud_or_profile_errors(monkeypatch, profile):
    monkeypatch.setattr(main.settings, "REDIS_URL", "")
    monkeypatch.setattr(main, "_production_mode", False)
    monkeypatch.setattr(
        "app.core.deployment_profile.detect_deployment_profile",
        Mock(side_effect=ValueError("synthetic")) if profile == "invalid"
        else lambda: "cloud_api",
    )
    assert await main.check_redis(redis_url=main.settings.REDIS_URL, production_mode=main._production_mode) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("database_revision,head,expected", [
    ("head", "head", True), ("old", "head", False),
    (None, "head", False), ("", "head", False), ("head", None, False),
])
async def test_alembic_uses_existing_location_and_revision_comparison(
    monkeypatch, database_revision, head, expected
):
    from alembic.script import ScriptDirectory

    result = SimpleNamespace(scalar_one_or_none=lambda: database_revision)
    execute = AsyncMock(return_value=result)
    monkeypatch.setattr(main, "async_session", session_factory(execute=execute))
    paths = []

    def from_config(config):
        paths.append(config.get_main_option("script_location"))
        return SimpleNamespace(get_current_head=lambda: head)

    monkeypatch.setattr(ScriptDirectory, "from_config", from_config)
    assert await main.check_alembic_head(
        main.async_session, script_location=main.os.path.join(main.os.path.dirname(main.__file__), "../alembic"),
    ) is expected
    assert str(execute.await_args.args[0]) == "SELECT version_num FROM alembic_version"
    assert paths == [main.os.path.join(main.os.path.dirname(main.__file__), "../alembic")]


@pytest.mark.asyncio
async def test_alembic_discovery_error_is_false(monkeypatch):
    from alembic.script import ScriptDirectory

    execute = AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: "head"))
    monkeypatch.setattr(main, "async_session", session_factory(execute=execute))
    monkeypatch.setattr(ScriptDirectory, "from_config", Mock(side_effect=RuntimeError("private")))
    assert await main.check_alembic_head(
        main.async_session, script_location=main.os.path.join(main.os.path.dirname(main.__file__), "../alembic"),
    ) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("writable", [False, True])
async def test_staging_probe_creates_directory_then_checks_write_access(monkeypatch, writable):
    from app.services import staging_storage

    directory = Mock()
    directory.__str__ = lambda _self: "synthetic-staging"
    monkeypatch.setattr(staging_storage, "_STAGING_DIR", directory)
    access = Mock(return_value=writable)
    monkeypatch.setattr(main.os, "access", access)
    assert await main.check_staging() is writable
    directory.mkdir.assert_called_once_with(parents=True, exist_ok=True)
    access.assert_called_once_with("synthetic-staging", main.os.W_OK)


@pytest.mark.asyncio
async def test_staging_mkdir_failure_does_not_check_access(monkeypatch):
    from app.services import staging_storage

    directory = Mock()
    directory.mkdir.side_effect = OSError("private")
    monkeypatch.setattr(staging_storage, "_STAGING_DIR", directory)
    access = Mock()
    monkeypatch.setattr(main.os, "access", access)
    assert await main.check_staging() is False
    access.assert_not_called()


@pytest.mark.parametrize("failure", [False, True])
def test_db_pool_probe_keeps_metrics_and_error_fallback(monkeypatch, failure):
    from app.core import database

    pool = SimpleNamespace(
        size=lambda: 4, checkedin=lambda: 2, checkedout=lambda: 1, overflow=lambda: -1,
    )
    if failure:
        pool.size = Mock(side_effect=RuntimeError("synthetic pool error"))
    monkeypatch.setattr(database, "engine", SimpleNamespace(sync_engine=SimpleNamespace(pool=pool)))
    assert main.get_db_pool_metrics() == (
        {"error": "synthetic pool error"} if failure
        else {"size": 4, "checked_in": 2, "checked_out": 1, "overflow": -1}
    )
