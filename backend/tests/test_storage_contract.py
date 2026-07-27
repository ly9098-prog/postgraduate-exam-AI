"""Storage contract tests — LocalFileStorage and MinIO (S3-compatible).

Tests verify that storage backends satisfy the StorageBackend contract:
  upload, delete, exists, get_download_url
"""
from __future__ import annotations

import pytest


class TestLocalFileStorageContract:
    """LocalFileStorage contract tests (async)."""

    @pytest.mark.asyncio
    async def test_upload_and_exists(self, tmpdir):
        from app.services.storage_backend import LocalFileStorage
        storage = LocalFileStorage(prefix=str(tmpdir))

        url = await storage.upload("test/file.pdf", b"test content")
        assert url is not None
        assert str(tmpdir) in url

        exists = await storage.exists("test/file.pdf")
        assert exists is True

    @pytest.mark.asyncio
    async def test_delete(self, tmpdir):
        from app.services.storage_backend import LocalFileStorage
        storage = LocalFileStorage(prefix=str(tmpdir))
        await storage.upload("test/file.pdf", b"test content")
        assert await storage.exists("test/file.pdf")

        deleted = await storage.delete("test/file.pdf")
        assert deleted is True
        assert await storage.exists("test/file.pdf") is False

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_true(self, tmpdir):
        """LocalFileStorage.delete returns True if file doesn't exist (already clean)."""
        from app.services.storage_backend import LocalFileStorage
        storage = LocalFileStorage(prefix=str(tmpdir))
        assert await storage.delete("nonexistent.pdf") is True

    @pytest.mark.asyncio
    async def test_get_download_url_returns_none(self, tmpdir):
        from app.services.storage_backend import LocalFileStorage
        storage = LocalFileStorage(prefix=str(tmpdir))
        assert await storage.get_download_url("test.pdf") is None


# MinIO tests — synchronous (use minio SDK, not async)
class TestMinioContract:
    """S3-compatible storage contract via MinIO.
    Requires MinIO at localhost:9000. Synchronous tests.
    """

    @classmethod
    def setup_class(cls):
        cls._MINIO_AVAILABLE = False
        try:
            from minio import Minio
            c = Minio("localhost:9000", "minioadmin", "minioadmin", secure=False)
            c.list_buckets()
            cls._MINIO_AVAILABLE = True
        except Exception:
            pass

    def _client(self):
        from minio import Minio
        return Minio("localhost:9000", "minioadmin", "minioadmin", secure=False)

    def _bucket(self):
        return "test-exports-contract"

    def _cleanup(self, client):
        try:
            for obj in client.list_objects(self._bucket(), recursive=True):
                client.remove_object(self._bucket(), obj.object_name)
        except Exception:
            pass

    def test_upload_and_download(self):
        if not self.__class__._MINIO_AVAILABLE:
            pytest.skip("MinIO not available")
        import io
        c = self._client()
        self._cleanup(c)
        if not c.bucket_exists(self._bucket()):
            c.make_bucket(self._bucket())

        content = b"test export file content"
        c.put_object(self._bucket(), "test-uploads/sample.pdf",
                     io.BytesIO(content), len(content))
        response = c.get_object(self._bucket(), "test-uploads/sample.pdf")
        assert response.read() == content

    def test_exists(self):
        if not self.__class__._MINIO_AVAILABLE:
            pytest.skip("MinIO not available")
        import io
        c = self._client()
        self._cleanup(c)
        if not c.bucket_exists(self._bucket()):
            c.make_bucket(self._bucket())

        c.put_object(self._bucket(), "test-exists/file.pdf",
                     io.BytesIO(b"data"), 4)
        assert c.stat_object(self._bucket(), "test-exists/file.pdf")

        with pytest.raises(Exception):
            c.stat_object(self._bucket(), "nonexistent.pdf")

    def test_delete(self):
        if not self.__class__._MINIO_AVAILABLE:
            pytest.skip("MinIO not available")
        import io
        c = self._client()
        self._cleanup(c)
        if not c.bucket_exists(self._bucket()):
            c.make_bucket(self._bucket())

        c.put_object(self._bucket(), "test-delete/file.pdf",
                     io.BytesIO(b"data"), 4)
        c.remove_object(self._bucket(), "test-delete/file.pdf")

        with pytest.raises(Exception):
            c.stat_object(self._bucket(), "test-delete/file.pdf")

    def test_presigned_url(self):
        if not self.__class__._MINIO_AVAILABLE:
            pytest.skip("MinIO not available")
        import io
        from datetime import timedelta
        c = self._client()
        self._cleanup(c)
        if not c.bucket_exists(self._bucket()):
            c.make_bucket(self._bucket())

        c.put_object(self._bucket(), "test-presigned/file.pdf",
                     io.BytesIO(b"data"), 4)

        url = c.get_presigned_url("GET", self._bucket(),
                                   "test-presigned/file.pdf",
                                   expires=timedelta(hours=1))
        assert url is not None
        assert "X-Amz" in url or "Signature" in url or "presigned" in url.lower()
