"""Staging storage — persistent file storage for durable tasks.

Replaces ephemeral ``_file_path`` references with object IDs stored in a
configurable persistent directory (Docker volume in production).

Features:
- Object ID generation (SHA-256 content hash)
- Metadata tracking (size, MIME type, original name, creation time)
- Retrieval by object ID across restarts
- Disk quota enforcement
- Max age / orphan cleanup
- Startup temp file sweep
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import shutil
import stat
import time
from dataclasses import dataclass
from pathlib import Path

import importlib.util

from app.core.config import settings

logger = logging.getLogger("postgraduate-ai.staging")

# Resolve staging directory — fall back to a writable temp-adjacent path
_candidate = getattr(settings, "STAGING_STORAGE_DIR", "") or "/opt/2240ai-v2/staging"
_STAGING_DIR = Path(_candidate)
if not _STAGING_DIR.parent.exists():
    # Fall back to a directory inside the project root
    _STAGING_DIR = Path("/home/lmh/projects/postgraduate-ai/.staging")
_DEFAULT_QUOTA_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB
_DEFAULT_MAX_AGE_SEC = 86400 * 7  # 7 days
_CLEANUP_INTERVAL_SEC = 3600  # 1 hour
_METADATA_SUFFIX = ".meta.json"


@dataclass
class StagingObject:
    """Metadata for a staged file."""
    object_id: str
    sha256: str
    size: int
    mime: str
    original_name: str
    created_at: float
    staging_path: str


def _ensure_dir(path: Path) -> None:
    """Create directory with restricted permissions (0700)."""
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(stat.S_IRWXU)


def _staging_object_dir() -> Path:
    """Return the directory where staged files are stored."""
    d = _STAGING_DIR / "objects"
    _ensure_dir(d)
    return d


def _object_path(object_id: str) -> Path:
    """Return the file path for a staging object."""
    return _staging_object_dir() / f"{object_id}.data"


def _metadata_path(object_id: str) -> Path:
    """Return the metadata file path for a staging object."""
    return _staging_object_dir() / f"{object_id}{_METADATA_SUFFIX}"


def _sha256_of_file(path: str | Path) -> str:
    """Compute SHA-256 of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _disk_usage_bytes(path: Path) -> int:
    """Return total bytes used by staging objects."""
    total = 0
    if path.is_dir():
        for entry in path.iterdir():
            if entry.is_file() and entry.suffix == ".data":
                total += entry.stat().st_size
    return total


def _check_disk_quota(path: Path, additional_bytes: int = 0) -> None:
    """Raise if adding *additional_bytes* would exceed the disk quota."""
    quota = getattr(settings, "STAGING_DISK_QUOTA", _DEFAULT_QUOTA_BYTES)
    used = _disk_usage_bytes(path)
    if used + additional_bytes > quota:
        raise OSError(
            f"Staging disk quota exceeded: {used + additional_bytes} > {quota} bytes"
        )


def store_file(
    source_path: str | Path,
    original_name: str = "",
    mime: str = "application/octet-stream",
) -> StagingObject:
    """Copy a file into staging storage and return its object metadata.

    The object_id is based on SHA-256 of file content (content-addressed).
    If the same content already exists, returns the existing object.
    """
    sha256 = _sha256_of_file(source_path)
    object_id = f"stg_{sha256[:32]}"
    dest = _object_path(object_id)

    if dest.exists():
        # Already staged — return existing metadata
        return _load_metadata(object_id)

    src_size = os.path.getsize(source_path)
    _check_disk_quota(_staging_object_dir(), src_size)
    _ensure_dir(dest.parent)

    shutil.copy2(source_path, dest)
    dest.chmod(0o400)  # read-only after staging

    meta = {
        "object_id": object_id,
        "sha256": sha256,
        "size": src_size,
        "mime": mime,
        "original_name": original_name,
        "created_at": time.time(),
        "staging_path": str(dest),
    }
    _write_metadata(object_id, meta)
    logger.info(
        "Staged file: object_id=%s sha256=%s size=%d mime=%s",
        object_id, sha256[:16], src_size, mime,
    )
    return StagingObject(**meta)


