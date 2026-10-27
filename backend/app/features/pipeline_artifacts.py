"""Pipeline artifact store — lightweight file-based stage output persistence.

Each stage can write its output to a JSON file on disk. The checkpoint
stores only a file path reference, not the data itself.  On resume,
stages whose artifact is readable can be skipped (true resume) rather
than re-derived from the source file.

Artifact directory structure::

    .backend_cache/pipeline_artifacts/{pipeline_id}/
      split.json
      normalize_schema.json
      math_detect.json
      table_detect.json
      repair.json
      review_commit_state.json

Each artifact now stores metadata for accurate resume:

.. code-block:: python

    {
        "completed_stage": "normalize_schema",
        "completed_stage_index": 12,
        "pipeline_version": "1",
        "stage_versions": {...},
        "data": ...
    }
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import sys
import time
import uuid
from datetime import date, datetime
from datetime import time as dtime
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)

# P0-1: canonical stage order — derived from PipelineDefinition, the single
# source of truth.  This list includes ALL known stages in their correct
# relative order.  Optional stages (e.g. repair, ai_validation) are included
# at their canonical positions; the actual pipeline may skip them if disabled.
from app.features.pipeline_definition import PipelineDefinition as _PipelineDefinition

CANONICAL_STAGE_ORDER: list[str] = list(_PipelineDefinition.stage_names())

# Current pipeline version for artifact compatibility checks.
# Built from stage order hash + code + config fingerprints so that any
# relevant change automatically invalidates existing artifacts.
# Bump the explicit suffix when artifact data format changes.
# OCR failure status now survives legacy and gateway adapters instead of silently
# omitting failed pages. Older derived artifacts must not bypass that correction.
_PIPELINE_SCHEMA_VERSION = "5"


def _build_pipeline_fingerprint() -> str:
    """Content-addressed pipeline fingerprint for artifact compatibility.

    Includes:
    - Canonical stage order hash (stage reordering invalidates artifacts)
    - Schema version (explicit bump for format changes)
    - Python major.minor version (serialization stability)
    """
    stage_hash = hashlib.md5("|".join(CANONICAL_STAGE_ORDER).encode()).hexdigest()[:8]
    raw = "|".join(
        [
            stage_hash,
            f"schema:{_PIPELINE_SCHEMA_VERSION}",
            f"py:{sys.version_info.major}.{sys.version_info.minor}",
        ]
    )
    return f"p{_PIPELINE_SCHEMA_VERSION}_s{hashlib.md5(raw.encode()).hexdigest()[:12]}"


PIPELINE_VERSION = _build_pipeline_fingerprint()


def _build_config_fingerprint() -> str:
    """Content-addressed config fingerprint for artifact compatibility.

    Includes key OcrRuntimeConfig fields that affect OCR output quality.
    Falls back to 'default' when runtime config is not yet initialized.
    """
    try:
        from app.core.ocr_runtime_config import get_runtime_config

        cfg = get_runtime_config()
        key_fields = "|".join(
            [
                str(cfg.use_gpu),
                cfg.language,
                str(cfg.det_db_thresh),
                str(cfg.det_db_box_thresh),
                str(cfg.det_db_unclip_ratio),
                str(cfg.drop_score),
                str(cfg.min_image_width),
                str(cfg.enable_rotation),
                str(cfg.enable_ai_correction),
                str(cfg.worker_count),
                str(cfg.gpu_shards),
            ]
        )
        return hashlib.md5(key_fields.encode()).hexdigest()[:12]
    except Exception:
        return "default"


# Re-export for callers that need to check config-aware pipeline version
def current_pipeline_version() -> str:
    """Return pipeline version with config fingerprint appended.

    Call this at artifact save/compatibility-check time (not at module load)
    so that config changes invalidate cached artifacts.
    """
    return f"{PIPELINE_VERSION}_cfg{_build_config_fingerprint()}"


# Whitelist of types allowed for artifact serialization.
# Using ``str()`` as a fallback (the previous default) silently loses type
# information and can produce irreversible results — only explicit types are
# safe to serialize.
_ALLOWED_SERIAL_TYPES = (
    str,
    int,
    float,
    bool,
    type(None),
    list,
    tuple,
    dict,
    bytes,
    datetime,
    date,
    dtime,
    Decimal,
    uuid.UUID,
)


def stage_index(stage_name: str) -> int:
    """Return the canonical index of a stage, or -1 if unknown."""
    try:
        return CANONICAL_STAGE_ORDER.index(stage_name)
    except ValueError:
        return -1


def stages_before(stage_name: str) -> list[str]:
    """Return all canonical stages that appear BEFORE the given stage."""
    idx = stage_index(stage_name)
    if idx < 0:
        return []
    return list(CANONICAL_STAGE_ORDER[:idx])


def is_stage_before(a: str, b: str) -> bool:
    """Return True if stage A appears before stage B in canonical order."""
    return stage_index(a) < stage_index(b)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _get_artifact_root() -> str:
    """Return the artifact root directory (resolved at call time for testability)."""
    return os.environ.get(
        "PIPELINE_ARTIFACT_DIR",
        os.path.join(os.getcwd(), ".backend_cache", "pipeline_artifacts"),
    )


# Default TTLs (seconds)
_COMPLETED_TTL = 86400  # 24h for completed pipelines
_FAILED_TTL = 604800  # 7d for failed pipelines
_RUNNING_TTL = 604800  # 7d for running (keep while active)

# Stage artifacts considered "resumable" — reading one allows skipping
# all prior stages.  The dict maps stage_name → artifact_filename.
# Derived from PipelineDefinition.
_RESUMABLE_ARTIFACTS: dict[str, str] = dict(_PipelineDefinition.resumable_artifacts())

# Safe pipeline ID pattern — prevents path traversal via user-supplied IDs
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _validate_pipeline_id(pipeline_id: str) -> str:
    """Validate and return a safe pipeline ID, or raise ValueError."""
    if not pipeline_id:
        raise ValueError("pipeline_id must not be empty")
    if not _SAFE_ID_RE.match(pipeline_id):
        raise ValueError(
            f"Unsafe pipeline_id {pipeline_id!r}: only [A-Za-z0-9_-] allowed"
        )
    return pipeline_id


def _safe_artifact_dir(pipeline_id: str) -> str:
    """Return the artifact directory for a pipeline after safety validation.

    Resolves the full path and verifies it is within the artifact root.
    """
    root = os.path.realpath(_get_artifact_root())
    candidate = os.path.realpath(os.path.join(root, _validate_pipeline_id(pipeline_id)))
    if not candidate.startswith(root + os.sep) and candidate != root:
        raise ValueError(
            f"Resolved pipeline path {candidate} is outside artifact root {root}"
        )
    return candidate


def _ensure_dir(pipeline_id: str) -> str:
    """Create the artifact directory for a pipeline if it doesn't exist."""
    d = _safe_artifact_dir(pipeline_id)
    try:
        os.makedirs(d, mode=0o755, exist_ok=True)
    except OSError as exc:
        logger.warning("Cannot create artifact dir %s: %s", d, exc)
    return d


