"""Staging storage unit tests — store, retrieve, delete, cleanup, lease, work copy."""
import os
import tempfile
import time

import pytest

from app.services.staging_storage import (
    _VALID_OBJECT_ID_RE_V2,
    _sha256_of_file,
    async_cleanup_work_copy,
    async_create_work_copy,
    cleanup_orphans,
    cleanup_work_copy,
    create_work_copy,
    decr_refcount,
    delete_object,
    extend_lease,
    get_metadata,
    get_refcount,
    incr_refcount,
    is_object_leased,
    lease_object,
    release_object,
    retrieve_file,
    set_object_retention,
    store_file,
    sweep_temp_files,
    validate_object_id,
)


class TestObjectIdFormat:
    """Full SHA-256 object ID format (4f)."""

    def test_v2_format_64_hex_chars(self):
        """New object IDs are 64 hex chars (full SHA-256)."""
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        tmp.write(b"hello staging")
        tmp.close()
        try:
            obj = store_file(tmp.name)
            assert obj.object_id.startswith("stg_")
            hex_part = obj.object_id[4:]
            assert len(hex_part) == 64, f"Expected 64 hex chars, got {len(hex_part)}"
            assert _VALID_OBJECT_ID_RE_V2.match(obj.object_id)
        finally:
            os.unlink(tmp.name)

    def test_validate_accepts_v1_legacy(self):
        """validate_object_id with allow_legacy=True accepts 32-char IDs."""
        validate_object_id("stg_" + "a" * 32, allow_legacy=True)

    def test_validate_accepts_v2(self):
        """validate_object_id accepts 64-char IDs."""
        validate_object_id("stg_" + "a" * 64)

    def test_validate_rejects_v1_when_disallowed(self):
        """validate_object_id with allow_legacy=False rejects 32-char IDs."""
        with pytest.raises(ValueError):
            validate_object_id("stg_" + "a" * 32, allow_legacy=False)

    def test_validate_rejects_invalid_chars(self):
        """validate_object_id rejects path traversal characters."""
        with pytest.raises(ValueError):
            validate_object_id("stg_../../etc/passwd")

    def test_validate_rejects_wrong_prefix(self):
        """validate_object_id rejects IDs without stg_ prefix."""
        with pytest.raises(ValueError):
            validate_object_id("abc_" + "a" * 64)

    def test_content_addressed_uses_full_sha256(self):
        """Same content produces same object_id (full SHA-256)."""
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
            hex_part = obj1.object_id[4:]
            assert len(hex_part) == 64
        finally:
            os.unlink(tmp1.name)
            os.unlink(tmp2.name)


