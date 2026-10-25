"""Contracts for import background source identity digest resolution."""

from __future__ import annotations

import io
import logging
from types import SimpleNamespace

from app.services.import_source_digest import (
    SourceDigestRequest,
    resolve_source_digest,
)


def request(provided=None, open_file=open, logger=None):
    return SourceDigestRequest(
        pipeline_id="pipe-1",
        file_path="/tmp/source.pdf",
        provided_sha256=provided,
        open_file=open_file,
        logger=logger or logging.getLogger("synthetic"),
    )


def test_provided_digest_is_returned_without_file_io():
    sentinel = object()
    assert resolve_source_digest(request("digest", open_file=sentinel)) == "digest"


def test_missing_digest_hashes_file_in_one_megabyte_chunks():
    calls = []

    def fake_open(*_args, **_kwargs):
        calls.append((_args, _kwargs))
        return io.BytesIO(b"source-bytes")

    digest = resolve_source_digest(request(None, open_file=fake_open))

    import hashlib

    assert digest == hashlib.sha256(b"source-bytes").hexdigest()
    assert calls == [(("/tmp/source.pdf", "rb"), {})]


def test_read_failure_returns_none_and_keeps_resume_optional_log():
    records = []

    class RecordingLogger(SimpleNamespace):
        def exception(self, message, *args):
            records.append((message % args))

    def fail_open(*_args, **_kwargs):
        raise OSError("missing")

    result = resolve_source_digest(
        request(None, open_file=fail_open, logger=RecordingLogger())
    )
    assert result is None
    assert records == [
        "compute source_sha256 failed for pipeline pipe-1; "
        "resume identity check will be skipped"
    ]