def _artifact_path(pipeline_id: str, filename: str) -> str:
    """Full path for a given artifact filename, with safety validation."""
    # Prevent path traversal in filename (e.g. "../../etc/passwd")
    safe_filename = os.path.basename(filename)
    if safe_filename != filename:
        raise ValueError(f"Unsafe filename {filename!r}: must be a bare name")
    return os.path.join(_safe_artifact_dir(pipeline_id), safe_filename)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def save_artifact(
    pipeline_id: str,
    stage_name: str,
    data: Any,
) -> str | None:
    """Save a stage output as a JSON artifact.

    The artifact is wrapped with metadata (completed_stage, stage_index,
    pipeline_version) so that restore can accurately determine which stages
    to skip and reject incompatible artifacts.

    Returns the file path if saved successfully, None on failure.
    On failure logs a warning but does NOT raise — pipeline continues.
    """
    filename = _RESUMABLE_ARTIFACTS.get(stage_name)
    if filename is None:
        return None
    path = _artifact_path(pipeline_id, filename)
    try:
        _ensure_dir(pipeline_id)
        # Wrap with metadata for accurate restore
        wrapped: dict[str, Any] = {
            "completed_stage": stage_name,
            "completed_stage_index": stage_index(stage_name),
            "pipeline_version": current_pipeline_version(),
            "config_fingerprint": _build_config_fingerprint(),
            "data": data,
        }
        _write_json(path, wrapped)
        return path
    except Exception as exc:
        logger.warning(
            "Failed to save artifact for stage=%s pipeline=%s: %s",
            stage_name,
            pipeline_id,
            exc,
        )
        return None


