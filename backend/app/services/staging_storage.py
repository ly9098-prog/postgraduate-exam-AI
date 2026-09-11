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
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from app.core.config import settings
from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile

logger = logging.getLogger("postgraduate-ai.staging")

# Resolve staging directory — use STAGING_STORAGE_DIR from settings or a sensible default.
# In production/cloud_api, the staging directory must be explicitly configured and writable.
_candidate = getattr(settings, "STAGING_STORAGE_DIR", "") or "/opt/2240ai-v2/staging"
_STAGING_DIR = Path(_candidate)

# In restricted environments, fail if the staging directory parent doesn't exist
_profile = detect_deployment_profile()
_is_production = (
    _profile == DeploymentProfile.CLOUD_API or settings.APP_ENV == "production"
)
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
_ORPHAN_GRACE_SEC = 3600  # never delete a partial write younger than one hour

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


def _write_lease_unlocked(
    object_id: str,
    owner_token: str = "",
    generation: int = 0,
    ttl_sec: int = _DEFAULT_LEASE_SEC,
) -> None:
    import json

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
    tmp = lp.with_name(f".{lp.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp, "w") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(lp)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def lease_object(
    object_id: str,
    owner_token: str = "",
    generation: int = 0,
    ttl_sec: int = _DEFAULT_LEASE_SEC,
) -> None:
    """Mark a staging object as in-use by an active task.

    Lease creation is serialized with cleanup/touch so cleanup cannot observe
    "unleased" and delete the object while a worker is claiming it.
    """
    validate_object_id(object_id)
    with _object_lifecycle_guard(object_id):
        if not _object_path(object_id).is_file():
            raise FileNotFoundError(f"Staging object {object_id} not found")
        _write_lease_unlocked(object_id, owner_token, generation, ttl_sec)


def release_object(object_id: str, owner_token: str = "", generation: int = 0) -> bool:
    """Remove the lease marker when ownership fencing permits it."""
    import json

    validate_object_id(object_id)
    with _object_lifecycle_guard(object_id):
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
                        object_id,
                        stored_owner,
                        owner_token,
                    )
                    return False
                stored_gen = data.get("generation", -1)
                if stored_owner and stored_gen != -1 and stored_gen != generation:
                    logger.warning(
                        "Lease generation mismatch for %s (expected=%d, got=%d)",
                        object_id,
                        stored_gen,
                        generation,
                    )
                    return False
            except (json.JSONDecodeError, OSError):
                pass

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
    """Extend an existing lease without opening a cleanup race."""
    import json

    validate_object_id(object_id)
    with _object_lifecycle_guard(object_id):
        lp = _lease_path(object_id)
        if not lp.exists() or not _object_path(object_id).is_file():
            return False

        if owner_token:
            try:
                with open(lp) as f:
                    data = json.load(f)
                stored_owner = data.get("owner_token", "")
                if stored_owner and stored_owner != owner_token:
                    logger.warning(
                        "Extend lease owner mismatch for %s (expected=%s, got=%s)",
                        object_id,
                        stored_owner,
                        owner_token,
                    )
                    return False
                stored_gen = data.get("generation", -1)
                if stored_owner and stored_gen != -1 and stored_gen != generation:
                    logger.warning(
                        "Extend lease generation mismatch for %s (expected=%d, got=%d)",
                        object_id,
                        stored_gen,
                        generation,
                    )
                    return False
            except (json.JSONDecodeError, OSError):
                return False

        _write_lease_unlocked(object_id, owner_token, generation, ttl_sec)
        return True


def create_work_copy(object_id: str, scratch_dir: str | Path) -> Path:
    """Create a writable copy of a staging object in the scratch directory.

    Always copies bytes into a unique scratch path. Hard links are deliberately
    avoided because a writable hard link would mutate the content-addressed
    staging inode. The caller may read, modify, or delete the returned copy;
    the staging original is NEVER modified.

    Raises FileNotFoundError if the staging object does not exist.
    """
    validate_object_id(object_id)
    src = _object_path(object_id)
    if not src.exists():
        raise FileNotFoundError(f"Staging object {object_id} not found at {src}")

    _ensure_dir(Path(scratch_dir))
    # Content-addressed staging objects can be referenced by multiple durable
    # tasks at the same time.  A deterministic ``{object_id}.work`` path makes
    # those workers overwrite and mutate the same scratch file.  Give every
    # claim an independent work copy instead.
    work_path = Path(scratch_dir) / f"{object_id}.{uuid.uuid4().hex}.work"

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


