"""Practice subject-tree cache — 24h shared cache + Admin invalidation."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services import subject_tree_cache


@pytest.mark.asyncio
async def test_cache_miss_returns_none():
    with patch("app.services.subject_tree_cache.cache") as mock_cache:
        mock_cache.get = AsyncMock(return_value=None)
        assert await subject_tree_cache.get_cached_subject_tree() is None


@pytest.mark.asyncio
async def test_cache_hit_returns_tree():
    tree = [{"id": 1, "code": "exam408", "children": []}]
    with patch("app.services.subject_tree_cache.cache") as mock_cache:
        mock_cache.get = AsyncMock(return_value=tree)
        assert await subject_tree_cache.get_cached_subject_tree() == tree


@pytest.mark.asyncio
async def test_non_list_payload_treated_as_miss():
    with patch("app.services.subject_tree_cache.cache") as mock_cache:
        mock_cache.get = AsyncMock(return_value={"not": "a list"})
        assert await subject_tree_cache.get_cached_subject_tree() is None


@pytest.mark.asyncio
async def test_set_caches_for_one_day():
    tree = [{"id": 1, "children": []}]
    with patch("app.services.subject_tree_cache.cache") as mock_cache:
        mock_cache.set = AsyncMock()
        await subject_tree_cache.set_cached_subject_tree(tree)
        mock_cache.set.assert_awaited_once()
        kwargs = mock_cache.set.await_args.kwargs
        assert kwargs["ttl"] == 24 * 60 * 60


@pytest.mark.asyncio
async def test_set_failure_is_non_fatal():
    tree = [{"id": 1, "children": []}]
    with patch("app.services.subject_tree_cache.cache") as mock_cache:
        mock_cache.set = AsyncMock(side_effect=RuntimeError("redis down"))
        # Must not raise — subject loading stays available.
        await subject_tree_cache.set_cached_subject_tree(tree)


@pytest.mark.asyncio
async def test_invalidate_deletes_namespace():
    with patch("app.services.subject_tree_cache.cache") as mock_cache:
        mock_cache.delete = AsyncMock(return_value=3)
        assert await subject_tree_cache.invalidate_subject_tree_cache() == 3
        pattern = mock_cache.delete.await_args.args[0]
        assert pattern == "practice:subject_tree:*"


@pytest.mark.asyncio
async def test_invalidate_failure_is_non_fatal():
    with patch("app.services.subject_tree_cache.cache") as mock_cache:
        mock_cache.delete = AsyncMock(side_effect=RuntimeError("redis down"))
        assert await subject_tree_cache.invalidate_subject_tree_cache() == 0