def _unwrap_artifact(
    saved: Any,
) -> tuple[str | None, int | None, str | None, str | None, Any]:
    """Unwrap a saved artifact, extracting metadata and inner data.

    Returns (completed_stage, completed_stage_index, pipeline_version,
             config_fingerprint, data).
    For legacy artifacts (pre-P0-1), returns None for metadata fields.

    When REJECT_LEGACY_ARTIFACTS is True, legacy artifacts raise ValueError
    so callers treat them as incompatible.
    """
    if isinstance(saved, dict) and "completed_stage" in saved and "data" in saved:
        return (
            str(saved.get("completed_stage", "")),
            int(saved.get("completed_stage_index", -1)),
            str(saved.get("pipeline_version", "")),
            str(saved.get("config_fingerprint", "")),
            saved["data"],
        )
    # Legacy artifact — reject if configured, otherwise warn and accept
    try:
        from app.core.config import settings

        if settings.REJECT_LEGACY_ARTIFACTS:
            raise ValueError("Legacy artifact rejected (REJECT_LEGACY_ARTIFACTS=True)")
    except ImportError:
        pass
    logger.warning(
        "Loading legacy artifact (no metadata wrapper) — "
        "consider re-running the pipeline to generate a compatible artifact"
    )
    return None, None, None, None, saved


def load_artifact(
    pipeline_id: str,
    stage_name: str,
) -> Any | None:
    """Load a previously saved stage artifact.

    Returns None if the artifact does not exist, is corrupted, or the
    stage is not resumable.  Never raises.

    For artifacts with metadata, the inner ``data`` field is returned.
    Legacy artifacts (raw data, no wrapper) are accepted with a warning
    for migration purposes but may be rejected in a future version.
    """
    filename = _RESUMABLE_ARTIFACTS.get(stage_name)
    if filename is None:
        return None
    path = _artifact_path(pipeline_id, filename)
    if not os.path.isfile(path):
        return None
    try:
        raw = _read_json(path)
        _, _, _, _, data = _unwrap_artifact(raw)
        return data if data is not None else raw
    except Exception as exc:
        logger.warning(
            "Corrupted artifact for stage=%s pipeline=%s (will fallback): %s",
            stage_name,
            pipeline_id,
            exc,
        )
        _safe_remove(path)
        return None


def check_artifact_compatibility(pipeline_id: str, stage_name: str) -> tuple[bool, str]:
    """Check whether a saved artifact is compatible with the current pipeline version.

    Returns (compatible: bool, reason: str). On success, reason is empty.
    On failure, reason describes why the artifact cannot be used.
    """
    filename = _RESUMABLE_ARTIFACTS.get(stage_name)
    if filename is None:
        return False, f"Stage {stage_name} is not resumable"
    path = _artifact_path(pipeline_id, filename)
    if not os.path.isfile(path):
        return False, f"No artifact found for stage {stage_name}"
    try:
        raw = _read_json(path)
    except Exception:
        return False, f"Corrupted artifact for stage {stage_name}"
    completed_stage, _, version, cfg_fp, _ = _unwrap_artifact(raw)
    if completed_stage is None:
        # Legacy artifact (pre-metadata)
        try:
            from app.core.config import settings

            if settings.REJECT_LEGACY_ARTIFACTS:
                return False, (
                    f"Legacy artifact for stage {stage_name} rejected "
                    f"(REJECT_LEGACY_ARTIFACTS=True)"
                )
        except ImportError:
            pass
        logger.warning(
            "Legacy artifact for stage=%s pipeline=%s (no metadata) — "
            "compatibility check passed but consider re-running pipeline",
            stage_name,
            pipeline_id,
        )
        return True, ""
    if not version:
        return False, f"Artifact for stage {stage_name} has no pipeline version"

    expected_version = current_pipeline_version()
    if version != expected_version:
        return False, (
            f"Pipeline version mismatch for artifact stage={stage_name}: "
            f"expected={expected_version}, got={version}. "
            "Re-run the full pipeline to generate a compatible artifact."
        )
    return True, ""


def artifact_exists(pipeline_id: str, stage_name: str) -> bool:
    """Check whether a resumable artifact exists on disk."""
    filename = _RESUMABLE_ARTIFACTS.get(stage_name)
    if filename is None:
        return False
    return os.path.isfile(_artifact_path(pipeline_id, filename))


def list_artifacts(pipeline_id: str) -> list[str]:
    """List stage names for which a readable artifact exists."""
    available: list[str] = []
    for stage_name in _RESUMABLE_ARTIFACTS:
        if artifact_exists(pipeline_id, stage_name):
            available.append(stage_name)
    return available


