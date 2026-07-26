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
import re
import shutil
import stat
import time
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile

logger = logging.getLogger("postgraduate-ai.staging")

# Resolve staging directory — use STAGING_STORAGE_DIR from settings or a sensible default.
# In production/cloud_api, the staging directory must be explicitly configured and writable.
_candidate = getattr(settings, "STAGING_STORAGE_DIR", "") or "/opt/2240ai-v2/staging"
_STAGING_DIR = Path(_candidate)

# In restricted environments, fail if the staging directory parent doesn't exist
_profile = detect_deployment_profile()
_is_production = _profile == DeploymentProfile.CLOUD_API or settings.APP_ENV == "production"
if _is_production and not _STAGING_DIR.parent.exists():
    raise RuntimeError(
        f"Staging directory parent does not exist: {_STAGING_DIR}. "
        "Set STAGING_STORAGE_DIR to an existing path."
    )
elif not _STAGING_DIR.parent.exists():
    # Development fallback — use a project-relative path
    _STAGING_DIR = Path.cwd() / ".staging"
    logger.warning(
        "STAGING_STORAGE_DIR parent does not exist, using fallback: %s",
        _STAGING_DIR,
    )
_DEFAULT_QUOTA_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB
_DEFAULT_MAX_AGE_SEC = 86400 * 7  # 7 days
_CLEANUP_INTERVAL_SEC = 3600  # 1 hour
_METADATA_SUFFIX = ".meta.json"
_LEASE_SUFFIX = ".lease"

# Default lease TTL for objects referenced by active tasks
_DEFAULT_LEASE_SEC = 86400 * 7  # 7 days — covers terminal retention

# Object ID format whitelist — prevents path traversal and injection attacks.
# New (v2) format: "stg_" followed by exactly 64 lowercase hex characters (full SHA-256).
# Legacy (v1) format: "stg_" followed by exactly 32 lowercase hex characters.
_VALID_OBJECT_ID_RE_V1 = re.compile(r"^stg_[a-f0-9]{32}$")
_VALID_OBJECT_ID_RE_V2 = re.compile(r"^stg_[a-f0-9]{64}$")


def validate_object_id(object_id: str, allow_legacy: bool = True) -> None:
    """Validate object_id format. Raises ValueError on invalid format.

    Accepts both v1 (32 hex chars) and v2 (64 hex chars, full SHA-256) formats
    when *allow_legacy* is True (default). New writes always use 64 hex chars.

    Rejects any path traversal characters (/, ., \\, etc.).
    """
    if _VALID_OBJECT_ID_RE_V2.match(object_id):
        return
    if allow_legacy and _VALID_OBJECT_ID_RE_V1.match(object_id):
        return
    raise ValueError(
        f"Invalid staging object_id format: {object_id!r}. "
        "Must match 'stg_' + 64 hex characters (v2) or 32 hex characters (v1 legacy)."
    )


def _lease_path(object_id: str) -> Path:
    """Return the lease marker file path for a staging object."""
    return _staging_object_dir() / f"{object_id}{_LEASE_SUFFIX}"


def lease_object(
    object_id: str,
    owner_token: str = "",
    generation: int = 0,
    ttl_sec: int = _DEFAULT_LEASE_SEC,
) -> None:
    """Mark a staging object as in-use (leased) by an active task.

    The lease is tied to a specific task attempt via *owner_token* and
    *generation*. Only the owning worker can release or extend the lease.

    The cleanup function will skip leased objects even if they are past
    the default max age.

    Creates a lease file with an absolute expires_at timestamp and
    ownership metadata (JSON), which is more robust than mtime-based
    expiry — the lease is preserved across filesystem operations and
    clock drift is bounded to the worker's own clock.

    When *owner_token* is empty (legacy callers), ownership verification
    is skipped and any worker can release the lease.
    """
    import json

    validate_object_id(object_id)
    lp = _lease_path(object_id)
    _ensure_dir(lp.parent)
    expires_at = time.time() + ttl_sec
    data: dict = {
        "expires_at": expires_at,
        "ttl_sec": ttl_sec,
    }
    if owner_token:
        data["owner_token"] = owner_token
        data["generation"] = generation
    tmp = lp.with_suffix(".lease.tmp")
    with open(tmp, "w") as f:
        json.dump(data, f)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(lp)


