"""Exercise the shared resolver against SQL, including legacy inactive descendants."""

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.admin import Subject
from app.services.subject_resolution import resolve_subject_id, resolve_subject_ids


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Subject.__table__.create)
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add_all([
                Subject(id=1, code="exam408", name="Root", path="exam408", level=1),
                Subject(
                    id=2, code="data_structure", name="Data structure",
                    path="exam408/data_structure", parent_id=1, level=2,
                ),
                Subject(
                    id=3, code="inactive", name="Inactive", path="exam408/inactive",
                    parent_id=1, level=2, is_active=False,
                ),
                Subject(
                    id=4, code="leaf", name="Leaf", path="exam408/inactive/leaf",
                    parent_id=3, level=3,
                ),
                Subject(id=5, code="math2", name="Math", path="math2", level=1),
            ])
            await session.commit()
            yield session
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(("value", "expected"), [
    (None, None), ("", None), ("  ", None), (1, 1), (999, None),
    ("exam408", 1), (" EXAM408 ", 1), ("data_structure", 2),
    ("structure", None), ("Data structure", None), ("1", None),
    ("unknown", None), ("inactive", 3),
])
async def test_exact_canonical_lookup(db, value, expected):
    assert await resolve_subject_id(db, value) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(("value", "descendants", "expected"), [
    ("exam408", True, {1, 2, 3, 4}), (1, True, {1, 2, 3, 4}),
    ("exam408", False, {1}), ("inactive", True, {3, 4}),
    ("data_structure", True, {2}), ("math2", True, {5}),
    ("unknown", True, set()), (None, True, set()),
])
async def test_scope_preserves_descendants_and_unrelated_roots(db, value, descendants, expected):
    result = await resolve_subject_ids(db, value, include_descendants=descendants)
    assert set(result) == expected
    assert len(result) == len(expected)


@pytest.mark.asyncio
async def test_default_scope_does_not_write_or_own_transaction(db, monkeypatch):
    commit = AsyncMock()
    rollback = AsyncMock()
    flush = AsyncMock()
    monkeypatch.setattr(db, "commit", commit)
    monkeypatch.setattr(db, "rollback", rollback)
    monkeypatch.setattr(db, "flush", flush)
    assert set(await resolve_subject_ids(db, "exam408")) == {1, 2, 3, 4}
    commit.assert_not_awaited()
    rollback.assert_not_awaited()
    flush.assert_not_awaited()