def retrieve_file(object_id: str) -> str | None:
    """Return the local file path for a staging object, or None if not found.

    The returned path is a read-only file in the staging directory.
    The caller should copy it if they need write access.
    """
    dest = _object_path(object_id)
    if dest.exists():
        return str(dest)
    logger.warning("Staging object not found: object_id=%s", object_id)
    return None


def get_metadata(object_id: str) -> StagingObject | None:
    """Return metadata for a staging object, or None."""
    try:
        return _load_metadata(object_id)
    except (FileNotFoundError, ValueError):
        return None


def delete_object(object_id: str) -> bool:
    """Delete a staging object and its metadata. Returns True if deleted."""
    removed = False
    for p in (_object_path(object_id), _metadata_path(object_id)):
        if p.exists():
            p.unlink()
            removed = True
    if removed:
        logger.info("Deleted staging object: object_id=%s", object_id)
    return removed


def _load_metadata(object_id: str) -> StagingObject:
    """Load metadata from JSON file."""
    import json
    mp = _metadata_path(object_id)
    with open(mp, "r") as f:
        data = json.load(f)
    return StagingObject(**data)


def _write_metadata(object_id: str, data: dict) -> None:
    """Write metadata to JSON file atomically."""
    import json
    import tempfile
    mp = _metadata_path(object_id)
    tmp = mp.with_suffix(".meta.tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, ensure_ascii=False)
    tmp.replace(mp)
    mp.chmod(0o400)


def cleanup_orphans(max_age_sec: int | None = None) -> int:
    """Remove staging objects older than *max_age_sec*.

    Also removes .data files without matching .meta.json (orphans) and
    .meta.json files without matching .data files.

    Returns the number of objects removed.
    """
    age = max_age_sec or _DEFAULT_MAX_AGE_SEC
    cutoff = time.time() - age
    removed = 0
    obj_dir = _staging_object_dir()

    # Collect all object_ids from .data and .meta files
    data_ids: set[str] = set()
    meta_ids: set[str] = set()
    if obj_dir.is_dir():
        for entry in obj_dir.iterdir():
            if entry.suffix == ".data":
                data_ids.add(entry.stem)
            elif entry.name.endswith(_METADATA_SUFFIX):
                meta_ids.add(entry.stem)

    all_ids = data_ids | meta_ids
    for oid in sorted(all_ids):
        meta = get_metadata(oid)
        if meta and meta.created_at < cutoff:
            delete_object(oid)
            removed += 1
        elif meta is None:
            # Orphan — remove leftover files
            for p in (_object_path(oid), _metadata_path(oid)):
                if p.exists():
                    p.unlink()
                    removed += 1

    if removed:
        logger.info("Cleanup removed %d expired staging objects", removed)
    return removed


def sweep_temp_files() -> int:
    """Clean up legacy temp files from previous runs.

    Scans the staging directory and default temp locations for files
    older than 24 hours. Returns count of removed files.
    """
    removed = 0
    # Clean legacy temp files in staging root
    age = 86400  # 24 hours
    cutoff = time.time() - age

    if _STAGING_DIR.is_dir():
        for entry in _STAGING_DIR.iterdir():
            if entry.is_file() and entry.stat().st_mtime < cutoff:
                entry.unlink()
                removed += 1

    if removed:
        logger.info("Temp sweep removed %d stale files", removed)
    return removed


# ── Async wrappers (move sync I/O off the event loop) ──


async def async_store_file(
    source_path: str | Path,
    original_name: str = "",
    mime: str = "application/octet-stream",
) -> StagingObject:
    """Async wrapper for store_file — runs in executor to avoid blocking."""
    return await asyncio.to_thread(store_file, source_path, original_name, mime)


async def async_retrieve_file(object_id: str) -> str | None:
    """Async wrapper for retrieve_file."""
    return await asyncio.to_thread(retrieve_file, object_id)


async def async_delete_object(object_id: str) -> bool:
    """Async wrapper for delete_object."""
    return await asyncio.to_thread(delete_object, object_id)


async def async_cleanup_orphans(max_age_sec: int | None = None) -> int:
    """Async wrapper for cleanup_orphans."""
    return await asyncio.to_thread(cleanup_orphans, max_age_sec)


async def async_sweep_temp_files() -> int:
    """Async wrapper for sweep_temp_files."""
    return await asyncio.to_thread(sweep_temp_files)