def find_resumable_stage(pipeline_id: str, completed_stages: list[str]) -> str | None:
    """Find the latest stage we can resume from, or None for full re-run.

    Strategy:
      1. Walk completed_stages in reverse order (newest first).
      2. If a stage has a readable + compatible artifact → resume from the
         *next* stage.
      3. If nothing found → full re-run.

    P0-1: uses the canonical stage order to determine "next". Also checks
    artifact compatibility via ``check_artifact_compatibility``.
    """
    for i in range(len(completed_stages) - 1, -1, -1):
        stage = completed_stages[i]
        compatible, _ = check_artifact_compatibility(pipeline_id, stage)
        if compatible and artifact_exists(pipeline_id, stage):
            if i + 1 < len(completed_stages):
                return completed_stages[i + 1]
            return stage
    return None


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def cleanup_artifacts(
    pipeline_id: str,
    *,
    ttl: int | None = None,
    force: bool = False,
) -> int:
    """Remove artifact files for a pipeline.

    Note: the ttl-based code path removes files by mtime without
    special-casing marker files (.completed / .failed).  If a marker
    is older than its adjacent artifacts, it may be removed first —
    the directory may appear "running" until the artifacts age past
    ttl too.  Prefer cleanup_expired() for whole-directory removal
    based on pipeline-status TTL.

    Args:
        pipeline_id: target pipeline.
        ttl: remove only if older than this many seconds.  None = remove all.
        force: skip safety checks (e.g. running pipeline).

    Returns:
        Number of files removed.
    """
    artifact_dir = _safe_artifact_dir(pipeline_id)
    if not os.path.isdir(artifact_dir):
        return 0

    # Safety: don't touch running pipelines unless forced
    if not force and _is_running(pipeline_id):
        logger.info("Skipping cleanup for running pipeline %s", pipeline_id)
        return 0

    resolved_root = os.path.realpath(artifact_dir)

    if ttl is not None:
        now = time.time()
        cutoff = now - ttl
        removed = 0
        for entry in os.listdir(artifact_dir):
            raw_path = os.path.join(artifact_dir, entry)
            # Resolve each entry and verify it stays within the safe directory
            resolved = os.path.realpath(raw_path)
            if (
                not resolved.startswith(resolved_root + os.sep)
                and resolved != resolved_root
            ):
                logger.warning("Skipping path traversal attempt: %s", raw_path)
                continue
            if os.path.isfile(resolved) and os.path.getmtime(resolved) < cutoff:
                _safe_remove(resolved)
                removed += 1
        # Remove the directory itself if empty
        if _dir_is_empty(artifact_dir):
            _safe_rmdir(artifact_dir)
        return removed

    # Remove everything
    try:
        shutil.rmtree(artifact_dir)
    except OSError as exc:
        logger.warning("Failed to remove artifact dir %s: %s", artifact_dir, exc)
        return 0
    return 1


def cleanup_expired(
    completed_ttl: int | None = None,
    failed_ttl: int | None = None,
    dry_run: bool = False,
) -> dict:
    """Clean up artifacts for all pipelines beyond their TTL.

    Scans the artifact root directory, checks each pipeline's status
    (based on directory mtime), and removes expired entries.

    Args:
        completed_ttl: TTL for completed pipelines (default 24h).
        failed_ttl: TTL for failed pipelines (default 7d).
        dry_run: if True, only scan and count, do not delete.

    Returns:
        {
            "scanned_count": int,            # total pipeline directories examined
            "deleted_count": int,            # files deleted (or would-be-deleted in dry_run)
            "freed_bytes": int,
            "skipped_running_count": int,
            "pipeline_results": {pipeline_id: files_removed_or_would_remove},
        }
    """
    completed_ttl = completed_ttl or _COMPLETED_TTL
    failed_ttl = failed_ttl or _FAILED_TTL

    if not os.path.isdir(_get_artifact_root()):
        return {
            "scanned_count": 0,
            "deleted_count": 0,
            "freed_bytes": 0,
            "skipped_running_count": 0,
            "pipeline_results": {},
        }

    results: dict[str, int] = {}
    now = time.time()
    skipped_running = 0
    freed_bytes = 0
    total_dirs = 0

    resolved_root = os.path.realpath(_get_artifact_root())

    for entry in os.listdir(_get_artifact_root()):
        pipeline_dir = os.path.join(_get_artifact_root(), entry)
        if not os.path.isdir(pipeline_dir):
            continue

        # Resolve and validate to prevent symlink traversal
        resolved = os.path.realpath(pipeline_dir)
        if (
            not resolved.startswith(resolved_root + os.sep)
            and resolved != resolved_root
        ):
            logger.warning(
                "Skipping path traversal attempt during cleanup: %s", pipeline_dir
            )
            continue

        total_dirs += 1

        # Use directory mtime as proxy for last activity
        mtime = os.path.getmtime(pipeline_dir)
        age = now - mtime

        # Determine TTL based on status heuristic
        running = _is_running_pipeline(pipeline_dir)
        if running:
            ttl = _RUNNING_TTL
        elif _contains_failed_marker(pipeline_dir):
            ttl = failed_ttl
        else:
            ttl = completed_ttl

        if age > ttl:
            if dry_run:
                # Count files that would be removed
                file_count = _count_artifact_files(pipeline_dir)
                if file_count > 0:
                    results[entry] = file_count
                    freed_bytes += _dir_size(pipeline_dir)
            else:
                # Capture accurate size before deletion
                dir_size = _dir_size(pipeline_dir)
                removed = cleanup_artifacts(entry, force=True)
                if removed > 0:
                    results[entry] = removed
                    freed_bytes += dir_size
        else:
            if running:
                skipped_running += 1

    # deleted_count = files affected (would-be-deleted in dry_run, actually removed otherwise)
    deleted_count = sum(results.values()) if results else 0
    return {
        "scanned_count": total_dirs,
        "deleted_count": deleted_count,
        "freed_bytes": freed_bytes,
        "skipped_running_count": skipped_running,
        "pipeline_results": results,
    }


