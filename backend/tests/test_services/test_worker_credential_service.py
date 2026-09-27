from __future__ import annotations

from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.time_utils import utcnow
from app.services.worker_credential_service import (
    create_credential,
    list_credentials,
    rotate_credential,
    verify_credential,
)


@pytest_asyncio.fixture
async def credential_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'credentials.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_verify_and_rotate_worker_credential(credential_session):
    credential, raw_key = await create_credential(credential_session, "gpu-worker-1")
    await credential_session.commit()

    assert raw_key != credential.key_hash
    assert await verify_credential(credential_session, "gpu-worker-1", raw_key) == credential
    assert await verify_credential(credential_session, "gpu-worker-1", "wrong") is None

    rotated = await rotate_credential(credential_session, credential.id)
    assert rotated is not None
    new_credential, new_raw_key = rotated
    await credential_session.commit()

    assert not credential.is_active
    assert credential.rotated_at is not None
    assert await verify_credential(credential_session, "gpu-worker-1", raw_key) is None
    assert (
        await verify_credential(credential_session, "gpu-worker-1", new_raw_key)
        == new_credential
    )
    assert {item.id for item in await list_credentials(credential_session)} == {
        new_credential.id,
        credential.id,
    }


@pytest.mark.asyncio
async def test_expired_worker_credential_is_rejected(credential_session):
    _, raw_key = await create_credential(
        credential_session,
        "expired-worker",
        expires_at=utcnow() - timedelta(seconds=1),
    )
    await credential_session.commit()

    assert await verify_credential(credential_session, "expired-worker", raw_key) is None
