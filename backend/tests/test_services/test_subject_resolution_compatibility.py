"""Real SQLite compatibility baseline for subject resolution."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.core.database import Base
from app.models.admin import Subject
from app.services import subject_resolution


async def _make_database(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'subj.db'}",
        connect_args={"timeout": 30},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf() as db:
        root = Subject(id=1, code="exam408", name="408", level=1, path="exam408")
        ds = Subject(id=2, parent_id=1, code="ds", name="数据结构", level=2, path="exam408/ds")
        cn = Subject(id=3, parent_id=1, code="cn", name="计网", level=2, path="exam408/cn")
        os_subj = Subject(id=4, parent_id=2, code="ds_sort", name="排序", level=3, path="exam408/ds/sort")
        db.add_all([root, ds, cn, os_subj])
        await db.commit()
    return engine, sf


@pytest.mark.asyncio
async def test_resolve_none_returns_none(tmp_path):
    engine, sf = await _make_database(tmp_path)
    async with sf() as db:
        assert await subject_resolution.resolve_subject_id(db, None) is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_resolve_by_int_id(tmp_path):
    engine, sf = await _make_database(tmp_path)
    async with sf() as db:
        assert await subject_resolution.resolve_subject_id(db, 2) == 2
        assert await subject_resolution.resolve_subject_id(db, 999) is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_resolve_by_code_case_insensitive(tmp_path):
    engine, sf = await _make_database(tmp_path)
    async with sf() as db:
        assert await subject_resolution.resolve_subject_id(db, "DS") == 2
        assert await subject_resolution.resolve_subject_id(db, "ds") == 2
    await engine.dispose()


@pytest.mark.asyncio
async def test_resolve_empty_string_returns_none(tmp_path):
    engine, sf = await _make_database(tmp_path)
    async with sf() as db:
        assert await subject_resolution.resolve_subject_id(db, "") is None
        assert await subject_resolution.resolve_subject_id(db, "  ") is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_resolve_unknown_code_returns_none(tmp_path):
    engine, sf = await _make_database(tmp_path)
    async with sf() as db:
        assert await subject_resolution.resolve_subject_id(db, "nonexistent") is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_resolve_ids_without_descendants(tmp_path):
    engine, sf = await _make_database(tmp_path)
    async with sf() as db:
        ids = await subject_resolution.resolve_subject_ids(db, 2, include_descendants=False)
        assert ids == [2]
    await engine.dispose()


@pytest.mark.asyncio
async def test_resolve_ids_with_descendants(tmp_path):
    engine, sf = await _make_database(tmp_path)
    async with sf() as db:
        ids = await subject_resolution.resolve_subject_ids(db, 2, include_descendants=True)
        assert set(ids) == {2, 4}
    await engine.dispose()


@pytest.mark.asyncio
async def test_resolve_ids_root_includes_all(tmp_path):
    engine, sf = await _make_database(tmp_path)
    async with sf() as db:
        ids = await subject_resolution.resolve_subject_ids(db, 1)
        assert set(ids) == {1, 2, 3, 4}
    await engine.dispose()


@pytest.mark.asyncio
async def test_resolve_ids_unknown_returns_empty(tmp_path):
    engine, sf = await _make_database(tmp_path)
    async with sf() as db:
        ids = await subject_resolution.resolve_subject_ids(db, "nonexistent")
        assert ids == []
    await engine.dispose()