def release_object(object_id: str, owner_token: str = "", generation: int = 0) -> bool:
    """Remove the lease marker for a staging object.

    Only succeeds if *owner_token* and *generation* match the lease data
    (when ownership info is present). When the lease has no owner_token
    (legacy), any caller can release it.

    Returns True if the lease was removed, False if it wasn't found or
    ownership verification failed.
    """
    import json

    validate_object_id(object_id)
    lp = _lease_path(object_id)
    if not lp.exists():
        return False

    if owner_token:
        try:
            with open(lp) as f:
                data = json.load(f)
            stored_owner = data.get("owner_token", "")
            if stored_owner and stored_owner != owner_token:
                logger.warning(
                    "Lease owner mismatch for %s (expected=%s, got=%s)",
                    object_id, stored_owner, owner_token,
                )
                return False
            stored_gen = data.get("generation", -1)
            if stored_owner and stored_gen != -1 and stored_gen != generation:
                logger.warning(
                    "Lease generation mismatch for %s (expected=%d, got=%d)",
                    object_id, stored_gen, generation,
                )
                return False
        except (json.JSONDecodeError, OSError):
            pass  # Legacy lease without owner info — proceed

    try:
        lp.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def extend_lease(
    object_id: str,
    owner_token: str = "",
    generation: int = 0,
    ttl_sec: int = _DEFAULT_LEASE_SEC,
) -> bool:
    """Extend the lease on a staging object.

    Only succeeds if *owner_token* matches the lease data (when ownership
    info is present). Returns True on success, False if the lease doesn't
    exist or ownership verification failed.
    """
    import json

    validate_object_id(object_id)
    lp = _lease_path(object_id)
    if not lp.exists():
        return False

    if owner_token:
        try:
            with open(lp) as f:
                data = json.load(f)
            stored_owner = data.get("owner_token", "")
            if stored_owner and stored_owner != owner_token:
                logger.warning(
                    "Extend lease owner mismatch for %s (expected=%s, got=%s)",
                    object_id, stored_owner, owner_token,
                )
                return False
        except (json.JSONDecodeError, OSError):
            return False

    # Re-write lease with new TTL (preserving existing fields)
    lease_object(object_id, owner_token=owner_token, generation=generation, ttl_sec=ttl_sec)
    return True


def create_work_copy(object_id: str, scratch_dir: str | Path) -> Path:
    """Create a writable copy of a staging object in the scratch directory.

    Attempts a hard link first (same filesystem, zero-copy), falling back
    to a file copy. The returned path is the work copy — the caller may
    read, modify, or delete it. The staging original is NEVER modified.

    Raises FileNotFoundError if the staging object does not exist.
    """
    validate_object_id(object_id)
    src = _object_path(object_id)
    if not src.exists():
        raise FileNotFoundError(f"Staging object {object_id} not found at {src}")

    _ensure_dir(Path(scratch_dir))
    work_path = Path(scratch_dir) / f"{object_id}.work"

    # Copy file data without preserving permissions (staging original is 0o400 read-only).
    # The work copy gets default write permissions so the pipeline can modify it.
    shutil.copyfile(str(src), str(work_path))

    return work_path


def cleanup_work_copy(work_path: str | Path) -> None:
    """Remove a work copy file created by create_work_copy.

    Safe to call even if the file doesn't exist or has already been
    deleted by the pipeline. Does NOT touch the staging original.
    """
    try:
        Path(work_path).unlink(missing_ok=True)
    except OSError as e:
        logger.warning("Failed to cleanup work copy %s: %s", work_path, e)


def set_object_retention(object_id: str, ttl_sec: int, owner_token: str = "", generation: int = 0) -> bool:
    """Adjust the lease TTL for a staging object based on terminal state.

    Called after a task reaches a terminal state (success, fail, dead,
    cancel) to set the appropriate retention period. The object remains
    leased (protected from cleanup) for *ttl_sec* more seconds, after
    which cleanup_orphans may remove it.

    Returns True if the retention was set, False if the object has no
    lease or ownership verification failed.
    """
    return extend_lease(object_id, owner_token=owner_token, generation=generation, ttl_sec=ttl_sec)


# ── Refcount for content-addressed staging objects ──

_REFCOUNT_STORE: dict[str, int] = {}
"""In-memory refcount fallback when Redis is unavailable.

Used only in development/local environments.
"""


def _refcount_key(object_id: str) -> str:
    return f"staging:v2:refcount:{object_id}"