class TestLeaseOwnerGeneration:
    """Lease with owner_token and generation (4a)."""

    OWNER = "proc_test123"
    OTHER_OWNER = "proc_other789"

    @pytest.fixture
    def staged_object(self):
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        tmp.write(b"lease test data")
        tmp.close()
        try:
            obj = store_file(tmp.name)
            yield obj
        finally:
            os.unlink(tmp.name)
            # Clean up any lease files
            try:
                from app.services.staging_storage import _lease_path
                lp = _lease_path(obj.object_id)
                if lp.exists():
                    lp.unlink()
            except Exception:
                pass

    def test_lease_with_owner_writes_metadata(self, staged_object):
        """lease_object with owner_token writes ownership metadata to lease file."""
        import json

        from app.services.staging_storage import _lease_path

        oid = staged_object.object_id
        lease_object(oid, owner_token=self.OWNER, generation=1, ttl_sec=3600)

        lp = _lease_path(oid)
        assert lp.exists()
        with open(lp) as f:
            data = json.load(f)
        assert data["owner_token"] == self.OWNER
        assert data["generation"] == 1
        assert data["ttl_sec"] == 3600
        assert "expires_at" in data

        release_object(oid)

    def test_lease_without_owner_no_metadata(self, staged_object):
        """lease_object without owner_token omits ownership fields."""
        import json

        from app.services.staging_storage import _lease_path

        oid = staged_object.object_id
        lease_object(oid, ttl_sec=3600)

        lp = _lease_path(oid)
        with open(lp) as f:
            data = json.load(f)
        assert "owner_token" not in data

        release_object(oid)

    def test_release_with_correct_owner_succeeds(self, staged_object):
        """release_object succeeds when owner_token matches."""
        oid = staged_object.object_id
        lease_object(oid, owner_token=self.OWNER, generation=1)
        assert release_object(oid, owner_token=self.OWNER, generation=1) is True
        assert is_object_leased(oid) is False

    def test_release_with_wrong_owner_fails(self, staged_object):
        """release_object fails when owner_token doesn't match."""
        oid = staged_object.object_id
        lease_object(oid, owner_token=self.OWNER, generation=1)
        assert release_object(oid, owner_token=self.OTHER_OWNER, generation=1) is False
        assert is_object_leased(oid) is True  # still leased

        # Cleanup with correct owner
        release_object(oid, owner_token=self.OWNER, generation=1)

    def test_release_with_wrong_generation_fails(self, staged_object):
        """release_object fails when generation doesn't match."""
        oid = staged_object.object_id
        lease_object(oid, owner_token=self.OWNER, generation=2)
        assert release_object(oid, owner_token=self.OWNER, generation=1) is False
        assert is_object_leased(oid) is True

        # Cleanup with correct generation
        release_object(oid, owner_token=self.OWNER, generation=2)

    def test_release_nonexistent_returns_false(self):
        """release_object returns False for nonexistent object."""
        assert release_object("stg_" + "a" * 64, owner_token=self.OWNER, generation=1) is False

    def test_release_without_owner_bypasses_check(self, staged_object):
        """release_object without owner_token bypasses ownership check (legacy compat)."""
        oid = staged_object.object_id
        lease_object(oid, ttl_sec=3600)  # no owner
        assert release_object(oid) is True  # legacy release, no owner check

    def test_extend_lease_with_correct_owner(self, staged_object):
        """extend_lease succeeds with matching owner_token."""
        oid = staged_object.object_id
        lease_object(oid, owner_token=self.OWNER, generation=1, ttl_sec=60)
        assert extend_lease(oid, owner_token=self.OWNER, generation=1, ttl_sec=3600) is True
        assert is_object_leased(oid) is True

        release_object(oid, owner_token=self.OWNER, generation=1)

    def test_extend_lease_with_wrong_owner_fails(self, staged_object):
        """extend_lease fails with mismatched owner_token."""
        oid = staged_object.object_id
        lease_object(oid, owner_token=self.OWNER, generation=1, ttl_sec=60)
        assert extend_lease(oid, owner_token=self.OTHER_OWNER, generation=1, ttl_sec=3600) is False

        # Lease still exists with original TTL
        release_object(oid, owner_token=self.OWNER, generation=1)

    def test_extend_lease_nonexistent_returns_false(self):
        """extend_lease returns False for nonexistent object."""
        assert extend_lease("stg_" + "a" * 64, owner_token=self.OWNER, generation=1) is False

    def test_lease_ttl_expiry(self, staged_object):
        """is_object_leased returns False after lease expires."""
        oid = staged_object.object_id
        lease_object(oid, owner_token=self.OWNER, generation=1, ttl_sec=1)
        assert is_object_leased(oid) is True
        time.sleep(1.1)
        assert is_object_leased(oid) is False

        # Cleanup
        release_object(oid, owner_token=self.OWNER, generation=1)

    def test_set_object_retention(self, staged_object):
        """set_object_retention adjusts lease TTL for terminal-state retention."""
        oid = staged_object.object_id
        lease_object(oid, owner_token=self.OWNER, generation=1, ttl_sec=3600)
        # Set shorter retention (e.g., after task success)
        assert set_object_retention(oid, ttl_sec=600, owner_token=self.OWNER, generation=1) is True

        # Verify TTL was updated by reading the lease file
        import json

        from app.services.staging_storage import _lease_path
        lp = _lease_path(oid)
        with open(lp) as f:
            data = json.load(f)
        assert data["ttl_sec"] == 600

        release_object(oid, owner_token=self.OWNER, generation=1)

    def test_lease_verify_detection_skip_leased_objects(self, staged_object):
        """is_object_leased returns True for actively leased objects."""
        oid = staged_object.object_id
        lease_object(oid, owner_token=self.OWNER, generation=1, ttl_sec=3600)
        assert is_object_leased(oid) is True
        release_object(oid, owner_token=self.OWNER, generation=1)

    def test_is_object_leased_no_lease(self, staged_object):
        """is_object_leased returns False when no lease file exists."""
        assert is_object_leased(staged_object.object_id) is False

    def test_is_object_leased_expired_legacy(self, staged_object):
        """is_object_leased falls back to mtime for legacy leases."""
        import json

        from app.services.staging_storage import _lease_path

        oid = staged_object.object_id
        lp = _lease_path(oid)
        # Write legacy lease (no expires_at field)
        with open(lp, "w") as f:
            json.dump({"ttl_sec": 3600}, f)

        assert is_object_leased(oid, max_lease_sec=3600) is True
        lp.unlink()


