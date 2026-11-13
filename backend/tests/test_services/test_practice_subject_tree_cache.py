"""get_practice_subject_tree must serve a 24h cache and fall back to DB."""

from types import SimpleNamespace
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


@pytest.mark.parametrize("code", [
    "advanced_math", "math2-calculus", "linear_algebra", "math2-linalg", "english", "politics", "pol",
])
async def test_disabled_extra_subject_is_unavailable(code):
    from app.core.subject_scope import (
        is_study_subject_enabled,
        select_study_subject_records,
    )
    from app.services.practice_service import (
        resolve_practice_subject_scope,
        resolve_subject_id_to_code,
    )

    subject = SimpleNamespace(id=2, code=code, name=code, parent_id=None, is_active=False)
    assert not is_study_subject_enabled(subject)
    assert select_study_subject_records([subject]) == []
    assert await resolve_subject_id_to_code(_db_with_subjects([subject]), 2) is None
    db = _db_with_subjects([subject])
    db.get = AsyncMock(return_value=subject)
    assert await resolve_practice_subject_scope(db, 2, include_children=False) == (False, [])


async def test_disabled_math_parent_hides_active_leaf_and_blocks_direct_scope():
    from app.core.subject_scope import select_study_subject_records
    from app.services.practice_service import resolve_practice_subject_scope

    parent = SimpleNamespace(id=1, code="math", name="数学", parent_id=None, is_active=False)
    leaf = SimpleNamespace(id=2, code="advanced_math", name="高数", parent_id=1, is_active=True)
    subjects = [parent, leaf]
    db = _db_with_subjects(subjects)
    db.get = AsyncMock(return_value=leaf)

    assert select_study_subject_records(subjects) == []
    assert await resolve_practice_subject_scope(db, 2, include_children=False) == (False, [])


@pytest.mark.parametrize("parent_id", [99, 2])
async def test_extra_subject_with_missing_or_cyclic_parent_is_unavailable(parent_id):
    from app.core.subject_scope import select_study_subject_records

    subject = SimpleNamespace(id=2, code="english", name="英语", parent_id=parent_id, is_active=True)
    assert select_study_subject_records([subject]) == []


@pytest.mark.parametrize("parent_active", [True, False])
async def test_extra_subject_under_custom_category_honors_ancestor_activation(parent_active):
    from app.core.subject_scope import select_study_subject_records
    from app.services.practice_service import (
        resolve_practice_subject_scope,
        resolve_subject_id_to_code,
    )

    parent = _subject(1, "languages", "语言")
    parent.is_active = parent_active
    leaf = _subject(2, "english", "英语", parent_id=1, level=2)
    leaf.is_active = True
    subjects = [parent, leaf]
    database = _db_with_subjects(subjects)
    database.get = AsyncMock(return_value=leaf)

    assert select_study_subject_records(subjects) == ([leaf] if parent_active else [])
    assert await resolve_subject_id_to_code(database, 2) == (
        ("english", "英语") if parent_active else None
    )
    assert await resolve_practice_subject_scope(database, 2, include_children=False) == (
        False, [2] if parent_active else []
    )


async def test_enabled_math_subjects_keep_their_parent_and_resolve_scope():
    from app.core.subject_scope import select_study_subject_records
    from app.services.practice_service import resolve_practice_subject_scope

    parent = SimpleNamespace(id=1, code="math", name="数学", parent_id=None, is_active=True, sort_order=0)
    active = SimpleNamespace(id=2, code="advanced_math", name="高数", parent_id=1, is_active=True, sort_order=0)
    inactive = SimpleNamespace(id=3, code="linear_algebra", name="线代", parent_id=1, is_active=False, sort_order=0)
    subjects = [parent, active, inactive]
    db = _db_with_subjects(subjects)
    db.get = AsyncMock(return_value=parent)

    assert select_study_subject_records(subjects) == [parent, active]
    assert await resolve_practice_subject_scope(db, 1, include_children=True) == (True, [1, 2])


async def test_subject_tree_tracks_disable_and_reenable_after_admin_invalidation():
    from app.services import practice_service
    from app.services.subject_tree_cache import invalidate_subject_tree_cache

    subject = _subject(1, "english", "英语")
    subject.is_active = True
    db = _db_with_subjects([subject])

    assert len(await practice_service.get_practice_subject_tree(db)) == 1
    subject.is_active = False
    await invalidate_subject_tree_cache()
    assert await practice_service.get_practice_subject_tree(db) == []
    subject.is_active = True
    await invalidate_subject_tree_cache()
    assert len(await practice_service.get_practice_subject_tree(db)) == 1