def incr_refcount(object_id: str) -> int:
    """Increment the reference count for a content-addressed staging object.

    Content-addressed objects (same SHA-256 = same object_id) may be
    referenced by multiple tasks. The refcount ensures the object is not
    deleted until all referencing tasks have completed and their leases
    have expired.

    Returns the new count.
    """
    try:
        from app.core.redis_client import redis_client
        if redis_client:
            key = _refcount_key(object_id)
            val = redis_client.incr(key)
            return val
    except Exception:
        pass
    count = _REFCOUNT_STORE.get(object_id, 0) + 1
    _REFCOUNT_STORE[object_id] = count
    return count


def decr_refcount(object_id: str) -> int:
    """Decrement the reference count. Returns new count (0 = no more references)."""
    try:
        from app.core.redis_client import redis_client
        if redis_client:
            key = _refcount_key(object_id)
            val = redis_client.decr(key)
            if val <= 0:
                redis_client.delete(key)
            return max(0, val)
    except Exception:
        pass
    count = _REFCOUNT_STORE.get(object_id, 0) - 1
    if count <= 0:
        _REFCOUNT_STORE.pop(object_id, None)
    else:
        _REFCOUNT_STORE[object_id] = count
    return max(0, count)


def get_refcount(object_id: str) -> int:
    """Return the current reference count (0 if unknown)."""
    try:
        from app.core.redis_client import redis_client
        if redis_client:
            key = _refcount_key(object_id)
            val = redis_client.get(key)
            return int(val) if val else 0
    except Exception:
        pass
    return _REFCOUNT_STORE.get(object_id, 0)