class TestWorkCopy:
    """Work copy for writable operations (4b)."""

    @pytest.fixture
    def staged_object(self):
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        tmp.write(b"work copy test data")
        tmp.close()
        try:
            obj = store_file(tmp.name)
            yield obj
        finally:
            os.unlink(tmp.name)
            delete_object(obj.object_id)

    def test_create_work_copy_content_matches(self, staged_object):
        """Work copy content matches the staging original."""
        oid = staged_object.object_id
        with tempfile.TemporaryDirectory() as scratch:
            work_path = create_work_copy(oid, scratch)
            assert work_path.exists()
            with open(work_path) as f:
                assert f.read() == "work copy test data"

    def test_work_copy_is_writable(self, staged_object):
        """Work copy can be written to (unlike staging original which is read-only)."""
        oid = staged_object.object_id
        with tempfile.TemporaryDirectory() as scratch:
            work_path = create_work_copy(oid, scratch)
            # Write to work copy
            with open(work_path, "w") as f:
                f.write("modified content")
            with open(work_path) as f:
                assert f.read() == "modified content"

    def test_work_copy_independent_from_staging(self, staged_object):
        """Modifying work copy does NOT affect staging original."""
        oid = staged_object.object_id
        with tempfile.TemporaryDirectory() as scratch:
            work_path = create_work_copy(oid, scratch)
            # Modify work copy
            with open(work_path, "w") as f:
                f.write("modified")

            # Staging original is unchanged
            original_path = retrieve_file(oid)
            assert original_path is not None
            with open(original_path) as f:
                assert f.read() == "work copy test data"

    def test_cleanup_work_copy(self, staged_object):
        """cleanup_work_copy removes the work copy file."""
        oid = staged_object.object_id
        with tempfile.TemporaryDirectory() as scratch:
            work_path = create_work_copy(oid, scratch)
            assert work_path.exists()
            cleanup_work_copy(work_path)
            assert not work_path.exists()

    def test_cleanup_work_copy_nonexistent(self):
        """cleanup_work_copy does not raise for nonexistent paths."""
        cleanup_work_copy("/nonexistent/work/copy.tmp")  # should not raise

    def test_create_work_copy_nonexistent_raises(self):
        """create_work_copy raises FileNotFoundError for nonexistent staging object."""
        with tempfile.TemporaryDirectory() as scratch:
            with pytest.raises(FileNotFoundError):
                create_work_copy("stg_" + "a" * 64, scratch)

    def test_async_create_and_cleanup(self, staged_object):
        """Async work copy wrappers work correctly."""
        import asyncio

        oid = staged_object.object_id
        async def _run():
            with tempfile.TemporaryDirectory() as scratch:
                wp = await async_create_work_copy(oid, scratch)
                assert wp.exists()
                await async_cleanup_work_copy(str(wp))
                assert not wp.exists()

        asyncio.run(_run())


