"""OCR Worker workspace — per-job directory management for isolation and resume.

Each job gets an isolated workspace:
  {WORKSPACE_ROOT}/jobs/{job_id}/
    input/          — downloaded input file (PDF, image)
    pages/          — rendered page images
    artifacts/      — intermediate artifacts
    result/         — final ModuleResult[DocumentIR]
    logs/           — per-job logs
    manifest.json   — job state manifest for resume
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class WorkspaceError(Exception):
    """Raised on workspace operations failure."""


class JobWorkspace:
    """Manages a single job's workspace directory."""

    def __init__(self, root: str, job_id: str) -> None:
        self._root = Path(root)
        self._job_id = job_id
        self._base = self._root / "jobs" / job_id

    @property
    def base(self) -> Path:
        return self._base

    @property
    def input_dir(self) -> Path:
        return self._base / "input"

    @property
    def pages_dir(self) -> Path:
        return self._base / "pages"

    @property
    def artifacts_dir(self) -> Path:
        return self._base / "artifacts"

    @property
    def result_dir(self) -> Path:
        return self._base / "result"

    @property
    def logs_dir(self) -> Path:
        return self._base / "logs"

    @property
    def manifest_path(self) -> Path:
        return self._base / "manifest.json"

    @property
    def input_path(self) -> Path:
        return self.input_dir / "input.bin"

    @property
    def result_path(self) -> Path:
        return self.result_dir / "document.ir.json"

    # ── Lifecycle ────────────────────────────────────────

    async def create(self) -> None:
        """Create the workspace directory structure."""
        try:
            self._base.mkdir(parents=True, exist_ok=True)
            self.input_dir.mkdir(exist_ok=True)
            self.pages_dir.mkdir(exist_ok=True)
            self.artifacts_dir.mkdir(exist_ok=True)
            self.result_dir.mkdir(exist_ok=True)
            self.logs_dir.mkdir(exist_ok=True)
        except OSError as e:
            raise WorkspaceError(f"Failed to create workspace for {self._job_id}: {e}") from e

    async def cleanup(self) -> None:
        """Remove the entire workspace directory."""
        if self._base.exists():
            shutil.rmtree(self._base, ignore_errors=True)

    async def exists(self) -> bool:
        """Check if workspace exists (has manifest)."""
        return self.manifest_path.exists()

    # ── Manifest ─────────────────────────────────────────

    def read_manifest(self) -> dict[str, Any] | None:
        """Read the job manifest. Returns None if not found."""
        if not self.manifest_path.exists():
            return None
        try:
            return json.loads(self.manifest_path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def write_manifest(self, data: dict[str, Any]) -> None:
        """Write the job manifest atomically via temporary file."""
        tmp = self.manifest_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, default=str))
        tmp.rename(self.manifest_path)

    def update_manifest(self, **fields: Any) -> dict[str, Any]:
        """Update specific manifest fields and return the full manifest."""
        manifest = self.read_manifest() or {}
        manifest.update(fields)
        manifest["updated_at"] = datetime.now(UTC).isoformat()
        self.write_manifest(manifest)
        return manifest

    # ── Page tracking ────────────────────────────────────

    def completed_pages(self) -> set[int]:
        """Return set of page indices that have been OCR'd."""
        manifest = self.read_manifest()
        if manifest is None:
            return set()
        return set(manifest.get("completed_pages", []))

    def mark_page_completed(self, page_index: int) -> None:
        """Mark a page as completed in the manifest."""
        manifest = self.read_manifest() or {}
        completed = set(manifest.get("completed_pages", []))
        completed.add(page_index)
        self.update_manifest(completed_pages=sorted(completed))

    def page_image_path(self, page_index: int) -> Path:
        """Path to a rendered page image."""
        return self.pages_dir / f"page_{page_index:04d}.png"

    # ── Stats ────────────────────────────────────────────

    def disk_usage_bytes(self) -> int:
        """Return total disk usage for this workspace in bytes."""
        total = 0
        for dirpath, dirnames, filenames in os.walk(self._base):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
        return total

    @staticmethod
    def total_disk_usage(root: str) -> int:
        """Return total disk usage across all job workspaces."""
        jobs_dir = Path(root) / "jobs"
        if not jobs_dir.exists():
            return 0
        total = 0
        for job_dir in jobs_dir.iterdir():
            if job_dir.is_dir():
                for dirpath, dirnames, filenames in os.walk(job_dir):
                    for f in filenames:
                        try:
                            total += (Path(dirpath) / f).stat().st_size
                        except OSError:
                            pass
        return total

    @staticmethod
    def list_incomplete(root: str) -> list[dict[str, Any]]:
        """Scan all workspaces and return incomplete (non-completed) jobs for resume."""
        jobs_dir = Path(root) / "jobs"
        if not jobs_dir.exists():
            return []
        incomplete: list[dict[str, Any]] = []
        for job_dir in jobs_dir.iterdir():
            if not job_dir.is_dir():
                continue
            manifest_path = job_dir / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                manifest = json.loads(manifest_path.read_text())
                if manifest.get("status") in ("running", "downloading", "uploading", "leased"):
                    incomplete.append(manifest)
            except (json.JSONDecodeError, OSError):
                pass
        return incomplete