def save_failed_marker(pipeline_id: str) -> None:
    """Write a marker file indicating the pipeline failed."""
    d = _safe_artifact_dir(pipeline_id)
    try:
        with open(os.path.join(d, ".failed"), "w") as f:
            f.write("")
    except OSError:
        pass


def save_completed_marker(pipeline_id: str) -> None:
    """Write a marker file indicating the pipeline completed."""
    d = _safe_artifact_dir(pipeline_id)
    try:
        with open(os.path.join(d, ".completed"), "w") as f:
            f.write("")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _count_artifact_files(pipeline_dir: str) -> int:
    """Count artifact files in a pipeline directory (non-recursive)."""
    if not os.path.isdir(pipeline_dir):
        return 0
    try:
        return sum(
            1
            for f in os.listdir(pipeline_dir)
            if os.path.isfile(os.path.join(pipeline_dir, f))
        )
    except OSError:
        return 0


def _dir_size(pipeline_dir: str) -> int:
    """Estimate total size of files in a pipeline directory."""
    total = 0
    if not os.path.isdir(pipeline_dir):
        return 0
    try:
        for f in os.listdir(pipeline_dir):
            fpath = os.path.join(pipeline_dir, f)
            if os.path.isfile(fpath):
                total += os.path.getsize(fpath)
    except OSError:
        pass
    return total


def _write_json(path: str, data: Any) -> None:
    """Write JSON with UTF-8 encoding and safe tempfile + rename pattern."""
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, default=_json_fallback)
        os.replace(tmp, path)
    except Exception:
        _safe_remove(tmp)
        raise


def _read_json(path: str) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _json_fallback(obj: Any) -> str:
    """Fallback serializer for non-JSON-serializable objects.

    Only handles whitelisted types; unknown types raise TypeError to prevent
    silent data loss from ``str()``-based serialization.
    """
    if isinstance(obj, _ALLOWED_SERIAL_TYPES):
        return str(obj)
    raise TypeError(
        f"Type {type(obj).__name__} is not allowed for artifact serialization. "
        f"Add it to _ALLOWED_SERIAL_TYPES or convert explicitly."
    )


def _safe_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _safe_rmdir(path: str) -> None:
    try:
        os.rmdir(path)
    except OSError:
        pass


def _dir_is_empty(path: str) -> bool:
    try:
        return not os.listdir(path)
    except OSError:
        return True


def _is_running(pipeline_id: str) -> bool:
    """Check if a pipeline is still running (no completed/failed markers)."""
    try:
        d = _safe_artifact_dir(pipeline_id)
    except ValueError:
        return False
    return os.path.isdir(d) and _has_no_terminal_marker(d)


def _is_running_pipeline(pipeline_dir: str) -> bool:
    return _has_no_terminal_marker(pipeline_dir)


def _has_no_terminal_marker(pipeline_dir: str) -> bool:
    has_completed = os.path.isfile(os.path.join(pipeline_dir, ".completed"))
    has_failed = os.path.isfile(os.path.join(pipeline_dir, ".failed"))
    return not has_completed and not has_failed


def _contains_failed_marker(pipeline_dir: str) -> bool:
    return os.path.isfile(os.path.join(pipeline_dir, ".failed"))
