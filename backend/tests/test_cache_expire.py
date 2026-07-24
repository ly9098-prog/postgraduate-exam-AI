"""Tests for cache.expire() method (P1-4 fix)."""


class TestCacheExpire:
    """CacheClient.expire() was missing — P1-4 fix added it."""

    def test_expire_attribute_exists(self):
        from app.core.cache import cache
        assert hasattr(cache, "expire"), "cache.expire() method must exist"
        assert callable(cache.expire), "cache.expire() must be callable"
