"""Unit tests for ResourceGuard (P0-4, P0-6 coverage)."""

import pytest
from app.core.resource_guard import ResourceGuard, ResourceGuardError, resource_guard


class TestResourceGuard:
    """ResourceGuard basic invariants."""

    def test_guard_is_singleton(self):
        assert resource_guard is not None
        assert isinstance(resource_guard, ResourceGuard)

    def test_error_code_and_message(self):
        err = ResourceGuardError("TEST_CODE", "test message")
        assert err.code == "TEST_CODE"
        assert str(err) == "test message"
        assert isinstance(err, ValueError)

    def test_check_input_bytes_ok(self):
        resource_guard.check_input_bytes(1024)  # small file, should pass

    def test_check_page_count_ok(self):
        resource_guard.check_page_count(5)  # few pages, should pass

    def test_check_page_count_exceeds(self):
        guard = ResourceGuard()
        guard.max_pages = 3
        with pytest.raises(ResourceGuardError) as exc_info:
            guard.check_page_count(10)
        assert exc_info.value.code == "PAGE_LIMIT_EXCEEDED"
