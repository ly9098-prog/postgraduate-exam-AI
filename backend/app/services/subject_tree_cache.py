"""Practice subject-tree cache (24h, Redis-shared, best-effort).

The student subject tree is read on every pomodoro page open and on the
practice page. It changes only through the Admin subject API, so a 24h cache
is safe as long as the Admin write path invalidates it.

Redis is the shared cache layer; if Redis is unavailable ``cache.get`` /
``cache.set`` degrade to the in-process cache, so the API stays available.
Admin mutations call :func:`invalidate_subject_tree_cache` so a subject
enable/disable/rename does not keep serving a stale tree for a day.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.cache import cache

logger = logging.getLogger("postgraduate-ai.subject-tree-cache")

# 24h. Bumped only through the Admin subject write path.
SUBJECT_TREE_CACHE_TTL_SEC = 24 * 60 * 60
SUBJECT_TREE_CACHE_PREFIX = "practice:subject_tree"


def _cache_key_shared() -> str:
    return f"{SUBJECT_TREE_CACHE_PREFIX}:student:v2"


def _cache_key_user(user_id: int | None) -> str:
    """Same payload is shared by all users; user_id is accepted for clarity.

    Kept as a separate function so a future per-user personalization can add
    the user dimension without changing call sites.
    """
    return _cache_key_shared()


async def get_cached_subject_tree(user_id: int | None = None) -> list[dict] | None:
    """Return the cached tree, or None on miss/deserialization failure."""
    payload = await cache.get(_cache_key_user(user_id))
    if payload is None:
        return None
    if not isinstance(payload, list):
        logger.warning("subject tree cache payload is not a list; treating as miss")
        return None
    return payload


async def set_cached_subject_tree(
    tree: list[dict[str, Any]],
    user_id: int | None = None,
) -> None:
    """Cache the tree, ignoring cache failures (best-effort)."""
    try:
        await cache.set(
            _cache_key_user(user_id),
            tree,
            ttl=SUBJECT_TREE_CACHE_TTL_SEC,
        )
    except Exception:
        logger.debug("subject tree cache write failed", exc_info=True)


async def invalidate_subject_tree_cache() -> int:
    """Drop the shared tree after any Admin subject mutation."""
    try:
        return await cache.delete(f"{SUBJECT_TREE_CACHE_PREFIX}:*")
    except Exception:
        logger.warning("subject tree cache invalidation failed", exc_info=True)
        return 0