def is_object_leased(object_id: str, max_lease_sec: int = _DEFAULT_LEASE_SEC) -> bool:
    """Check if a staging object has an active lease.

    Reads the ``expires_at`` timestamp from the lease file (JSON).
    Falls back to mtime-based check for legacy lease files that were
    written before the expires_at JSON format was introduced.
    """
    import json

    lp = _lease_path(object_id)
    if not lp.exists():
        return False
    try:
        with open(lp) as f:
            data = json.load(f)
        expires_at = data.get("expires_at")
        if expires_at is not None:
            return time.time() < expires_at
    except (json.JSONDecodeError, OSError, ValueError):
        pass

    # Legacy fallback: mtime-based check
    try:
        age = time.time() - lp.stat().st_mtime
        return age < max_lease_sec
    except OSError:
        return False


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

    The object_id is the full SHA-256 hex digest of file content
    (content-addressed). If the same content already exists, returns the
    existing object.

    Writes are atomic: the data file is written to ``.data.tmp``, fsynced,
    then renamed to ``.data``. A crash between data and metadata writes
    produces a detectable orphan (``.data`` without ``.meta.json``), which
    ``cleanup_orphans`` removes after a grace period.
    """
    sha256 = _sha256_of_file(source_path)
    object_id = f"stg_{sha256}"
    dest = _object_path(object_id)

    if dest.exists():
        return _load_metadata(object_id)

    src_size = os.path.getsize(source_path)
    _check_disk_quota(_staging_object_dir(), src_size)
    _ensure_dir(dest.parent)

    # Atomic write: .data.tmp → fsync → rename
    tmp_dest = dest.with_suffix(".data.tmp")
    with open(source_path, "rb") as src_f:
        with open(tmp_dest, "wb") as dst_f:
            import shutil
            shutil.copyfileobj(src_f, dst_f)
            dst_f.flush()
            os.fsync(dst_f.fileno())
    tmp_dest.chmod(0o400)
    tmp_dest.replace(dest)

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
    validate_object_id(object_id)
    dest = _object_path(object_id)
    if dest.exists():
        return str(dest)
    logger.warning("Staging object not found: object_id=%s", object_id)
    return None


def get_metadata(object_id: str) -> StagingObject | None:
    """Return metadata for a staging object, or None."""
    try:
        validate_object_id(object_id)
        return _load_metadata(object_id)
    except (FileNotFoundError, ValueError):
        return None


def delete_object(object_id: str) -> bool:
    """Delete a staging object and its metadata. Returns True if deleted."""
    validate_object_id(object_id)
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
    with open(mp) as f:
        data = json.load(f)
    return StagingObject(**data)


def _write_metadata(object_id: str, data: dict) -> None:
    """Write metadata to JSON file atomically.

    Atomic write via temp file + fsync + rename. This ensures that a
    crash during write leaves either the old metadata or the complete
    new metadata, never a partial/corrupt file.
    """
    import json
    mp = _metadata_path(object_id)
    tmp = mp.with_suffix(".meta.tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(mp)
    mp.chmod(0o400)


def cleanup_orphans(max_age_sec: int | None = None) -> int:
    """Remove staging objects older than *max_age_sec*.

    Removes:
    - Expired objects (created_at < cutoff) that are not leased and have no refcount
    - Orphan ``.data`` files without matching ``.meta.json`` (crash during atomic write)
    - Orphan ``.meta.json`` files without matching ``.data``
    - Stale ``.data.tmp`` / ``.meta.tmp`` files (crash during atomic write)

    Objects that are currently leased OR have a refcount > 0 are SKIPPED.
    This prevents cleanup from deleting data still needed by queued,
    processing, or retry tasks, or shared by multiple tasks.

    Returns the number of objects removed.
    """
    age = max_age_sec or _DEFAULT_MAX_AGE_SEC
    cutoff = time.time() - age
    removed = 0
    obj_dir = _staging_object_dir()

    # Clean stale .tmp files from crashed atomic writes
    if obj_dir.is_dir():
        for entry in list(obj_dir.iterdir()):
            if entry.suffix in (".tmp", ".tmp") and "tmp" in entry.name:
                try:
                    entry.unlink()
                    removed += 1
                except OSError:
                    pass

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
        # Skip objects that are leased or still referenced
        if is_object_leased(oid):
            continue
        if get_refcount(oid) > 0:
            continue

        meta = get_metadata(oid)
        if meta and meta.created_at < cutoff:
            delete_object(oid)
            removed += 1
        elif meta is None:
            # Orphan — remove leftover files (data without meta or vice versa)
            for p in (_object_path(oid), _metadata_path(oid)):
                if p.exists():
                    p.unlink()
                    removed += 1

    if removed:
        logger.info("Cleanup removed %d expired/orphaned staging objects", removed)
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


async def async_lease_object(
    object_id: str,
    owner_token: str = "",
    generation: int = 0,
    ttl_sec: int = _DEFAULT_LEASE_SEC,
) -> None:
    """Async wrapper for lease_object."""
    return await asyncio.to_thread(lease_object, object_id, owner_token, generation, ttl_sec)


async def async_extend_lease(
    object_id: str,
    owner_token: str = "",
    generation: int = 0,
    ttl_sec: int = _DEFAULT_LEASE_SEC,
) -> bool:
    """Async wrapper for extend_lease."""
    return await asyncio.to_thread(extend_lease, object_id, owner_token, generation, ttl_sec)


async def async_release_object(
    object_id: str,
    owner_token: str = "",
    generation: int = 0,
) -> bool:
    """Async wrapper for release_object."""
    return await asyncio.to_thread(release_object, object_id, owner_token, generation)


async def async_create_work_copy(object_id: str, scratch_dir: str | Path) -> Path:
    """Async wrapper for create_work_copy."""
    return await asyncio.to_thread(create_work_copy, object_id, scratch_dir)


async def async_cleanup_work_copy(work_path: str | Path) -> None:
    """Async wrapper for cleanup_work_copy."""
    return await asyncio.to_thread(cleanup_work_copy, work_path)


async def async_set_object_retention(
    object_id: str,
    ttl_sec: int,
    owner_token: str = "",
    generation: int = 0,
) -> bool:
    """Async wrapper for set_object_retention."""
    return await asyncio.to_thread(set_object_retention, object_id, ttl_sec, owner_token, generation)


async def async_incr_refcount(object_id: str) -> int:
    """Async wrapper for incr_refcount."""
    return await asyncio.to_thread(incr_refcount, object_id)


async def async_decr_refcount(object_id: str) -> int:
    """Async wrapper for decr_refcount."""
    return await asyncio.to_thread(decr_refcount, object_id)


def get_metrics() -> dict:
    """Return staging storage metrics: disk usage, object count, lease count."""
    obj_dir = _staging_object_dir()
    disk_usage = 0
    object_count = 0
    leased_count = 0
    orphan_count = 0
    if obj_dir.is_dir():
        has_meta: set[str] = set()
        for entry in obj_dir.iterdir():
            if entry.suffix == ".meta.json":
                has_meta.add(entry.stem)
        for entry in obj_dir.iterdir():
            if entry.suffix == ".data":
                object_count += 1
                disk_usage += entry.stat().st_size
                if entry.stem not in has_meta:
                    orphan_count += 1
            elif entry.suffix == _LEASE_SUFFIX:
                oid = entry.stem
                try:
                    validate_object_id(oid)
                    if is_object_leased(oid):
                        leased_count += 1
                except ValueError:
                    pass
    return {
        "disk_usage_bytes": disk_usage,
        "object_count": object_count,
        "leased_count": leased_count,
        "orphan_count": orphan_count,
    }