def set_object_retention(
    object_id: str, ttl_sec: int, owner_token: str = "", generation: int = 0
) -> bool:
    """Adjust the lease TTL for a staging object based on terminal state.

    Called after a task reaches a terminal state (success, fail, dead,
    cancel) to set the appropriate retention period. The object remains
    leased (protected from cleanup) for *ttl_sec* more seconds, after
    which cleanup_orphans may remove it.

    Returns True if the retention was set, False if the object has no
    lease or ownership verification failed.
    """
    return extend_lease(
        object_id, owner_token=owner_token, generation=generation, ttl_sec=ttl_sec
    )


# ── Refcount for content-addressed staging objects ──

_REFCOUNT_STORE: dict[str, int] = {}
"""In-memory refcount fallback used only in development/local environments."""

# Object lifecycle coordination -------------------------------------------------
#
# Staging objects are content-addressed and may be reused by a new task at the
# same moment the hourly cleanup decides an old object is expired.  Metadata
# timestamps alone cannot close that TOCTOU window.  Serialize lifecycle
# mutations (touch/lease/refcount/delete) with a short Redis guard in deployed
# environments.  Local development without Redis uses an in-process lock.
_OBJECT_GUARD_PREFIX = "staging:v2:guard"
_OBJECT_GUARD_TTL_SEC = 30
_OBJECT_GUARD_WAIT_SEC = 3.0
_OBJECT_GUARD_RELEASE_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""
_LOCAL_OBJECT_GUARDS: tuple[Lock, ...] = tuple(Lock() for _ in range(64))


def _local_object_guard(object_id: str) -> Lock:
    # Fixed lock striping avoids an unbounded per-object lock registry in long
    # running development processes while preserving lifecycle serialization.
    return _LOCAL_OBJECT_GUARDS[hash(object_id) % len(_LOCAL_OBJECT_GUARDS)]


# Synchronous staging cleanup runs in ``asyncio.to_thread``.  It must not reuse
# the application's ``redis.asyncio`` client through ``asyncio.run`` because
# that client belongs to the main event loop.  Keep a dedicated synchronous
# redis-py client for the synchronous cleanup/refcount path.
_REFCOUNT_SYNC_CLIENT = None

# Atomic decrement prevents a DECR -> concurrent INCR -> DEL race from deleting
# a newly-live reference count.
_REFCOUNT_DECR_LUA = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
if current <= 1 then
  redis.call('DEL', KEYS[1])
  return 0
