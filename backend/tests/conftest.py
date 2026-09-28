"""Shared test fixtures."""
from __future__ import annotations

import pytest

from app.core.cache import cache
from tests.fixtures.pdf_helper import make_minimal_pdf


@pytest.fixture(autouse=True)
def _isolate_local_cache():
    """Reset the in-process cache fallback around every test.

    Security keys (permission cache, role versions, rate-limit counters)
    persist in the local fallback within one process; without this reset a
    fake DB result from one test leaks into the next via a cached entry.
    Real Redis deployments are unaffected — this only touches the fallback.
    """
    cache._local.clear()
    yield
    cache._local.clear()


@pytest.fixture
def minimal_pdf_bytes() -> bytes:
    """Return bytes of a minimal 1-page valid PDF."""
    return make_minimal_pdf(page_count=1)


@pytest.fixture
def minimal_pdf_path(tmp_path) -> str:
    """Write a minimal 1-page PDF to a temp file and return its path."""
    p = tmp_path / "test.pdf"
    p.write_bytes(make_minimal_pdf(page_count=1))
    return str(p)


@pytest.fixture
def three_page_pdf_path(tmp_path) -> str:
    """Write a 3-page PDF to a temp file and return its path."""
    p = tmp_path / "test_3p.pdf"
    p.write_bytes(make_minimal_pdf(page_count=3))
    return str(p)


@pytest.fixture
def five_page_pdf_path(tmp_path) -> str:
    """Write a 5-page PDF to a temp file and return its path."""
    p = tmp_path / "test_5p.pdf"
    p.write_bytes(make_minimal_pdf(page_count=5))
    return str(p)


@pytest.fixture
def thirty_page_pdf_path(tmp_path) -> str:
    """Write a 30-page PDF for chunk testing."""
    p = tmp_path / "test_30p.pdf"
    p.write_bytes(make_minimal_pdf(page_count=30))
    return str(p)


@pytest.fixture
def corrupted_pdf_path(tmp_path) -> str:
    """Write a corrupted (invalid) PDF file."""
    p = tmp_path / "corrupted.pdf"
    p.write_bytes(b"this is not a pdf at all")
    return str(p)
