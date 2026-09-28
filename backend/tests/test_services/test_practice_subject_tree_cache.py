"""get_practice_subject_tree must serve a 24h cache and fall back to DB."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio


def _subject(subject_id, code, name, parent_id=None, level=1, sort_order=0):
    s = MagicMock()
    s.id = subject_id
    s.code = code
    s.name = name
    s.parent_id = parent_id
    s.level = level
    s.sort_order = sort_order
    s.path = code
    return s


def _db_with_subjects(subjects):
    db = MagicMock()
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = subjects
    result.scalars.return_value = scalars
    db.execute = AsyncMock(return_value=result)
    return db


async def test_cache_hit_skips_database():
    from app.services import practice_service

    cached_tree = [{"subject_id": 1, "subject_code": "exam408", "children": []}]
    db = _db_with_subjects([])
    with patch(
        "app.services.subject_tree_cache.get_cached_subject_tree",
        new=AsyncMock(return_value=cached_tree),
    ):
        tree = await practice_service.get_practice_subject_tree(db)

    assert tree == cached_tree
    db.execute.assert_not_awaited()


async def test_cache_miss_queries_db_and_populates_cache():
    from app.services import practice_service

    subjects = [
        _subject(1, "exam408", "计算机", None, 1),
        _subject(2, "data_structure", "数据结构", 1, 2, 10),
    ]
    db = _db_with_subjects(subjects)
    set_mock = AsyncMock()
    with (
        patch(
            "app.services.subject_tree_cache.get_cached_subject_tree",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.services.subject_tree_cache.set_cached_subject_tree",
            new=set_mock,
        ),
    ):
        tree = await practice_service.get_practice_subject_tree(db)

    assert db.execute.await_count == 1
    assert len(tree) == 1
    assert tree[0]["subject_code"] == "exam408"
    assert tree[0]["children"][0]["subject_code"] == "data_structure"
    set_mock.assert_awaited_once()