class TestRefcount:
    """Refcount for content-addressed objects (4d)."""

    def test_incr_refcount(self):
        """incr_refcount returns the new count."""
        oid = "stg_" + "a" * 64
        try:
            assert incr_refcount(oid) == 1
            assert incr_refcount(oid) == 2
        finally:
            # Cleanup in-memory state
            from app.services.staging_storage import _REFCOUNT_STORE
            _REFCOUNT_STORE.pop(oid, None)

    def test_decr_refcount(self):
        """decr_refcount decrements and returns new count."""
        oid = "stg_" + "b" * 64
        try:
            incr_refcount(oid)
            incr_refcount(oid)
            incr_refcount(oid)
            assert decr_refcount(oid) == 2
            assert decr_refcount(oid) == 1
            assert decr_refcount(oid) == 0
            assert decr_refcount(oid) == 0  # doesn't go negative
        finally:
            from app.services.staging_storage import _REFCOUNT_STORE
            _REFCOUNT_STORE.pop(oid, None)

    def test_get_refcount(self):
        """get_refcount returns current count."""
        oid = "stg_" + "c" * 64
        try:
            assert get_refcount(oid) == 0
            incr_refcount(oid)
            assert get_refcount(oid) == 1
        finally:
            from app.services.staging_storage import _REFCOUNT_STORE
            _REFCOUNT_STORE.pop(oid, None)

    def test_decr_removes_from_store_when_zero(self, staged_object):
        """decr_refcount removes entry when count reaches 0."""
        from app.services.staging_storage import _REFCOUNT_STORE

        oid = "stg_" + "d" * 64
        incr_refcount(oid)
        decr_refcount(oid)
        assert oid not in _REFCOUNT_STORE

    @pytest.fixture
    def staged_object(self):
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        tmp.write(b"refcount test")
        tmp.close()
        try:
            obj = store_file(tmp.name)
            yield obj
        finally:
            os.unlink(tmp.name)
            delete_object(obj.object_id)


class TestAtomicWrites:
    """Atomic staging writes (4e)."""

    def test_store_file_atomic_write(self):
        """store_file creates .data file (not .data.tmp) on success."""
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        tmp.write(b"atomic write test")
        tmp.close()
        try:
            obj = store_file(tmp.name)
            # Data file exists (not .tmp)
            from app.services.staging_storage import _object_path
            dp = _object_path(obj.object_id)
            assert dp.exists()
            assert not dp.with_suffix(".data.tmp").exists()
        finally:
            os.unlink(tmp.name)
            delete_object(obj.object_id)

    def test_cleanup_orphans_removes_stale_tmp(self):
        """cleanup_orphans removes stale .data.tmp files from crashes."""
        from app.services.staging_storage import _staging_object_dir

        obj_dir = _staging_object_dir()
        stale_tmp = obj_dir / "stg_0000000000000000000000000000000000000000000000000000000000000000.data.tmp"
        try:
            stale_tmp.write_text("stale data")
            removed = cleanup_orphans(max_age_sec=-1)
            assert removed >= 1
            assert not stale_tmp.exists()
        finally:
            if stale_tmp.exists():
                stale_tmp.unlink()

    def test_store_and_retrieve_content(self):
        """Core store/retrieve still works correctly after atomic write changes."""
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        tmp.write(b"hello staging")
        tmp.close()
        try:
            obj = store_file(tmp.name)
            path = retrieve_file(obj.object_id)
            assert path is not None
            with open(path) as f:
                assert f.read() == "hello staging"
        finally:
            # Compute v1 key before temp file deletion
            v1_key = "stg_" + _sha256_of_file(tmp.name)[:32]
            os.unlink(tmp.name)
            delete_object(obj.object_id)
            # Clean up v1 legacy key if it exists
            from app.services.staging_storage import _object_path as op
            old_path = op(v1_key)
            if old_path.exists():
                old_path.unlink()