end
return redis.call('DECR', KEYS[1])
"""


def _ensure_refcount_redis_sync():
    global _REFCOUNT_SYNC_CLIENT
    if not settings.REDIS_URL:
        return None
    if _REFCOUNT_SYNC_CLIENT is not None:
        return _REFCOUNT_SYNC_CLIENT
    try:
        import redis as redis_sync

        _REFCOUNT_SYNC_CLIENT = redis_sync.from_url(
            settings.REDIS_URL,
            socket_connect_timeout=2,
            socket_timeout=2,
            decode_responses=True,
        )
        return _REFCOUNT_SYNC_CLIENT
    except Exception:
        _REFCOUNT_SYNC_CLIENT = None
        return None


def _reset_refcount_redis_sync() -> None:
    global _REFCOUNT_SYNC_CLIENT
    client = _REFCOUNT_SYNC_CLIENT
    _REFCOUNT_SYNC_CLIENT = None
    if client is not None:
        try:
            client.close()
        except Exception:
            pass


@contextmanager
def _object_lifecycle_guard(object_id: str):
    """Serialize lifecycle mutation for one staging object.

    Production uses Redis so cleanup, web enqueue and workers running in
    different processes cannot delete/reuse the same object concurrently.
    Failure to acquire/read the coordination backend is fail-closed.
    """
    validate_object_id(object_id)
    if not settings.REDIS_URL:
        lock = _local_object_guard(object_id)
        acquired = lock.acquire(timeout=_OBJECT_GUARD_WAIT_SEC)
        if not acquired:
            raise RuntimeError(f"Timed out acquiring staging guard: {object_id}")
        try:
            yield
        finally:
            lock.release()
        return

    client = _ensure_refcount_redis_sync()
    if client is None:
        if _is_production:
            raise RuntimeError("Redis unavailable for staging lifecycle guard")
        lock = _local_object_guard(object_id)
        acquired = lock.acquire(timeout=_OBJECT_GUARD_WAIT_SEC)
        if not acquired:
            raise RuntimeError(f"Timed out acquiring staging guard: {object_id}")
        try:
            yield
        finally:
            lock.release()
        return

    key = f"{_OBJECT_GUARD_PREFIX}:{object_id}"
    token = uuid.uuid4().hex
    deadline = time.monotonic() + _OBJECT_GUARD_WAIT_SEC
    acquired = False
    try:
        while time.monotonic() < deadline:
            try:
                if client.set(key, token, nx=True, ex=_OBJECT_GUARD_TTL_SEC):
                    acquired = True
                    break
            except Exception as exc:
                _reset_refcount_redis_sync()
                raise RuntimeError(
                    "Redis unavailable for staging lifecycle guard"
                ) from exc
            time.sleep(0.025)
        if not acquired:
            raise RuntimeError(f"Timed out acquiring staging guard: {object_id}")
        yield
    finally:
        if acquired:
            try:
                client.eval(_OBJECT_GUARD_RELEASE_LUA, 1, key, token)
            except Exception:
                # TTL guarantees eventual release.  Do not mask the operation
                # result solely because guard cleanup failed.
                logger.warning(
                    "Failed to release staging lifecycle guard: %s", object_id
                )


def _refcount_key(object_id: str) -> str:
    validate_object_id(object_id)
    return f"staging:v2:refcount:{object_id}"


def _refcount_redis_op(op: str, object_id: str) -> int | None:
    """Execute a synchronous refcount operation without crossing event loops."""
    client = _ensure_refcount_redis_sync()
    if client is None:
        return None
    key = _refcount_key(object_id)
    try:
        if op == "incr":
            return int(client.incr(key))
        if op == "decr":
            return int(client.eval(_REFCOUNT_DECR_LUA, 1, key))
        if op == "get":
            value = client.get(key)
            return int(value) if value else 0
        return None
    except Exception:
        _reset_refcount_redis_sync()
        return None


def get_refcounts(object_ids: list[str]) -> dict[str, int]:
    """Fetch many refcounts in one Redis round trip.

    Cleanup may inspect thousands of objects.  MGET keeps the hourly job cheap
    and gives production a single fail-closed decision before any deletion.
    """
    unique_ids = list(dict.fromkeys(object_ids))
    if not unique_ids:
        return {}
    if settings.REDIS_URL:
        client = _ensure_refcount_redis_sync()
        if client is not None:
            try:
                values = client.mget(
                    [_refcount_key(object_id) for object_id in unique_ids]
                )
                return {
                    object_id: int(value) if value else 0
                    for object_id, value in zip(unique_ids, values, strict=True)
                }
            except Exception:
                _reset_refcount_redis_sync()
        if _is_production:
            raise RuntimeError("Redis unavailable for staging refcount batch read")
    return {object_id: _REFCOUNT_STORE.get(object_id, 0) for object_id in unique_ids}


def incr_refcount(object_id: str) -> int:
    """Increment the staging reference count under the lifecycle guard."""
    validate_object_id(object_id)
    with _object_lifecycle_guard(object_id):
        if settings.REDIS_URL:
            value = _refcount_redis_op("incr", object_id)
            if value is not None:
                return value
            if _is_production:
                raise RuntimeError(
                    f"Redis unavailable for refcount incr (object_id={object_id})"
                )
        count = _REFCOUNT_STORE.get(object_id, 0) + 1
        _REFCOUNT_STORE[object_id] = count
        return count


def decr_refcount(object_id: str) -> int:
    """Atomically decrement a staging reference count, never below zero."""
    validate_object_id(object_id)
    with _object_lifecycle_guard(object_id):
        if settings.REDIS_URL:
            value = _refcount_redis_op("decr", object_id)
            if value is not None:
                return value
            if _is_production:
                raise RuntimeError(
                    f"Redis unavailable for refcount decr (object_id={object_id})"
                )
        count = _REFCOUNT_STORE.get(object_id, 0) - 1
        if count <= 0:
            _REFCOUNT_STORE.pop(object_id, None)
        else:
            _REFCOUNT_STORE[object_id] = count
        return max(0, count)


def get_refcount(object_id: str) -> int:
    """Return the current reference count (0 if unknown)."""
    return get_refcounts([object_id]).get(object_id, 0)


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
    # Refreshed whenever a durable task references this content-addressed
    # object. Cleanup uses it in addition to created_at, so reusing an older
    # object cannot race the hourly retention sweep before a worker claims it.
    last_referenced_at: float | None = None


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
        touch_object(object_id)
        return _load_metadata(object_id)

    src_size = os.path.getsize(source_path)
    _check_disk_quota(_staging_object_dir(), src_size)
    _ensure_dir(dest.parent)

    # Atomic write with a unique sibling temp file.  A deterministic
    # ``.data.tmp`` name lets concurrent uploads of identical content truncate
    # each other's temporary file before the atomic rename.
    tmp_dest = dest.with_name(f".{dest.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(source_path, "rb") as src_f:
            with open(tmp_dest, "wb") as dst_f:
                shutil.copyfileobj(src_f, dst_f)
                dst_f.flush()
                os.fsync(dst_f.fileno())
        tmp_dest.chmod(0o400)
        # Replacing an already-created content-addressed target is harmless
        # (the bytes have the same SHA-256), but avoid needless churn when a
        # concurrent writer won the race.
        if not dest.exists():
            tmp_dest.replace(dest)
    finally:
        try:
            tmp_dest.unlink(missing_ok=True)
        except OSError:
            pass

    meta = {
        "object_id": object_id,
        "sha256": sha256,
        "size": src_size,
        "mime": mime,
        "original_name": original_name,
        "created_at": time.time(),
        "staging_path": str(dest),
        "last_referenced_at": time.time(),
    }
    _write_metadata(object_id, meta)
    logger.info(
        "Staged file: object_id=%s sha256=%s size=%d mime=%s",
        object_id,
        sha256[:16],
        src_size,
        mime,
    )
    return StagingObject(**meta)


def touch_object(object_id: str) -> bool:
    """Refresh retention without racing the cleanup decision/delete window."""
    import json

    validate_object_id(object_id)
    with _object_lifecycle_guard(object_id):
        if not _object_path(object_id).is_file():
            return False
        metadata_path = _metadata_path(object_id)
        if not metadata_path.is_file():
            return False
        try:
            data = json.loads(metadata_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return False
            data["last_referenced_at"] = time.time()
            _write_metadata(object_id, data)
            return True
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return False


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


def _delete_object_unlocked(object_id: str) -> bool:
    removed = False
    for p in (
        _object_path(object_id),
        _metadata_path(object_id),
        _lease_path(object_id),
    ):
        if p.exists():
            p.unlink()
            removed = True
    if removed:
        logger.info("Deleted staging object: object_id=%s", object_id)
    return removed


def delete_object(object_id: str) -> bool:
    """Delete a staging object while excluding concurrent reuse/lease."""
    validate_object_id(object_id)
    with _object_lifecycle_guard(object_id):
        return _delete_object_unlocked(object_id)


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
    tmp = mp.with_name(f".{mp.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp, "w") as f:
            json.dump(data, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        tmp.chmod(0o400)
        tmp.replace(mp)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def cleanup_orphans(max_age_sec: int | None = None) -> int:
    """Remove expired/orphan staging entries without racing active writers.

    Normal retention follows ``STAGING_RETENTION_SEC``.  Partial files and
    malformed/legacy markers are only reclaimed after a separate one-hour
    grace period.  In production Redis refcount lookup fails closed: if the
    shared reference state cannot be read, this function raises before
    deleting any staged object.
    """
    import json

    configured_age = int(
        getattr(settings, "STAGING_RETENTION_SEC", _DEFAULT_MAX_AGE_SEC)
        or _DEFAULT_MAX_AGE_SEC
    )
    age = int(max_age_sec) if max_age_sec is not None else configured_age
    age = max(_ORPHAN_GRACE_SEC, age)
    now = time.time()
    cutoff = now - age
    orphan_cutoff = now - _ORPHAN_GRACE_SEC
    obj_dir = _staging_object_dir()
    removed = 0

    def older_than(path: Path, threshold: float) -> bool:
        try:
            return path.stat().st_mtime < threshold
        except OSError:
            return False

    def unlink(path: Path) -> bool:
        try:
            path.unlink(missing_ok=True)
            return True
        except OSError as exc:
            logger.warning("Failed to remove staging entry %s: %s", path.name, exc)
            return False

    entries = list(obj_dir.iterdir()) if obj_dir.is_dir() else []

    # Atomic-write leftovers must never be deleted while a writer may still be
    # fsyncing/renaming them.
    for entry in entries:
        if (
            entry.is_file()
            and entry.name.endswith(".tmp")
            and older_than(entry, orphan_cutoff)
        ):
            removed += int(unlink(entry))

    # Expired/corrupt leases should not protect an object forever.  Valid live
    # leases are left untouched and checked again below via is_object_leased().
    for entry in entries:
        if not entry.is_file() or not entry.name.endswith(_LEASE_SUFFIX):
            continue
        oid = entry.name[: -len(_LEASE_SUFFIX)]
        try:
            validate_object_id(oid)
        except ValueError:
            if older_than(entry, orphan_cutoff):
                removed += int(unlink(entry))
            continue
        with _object_lifecycle_guard(oid):
            # The path may have been replaced by an extend/claim while cleanup
            # waited for the guard, so inspect the current lease, not the old
            # directory-entry snapshot.
            current = _lease_path(oid)
            if not current.exists():
                continue
            stale = False
            try:
                data = json.loads(current.read_text(encoding="utf-8"))
                expires_at = data.get("expires_at")
                if expires_at is not None:
                    stale = float(expires_at) <= time.time()
                else:
                    stale = older_than(
                        current,
                        time.time() - max(_DEFAULT_LEASE_SEC, _ORPHAN_GRACE_SEC),
                    )
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                stale = older_than(current, orphan_cutoff)
            if stale:
                removed += int(unlink(current))

    data_ids: set[str] = set()
    meta_ids: set[str] = set()
    invalid_files: list[Path] = []
    for entry in list(obj_dir.iterdir()) if obj_dir.is_dir() else []:
        if not entry.is_file():
            continue
        if entry.name.endswith(".data"):
            oid = entry.name[: -len(".data")]
            try:
                validate_object_id(oid)
            except ValueError:
                invalid_files.append(entry)
            else:
                data_ids.add(oid)
        elif entry.name.endswith(_METADATA_SUFFIX):
            oid = entry.name[: -len(_METADATA_SUFFIX)]
            try:
                validate_object_id(oid)
            except ValueError:
                invalid_files.append(entry)
            else:
                meta_ids.add(oid)

    # Unknown files are never touched immediately; allow an operator or an
    # interrupted deployment a grace period first.
    for entry in invalid_files:
        if older_than(entry, orphan_cutoff):
            removed += int(unlink(entry))

    all_ids = sorted(data_ids | meta_ids)
    get_refcounts(all_ids)  # fail closed before object deletion

    for oid in all_ids:
        # Re-check every lifecycle signal while holding the same guard used by
        # enqueue touches, worker leases and refcount mutations.  This closes
        # the classic check-old-metadata -> concurrent reuse -> delete race.
        with _object_lifecycle_guard(oid):
            if is_object_leased(oid):
                continue
            if get_refcount(oid) > 0:
                continue

            data_path = _object_path(oid)
            meta_path = _metadata_path(oid)
            has_data = data_path.exists()
            has_meta = meta_path.exists()

            # A data/meta half-pair can be the tiny crash window between the two
            # atomic renames.  Only reclaim it after the orphan grace period.
            if not (has_data and has_meta):
                existing = [path for path in (data_path, meta_path) if path.exists()]
                if existing and all(
                    older_than(path, orphan_cutoff) for path in existing
                ):
                    for path in existing:
                        removed += int(unlink(path))
                continue

            try:
                meta = _load_metadata(oid)
            except Exception:
                # Corrupt metadata plus data is also protected by the grace window.
                if older_than(data_path, orphan_cutoff) and older_than(
                    meta_path, orphan_cutoff
                ):
                    removed += int(unlink(data_path))
                    removed += int(unlink(meta_path))
                continue

            reference_at = float(meta.last_referenced_at or meta.created_at)
            if reference_at < cutoff:
                if _delete_object_unlocked(oid):
                    removed += 1

    if removed:
        logger.info("Cleanup removed %d expired/orphaned staging entries", removed)
    return removed


def inspect_staging_cleanup_capability() -> tuple[bool, str | None]:
    """Return whether the staging cleanup can safely read and mutate storage."""
    try:
        obj_dir = _staging_object_dir()
    except Exception as exc:
        return False, f"staging 目录不可创建：{type(exc).__name__}: {str(exc)[:160]}"
    if not obj_dir.is_dir():
        return False, "staging objects 路径不是目录"
    if not os.access(obj_dir, os.R_OK | os.W_OK | os.X_OK):
        return False, "staging objects 目录缺少读/写/遍历权限"
    return True, None


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


async def async_touch_object(object_id: str) -> bool:
    """Async wrapper for touch_object."""
    return await asyncio.to_thread(touch_object, object_id)


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
    return await asyncio.to_thread(
        lease_object, object_id, owner_token, generation, ttl_sec
    )


async def async_extend_lease(
    object_id: str,
    owner_token: str = "",
    generation: int = 0,
    ttl_sec: int = _DEFAULT_LEASE_SEC,
) -> bool:
    """Async wrapper for extend_lease."""
    return await asyncio.to_thread(
        extend_lease, object_id, owner_token, generation, ttl_sec
    )


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
    return await asyncio.to_thread(
        set_object_retention, object_id, ttl_sec, owner_token, generation
    )


async def async_incr_refcount(object_id: str) -> int:
    """Async wrapper preserving the same lifecycle guard as sync callers."""
    return await asyncio.to_thread(incr_refcount, object_id)


async def async_decr_refcount(object_id: str) -> int:
    """Async wrapper preserving the same lifecycle guard as sync callers."""
    return await asyncio.to_thread(decr_refcount, object_id)


def get_metrics() -> dict:
    """Return staging storage metrics: disk usage, object count, leases, orphans."""
    obj_dir = _staging_object_dir()
    disk_usage = 0
    object_count = 0
    leased_count = 0
    orphan_count = 0
    if obj_dir.is_dir():
        has_meta: set[str] = set()
        for entry in obj_dir.iterdir():
            if entry.is_file() and entry.name.endswith(_METADATA_SUFFIX):
                has_meta.add(entry.name[: -len(_METADATA_SUFFIX)])
        for entry in obj_dir.iterdir():
            if not entry.is_file():
                continue
            if entry.name.endswith(".data"):
                oid = entry.name[: -len(".data")]
                object_count += 1
                try:
                    disk_usage += entry.stat().st_size
                except OSError:
                    pass
                if oid not in has_meta:
                    orphan_count += 1
            elif entry.name.endswith(_LEASE_SUFFIX):
                oid = entry.name[: -len(_LEASE_SUFFIX)]
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
