"""Integration test fixtures for PostgreSQL and Redis.

Usage:
    docker compose -f deploy/docker-compose.test.yml up -d
    python -m pytest tests/integration/ -x --run-integration

Requires ``--run-integration`` to avoid accidental use in CI/dev environments.
"""

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


# ── PostgreSQL fixtures ─────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def pg_engine():
    """Create a PostgreSQL engine (session-scoped)."""
    engine = create_async_engine(TEST_POSTGRES_URL, echo=False)
    yield engine


@pytest.fixture
async def pg_session(pg_engine):
    """Yield a standalone PostgreSQL session per test with full DDL + teardown."""
    from app.models import Base

    async with pg_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)() as session:
        yield session
    async with pg_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# ── Redis fixtures ──────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def redis_client():
    """Create a Redis client (session-scoped). ``from_url`` is synchronous."""
    import redis.asyncio as aioredis

    return aioredis.from_url(TEST_REDIS_URL, decode_responses=True)


@pytest.fixture
async def redis_session(redis_client):
    """Flush the test DB before each test."""
    await redis_client.flushdb()
    yield redis_client
    await redis_client.flushdb()


# ── Combined fixture ────────────────────────────────────────────────────────


@pytest.fixture
async def integration_env(pg_session, redis_session):
    """Both a PG session and a clean Redis client."""
    return {"pg": pg_session, "redis": redis_session}
