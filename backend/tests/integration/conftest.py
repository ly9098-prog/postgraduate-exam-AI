"""Integration test fixtures for PostgreSQL and Redis.

Usage:
    docker compose -f deploy/docker-compose.test.yml up -d
    python -m pytest tests/integration/ -x --run-integration

Requires ``--run-integration`` to avoid accidental use in CI/dev environments.

Note: pytest-asyncio 1.3.0 doesn't support async fixtures in conftest.
All fixtures here are sync. Tests handle async setup async/await inline.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Default test connection URLs (match deploy/docker-compose.test.yml)
TEST_POSTGRES_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5433/testdb",
)
TEST_REDIS_URL = os.environ.get(
    "TEST_REDIS_URL",
    "redis://localhost:6380/1",
)


def pytest_addoption(parser):
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests requiring PostgreSQL and/or Redis",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: marks tests that need --run-integration")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-integration"):
        return  # let all tests run
    skip_integration = pytest.mark.skip(reason="need --run-integration option to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)


# ── PostgreSQL fixtures (sync — pytest-asyncio 1.3.0 compat) ──


@pytest.fixture
def pg_engine():
    """Create a PostgreSQL engine (function-scoped)."""
    engine = create_async_engine(TEST_POSTGRES_URL, echo=False)
    yield engine


@pytest.fixture
def pg_session(pg_engine):
    """Return an async_sessionmaker. Tests create sessions with ``async with``."""
    return async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)


# ── Redis fixtures (sync — pytest-asyncio 1.3.0 compat) ──


@pytest.fixture
def redis_client():
    """Return a Redis client. ``from_url`` is synchronous."""
    import redis.asyncio as aioredis

    return aioredis.from_url(TEST_REDIS_URL, decode_responses=True)


@pytest.fixture
def redis_session(redis_client):
    """Flush the test DB before each test. Returns the client."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    loop.run_until_complete(redis_client.flushdb())
    yield redis_client
    loop.run_until_complete(redis_client.flushdb())


# ── Combined fixture (sync) ──


@pytest.fixture
def integration_env(pg_session, redis_session):
    """Both a sessionmaker and a clean Redis client."""
    return {"pg": pg_session, "redis": redis_session}
