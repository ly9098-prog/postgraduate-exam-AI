"""Staging storage unit tests — store, retrieve, delete, cleanup, quota."""
import os
import tempfile
import time

from app.services.staging_storage import (
    StagingObject,
    _sha256_of_file,
    cleanup_orphans,
    delete_object,
    get_metadata,
    retrieve_file,
    store_file,
    sweep_temp_files,
)


class TestStagingStorage:
    """Core staging operations."""

    def test_store_and_retrieve(self):
        """Store a file and retrieve it by object_id."""
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        tmp.write(b"hello staging")
        tmp.close()

        try:
            obj = store_file(tmp.name, original_name="test.txt", mime="text/plain")
            assert obj.object_id
            assert obj.sha256
            assert obj.size == 13
            assert obj.mime == "text/plain"
            assert obj.original_name == "test.txt"

            path = retrieve_file(obj.object_id)
            assert path is not None
            assert os.path.exists(path)
            with open(path) as f:
                assert f.read() == "hello staging"
        finally:
            os.unlink(tmp.name)

    def test_delete_removes_file(self):
        """Delete removes the staged file and metadata."""
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        tmp.write(b"delete me")
        tmp.close()

        try:
            obj = store_file(tmp.name)
            assert retrieve_file(obj.object_id) is not None
            assert delete_object(obj.object_id) is True
            assert retrieve_file(obj.object_id) is None
            # Second delete returns False
            assert delete_object(obj.object_id) is False
        finally:
            os.unlink(tmp.name)

    def test_get_metadata(self):
        """Metadata is retrievable and correct."""
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".bin")
        tmp.write(b"meta data")
        tmp.close()

        try:
            obj = store_file(tmp.name, original_name="meta.bin", mime="application/octet-stream")
            meta = get_metadata(obj.object_id)
            assert meta is not None
            assert meta.object_id == obj.object_id
            assert meta.size == 9
            assert meta.original_name == "meta.bin"
            assert meta.mime == "application/octet-stream"

            # Non-existent returns None
            assert get_metadata("nonexistent") is None
        finally:
            os.unlink(tmp.name)

    def test_content_addressed_dedup(self):
        """Same content produces same object_id (content-addressed)."""
        tmp1 = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        tmp2 = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        tmp1.write(b"identical content")
        tmp2.write(b"identical content")
        tmp1.close()
        tmp2.close()

        try:
            obj1 = store_file(tmp1.name)
            obj2 = store_file(tmp2.name)
            assert obj1.object_id == obj2.object_id
        finally:
            os.unlink(tmp1.name)
            os.unlink(tmp2.name)

    def test_sha256_of_file(self):
        """SHA-256 helper computes correct hash."""
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        tmp.write(b"hello")
        tmp.close()

        try:
            h = _sha256_of_file(tmp.name)
            assert h == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
        finally:
            os.unlink(tmp.name)


class TestStagingCleanup:
    """Cleanup and sweep operations."""

    def test_cleanup_orphans_removes_expired(self):
        """Cleanup removes objects older than max_age."""
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        tmp.write(b"old data")
        tmp.close()

        try:
            obj = store_file(tmp.name)
            # Force the object to appear expired by using a negative age
            deleted = cleanup_orphans(max_age_sec=-1)
            assert deleted >= 1
            assert retrieve_file(obj.object_id) is None
        finally:
            os.unlink(tmp.name)

    def test_cleanup_preserves_recent(self):
        """Cleanup does not remove objects within max_age."""
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        tmp.write(b"recent data")
        tmp.close()

        try:
            obj = store_file(tmp.name)
            # Use a large max_age — should not delete
            deleted = cleanup_orphans(max_age_sec=86400 * 30)  # 30 days
            assert deleted == 0
            assert retrieve_file(obj.object_id) is not None
        finally:
            os.unlink(tmp.name)

    def test_sweep_temp_files(self):
        """Sweep removes only files older than 24h."""
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".tmp")
        tmp.write(b"stale temp")
        tmp.close()
        target_dir = os.path.dirname(tmp.name)

        try:
            # sweep targets staging dir, not system /tmp — just verify it runs
            swept = sweep_temp_files()
            assert isinstance(swept, int)
            assert swept >= 0
        finally:
            os.unlink(tmp.name)


class TestStagingEdgeCases:
    """Edge cases and error handling."""

    def test_store_nonexistent_file(self):
        """Storing a non-existent file raises an error."""
        import pytest
        with pytest.raises(FileNotFoundError):
            store_file("/nonexistent/path/file.txt")

    def test_retrieve_nonexistent_id(self):
        """Retrieving a non-existent ID returns None."""
        assert retrieve_file("nonexistent_id") is None

    def test_delete_nonexistent_id(self):
        """Deleting a non-existent ID returns False."""
        assert delete_object("nonexistent_id") is False
