"""PageStream Profile Config — Verify profile-aware PageStream creation."""
from __future__ import annotations

from app.features.page_stream import PageStream


def test_local_profile_window_size():
    stream = PageStream.for_profile("local_import")
    assert stream._window_size >= 2


def test_cloud_profile_window_size():
    stream = PageStream.for_profile("cloud_api")
    assert stream._window_size >= 2  # min window_size


def test_profile_classmethod_returns_stream():
    stream = PageStream.for_profile("local_import")
    assert isinstance(stream, PageStream)


def test_cloud_stream_default_overlap():
    stream = PageStream.for_profile("cloud_api")
    # cloud_api defaults to overlap=0, but PageStream enforces overlap <= window_size // 2
    assert stream._overlap == 0


def test_explicit_cloud_overrides():
    stream = PageStream.for_profile("cloud_api", window_size=2, overlap=0)
    assert stream._window_size == 2
    assert stream._overlap == 0