class TestStagingStorage:
    """Core staging operations (existing tests, updated for v2)."""

    def test_store_and_retrieve(self):
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        tmp.write(b"hello staging")
        tmp.close()
        try:
            obj = store_file(tmp.name, original_name="test.txt", mime="text/plain")
            assert obj.object_id
            assert obj.object_id.startswith("stg_")
            assert len(obj.object_id) == 4 + 64  # stg_ + 64 hex chars
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
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        tmp.write(b"delete me")
        tmp.close()
        try:
            obj = store_file(tmp.name)
            assert retrieve_file(obj.object_id) is not None
            assert delete_object(obj.object_id) is True
            assert retrieve_file(obj.object_id) is None
            assert delete_object(obj.object_id) is False
        finally:
            os.unlink(tmp.name)

    def test_get_metadata(self):
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

            assert get_metadata("nonexistent") is None
        finally:
            os.unlink(tmp.name)

    def test_content_addressed_dedup(self):
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
            # Full SHA-256, not truncated
            assert len(obj1.object_id) == 4 + 64
        finally:
            os.unlink(tmp1.name)
            os.unlink(tmp2.name)

    def test_sha256_of_file(self):
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        tmp.write(b"hello")
        tmp.close()
        try:
            h = _sha256_of_file(tmp.name)
            assert h == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
        finally:
            os.unlink(tmp.name)


class TestStagingCleanup:
    """Cleanup and sweep operations (updated for refcount)."""

    def test_cleanup_orphans_removes_expired(self):
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        tmp.write(b"old data")
        tmp.close()
        try:
            obj = store_file(tmp.name)
            deleted = cleanup_orphans(max_age_sec=-1)
            assert deleted >= 1
            assert retrieve_file(obj.object_id) is None
        finally:
            os.unlink(tmp.name)

    def test_cleanup_preserves_recent(self):
        # Clean staging dir to avoid state leakage from previous tests
        self._clean_staging_dir()
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        tmp.write(b"recent data")
        tmp.close()
        try:
            obj = store_file(tmp.name)
            deleted = cleanup_orphans(max_age_sec=86400 * 30)
            # Recent objects should not be deleted (but may be 0 if no orphans)
            if deleted > 0:
                # Only allow pre-existing orphans, not our object
                assert retrieve_file(obj.object_id) is not None
            assert retrieve_file(obj.object_id) is not None
        finally:
            os.unlink(tmp.name)

    def _clean_staging_dir(self):
        """Remove all files from staging objects dir for test isolation."""
        from app.services.staging_storage import _staging_object_dir
        d = _staging_object_dir()
        if d.is_dir():
            for entry in list(d.iterdir()):
                try:
                    entry.unlink()
                except OSError:
                    pass

    def test_cleanup_skips_leased(self):
        """cleanup_orphans skips objects with active leases."""
        self._clean_staging_dir()
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        tmp.write(b"leased data")
        tmp.close()
        try:
            obj = store_file(tmp.name)
            lease_object(obj.object_id, owner_token="test_owner", generation=1, ttl_sec=3600)
            cleanup_orphans(max_age_sec=-1)
            # Leased object must still exist
            assert retrieve_file(obj.object_id) is not None
            release_object(obj.object_id, owner_token="test_owner", generation=1)
        finally:
            os.unlink(tmp.name)

    def test_cleanup_skips_refcounted(self):
        """cleanup_orphans skips objects with refcount > 0."""
        self._clean_staging_dir()
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        tmp.write(b"refcounted data")
        tmp.close()
        try:
            obj = store_file(tmp.name)
            oid = obj.object_id
            incr_refcount(oid)
            try:
                cleanup_orphans(max_age_sec=-1)
                # Refcounted object must still exist
                assert retrieve_file(oid) is not None
            finally:
                decr_refcount(oid)
        finally:
            os.unlink(tmp.name)

    def test_sweep_temp_files(self):
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".tmp")
        tmp.write(b"stale temp")
        tmp.close()
        try:
            swept = sweep_temp_files()
            assert isinstance(swept, int)
            assert swept >= 0
        finally:
            os.unlink(tmp.name)


class TestStagingEdgeCases:
    """Edge cases and error handling."""

    def test_store_nonexistent_file(self):
        with pytest.raises(FileNotFoundError):
            store_file("/nonexistent/path/file.txt")

    def test_retrieve_nonexistent_id(self):
        assert retrieve_file("stg_" + "0" * 64) is None

    def test_retrieve_v1_legacy_id(self):
        """retrieve_file accepts v1 32-char IDs (backward compat)."""
        assert retrieve_file("stg_" + "0" * 32) is None  # doesn't exist but doesn't raise

    def test_delete_nonexistent_id(self):
        assert delete_object("stg_" + "0" * 64) is False
