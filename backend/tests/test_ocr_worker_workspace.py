"""OCR Worker workspace tests — no Paddle/GPU required."""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from app.ocr_worker.workspace import JobWorkspace, WorkspaceError


@pytest.fixture
def tmp_root():
    with tempfile.TemporaryDirectory() as d:
        yield d


class TestJobWorkspace:
    """Test workspace lifecycle and manifest management."""

    def test_create_workspace(self, tmp_root):
        ws = JobWorkspace(tmp_root, "job-001")
        import asyncio
        asyncio.run(ws.create())

        assert ws.base.exists()
        assert ws.input_dir.exists()
        assert ws.pages_dir.exists()
        assert ws.artifacts_dir.exists()
        assert ws.result_dir.exists()
        assert ws.logs_dir.exists()

    def test_manifest_write_and_read(self, tmp_root):
        ws = JobWorkspace(tmp_root, "job-002")
        import asyncio
        asyncio.run(ws.create())

        manifest = {
            "job_id": "job-002",
            "status": "running",
            "completed_pages": [0, 1, 2],
        }
        ws.write_manifest(manifest)

        loaded = ws.read_manifest()
        assert loaded is not None
        assert loaded["job_id"] == "job-002"
        assert loaded["status"] == "running"
        assert loaded["completed_pages"] == [0, 1, 2]

    def test_update_manifest(self, tmp_root):
        ws = JobWorkspace(tmp_root, "job-003")
        import asyncio
        asyncio.run(ws.create())

        ws.write_manifest({"job_id": "job-003", "status": "pending"})
        ws.update_manifest(status="leased")

        loaded = ws.read_manifest()
        assert loaded["status"] == "leased"

    def test_completed_pages(self, tmp_root):
        ws = JobWorkspace(tmp_root, "job-004")
        import asyncio
        asyncio.run(ws.create())

        ws.write_manifest({"job_id": "job-004", "status": "running", "completed_pages": []})

        assert ws.completed_pages() == set()
        ws.mark_page_completed(0)
        assert ws.completed_pages() == {0}
        ws.mark_page_completed(1)
        assert ws.completed_pages() == {0, 1}

    def test_manifest_not_found(self, tmp_root):
        ws = JobWorkspace(tmp_root, "nonexistent")
        assert ws.read_manifest() is None
        assert ws.completed_pages() == set()

    def test_disk_usage(self, tmp_root):
        ws = JobWorkspace(tmp_root, "job-005")
        import asyncio
        asyncio.run(ws.create())

        # Write a test file
        ws.input_dir.joinpath("test.bin").write_bytes(b"x" * 1024)
        usage = ws.disk_usage_bytes()
        assert usage >= 1024

    def test_total_disk_usage(self, tmp_root):
        ws1 = JobWorkspace(tmp_root, "job-a")
        ws2 = JobWorkspace(tmp_root, "job-b")
        import asyncio
        asyncio.run(ws1.create())
        asyncio.run(ws2.create())

        ws1.input_dir.joinpath("f1.bin").write_bytes(b"x" * 512)
        ws2.input_dir.joinpath("f2.bin").write_bytes(b"x" * 256)

        total = JobWorkspace.total_disk_usage(tmp_root)
        assert total >= 768

    def test_list_incomplete(self, tmp_root):
        ws_done = JobWorkspace(tmp_root, "done-job")
        ws_pending = JobWorkspace(tmp_root, "pending-job")
        import asyncio
        asyncio.run(ws_done.create())
        asyncio.run(ws_pending.create())

        ws_done.write_manifest({"job_id": "done-job", "status": "completed"})
        ws_pending.write_manifest({"job_id": "pending-job", "status": "running"})

        incomplete = JobWorkspace.list_incomplete(tmp_root)
        ids = [m["job_id"] for m in incomplete]
        assert "pending-job" in ids
        assert "done-job" not in ids

    def test_cleanup_removes_workspace(self, tmp_root):
        ws = JobWorkspace(tmp_root, "job-cleanup")
        import asyncio
        asyncio.run(ws.create())
        assert ws.base.exists()

        asyncio.run(ws.cleanup())
        assert not ws.base.exists()

    def test_page_image_path(self, tmp_root):
        ws = JobWorkspace(tmp_root, "job-img")
        p = ws.page_image_path(0)
        assert "page_0000.png" in str(p)
        p2 = ws.page_image_path(42)
        assert "page_0042.png" in str(p2)

    def test_workspace_error_on_bad_path(self):
        ws = JobWorkspace("/nonexistent/parent", "bad-job")
        with pytest.raises(WorkspaceError):
            import asyncio
            asyncio.run(ws.create())
