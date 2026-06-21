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

No page image bytes, LLM raw responses, or large OCR boxes are stored
in artifacts.  Only the structured question dicts that are the normal
output of each stage.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from typing import Any

logger = logging.getLogger(__name__)

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
_COMPLETED_TTL = 86400       # 24h for completed pipelines
_FAILED_TTL = 604800         # 7d for failed pipelines
_RUNNING_TTL = 604800        # 7d for running (keep while active)

# Stage artifacts considered "resumable" — reading one allows skipping
# all prior stages.  The dict maps stage_name → artifact_filename.
_RESUMABLE_ARTIFACTS: dict[str, str] = {
    "split": "split.json",
    "match": "match.json",
    "normalize_schema": "normalize_schema.json",
    "math_detect": "math_detect.json",
    "table_detect": "table_detect.json",
    "repair": "repair.json",
    "review": "review_commit_state.json",
}

def _ensure_dir(pipeline_id: str) -> str:
    """Create the artifact directory for a pipeline if it doesn't exist."""
    d = os.path.join(_get_artifact_root(), pipeline_id)
    try:
        os.makedirs(d, mode=0o755, exist_ok=True)
    except OSError as exc:
        logger.warning("Cannot create artifact dir %s: %s", d, exc)
    return d


def _artifact_path(pipeline_id: str, filename: str) -> str:
    """Full path for a given artifact filename."""
    return os.path.join(_get_artifact_root(), pipeline_id, filename)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def save_artifact(
    pipeline_id: str,
    stage_name: str,
    data: Any,
) -> str | None:
    """Save a stage output as a JSON artifact.

    Returns the file path if saved successfully, None on failure.
    On failure logs a warning but does NOT raise — pipeline continues.
    """
    filename = _RESUMABLE_ARTIFACTS.get(stage_name)
    if filename is None:
        return None
    path = _artifact_path(pipeline_id, filename)
    try:
        _ensure_dir(pipeline_id)
        _write_json(path, data)
        return path
    except Exception as exc:
        logger.warning(
            "Failed to save artifact for stage=%s pipeline=%s: %s",
            stage_name, pipeline_id, exc,
        )
        return None


def load_artifact(
    pipeline_id: str,
    stage_name: str,
) -> Any | None:
    """Load a previously saved stage artifact.

    Returns None if the artifact does not exist, is corrupted, or the
    stage is not resumable.  Never raises.
    """
    filename = _RESUMABLE_ARTIFACTS.get(stage_name)
    if filename is None:
        return None
    path = _artifact_path(pipeline_id, filename)
    if not os.path.isfile(path):
        return None
    try:
        return _read_json(path)
    except Exception as exc:
        logger.warning(
            "Corrupted artifact for stage=%s pipeline=%s (will fallback): %s",
            stage_name, pipeline_id, exc,
        )
        _safe_remove(path)
        return None


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
      2. If a stage has a readable artifact → resume from the *next* stage.
      3. If nothing found → full re-run.

    Example:
      completed_stages = [extract, normalize, split, match, normalize_schema]
      normalize_schema artifact exists → resume from math_detect
    """
    for i in range(len(completed_stages) - 1, -1, -1):
        stage = completed_stages[i]
        if artifact_exists(pipeline_id, stage):
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

    Args:
        pipeline_id: target pipeline.
        ttl: remove only if older than this many seconds.  None = remove all.
        force: skip safety checks (e.g. running pipeline).

    Returns:
        Number of files removed.
    """
    artifact_dir = os.path.join(_get_artifact_root(), pipeline_id)
    if not os.path.isdir(artifact_dir):
        return 0

    # Safety: don't touch running pipelines unless forced
    if not force and _is_running(pipeline_id):
        logger.info("Skipping cleanup for running pipeline %s", pipeline_id)
        return 0

    if ttl is not None:
        now = time.time()
        cutoff = now - ttl
        removed = 0
        for entry in os.listdir(artifact_dir):
            path = os.path.join(artifact_dir, entry)
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                _safe_remove(path)
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
) -> dict[str, int]:
    """Clean up artifacts for all pipelines beyond their TTL.

    Scans the artifact root directory, checks each pipeline's status
    (based on directory mtime), and removes expired entries.

    Args:
        completed_ttl: TTL for completed pipelines (default 24h).
        failed_ttl: TTL for failed pipelines (default 7d).

    Returns:
        {pipeline_id: files_removed, ...}
    """
    completed_ttl = completed_ttl or _COMPLETED_TTL
    failed_ttl = failed_ttl or _FAILED_TTL

    if not os.path.isdir(_get_artifact_root()):
        return {}

    results: dict[str, int] = {}
    now = time.time()
    for entry in os.listdir(_get_artifact_root()):
        pipeline_dir = os.path.join(_get_artifact_root(), entry)
        if not os.path.isdir(pipeline_dir):
            continue

        # Use directory mtime as proxy for last activity
        mtime = os.path.getmtime(pipeline_dir)
        age = now - mtime

        # Determine TTL based on status heuristic
        running = _contains_running_marker(pipeline_dir)
        if running:
            ttl = _RUNNING_TTL
        elif _contains_failed_marker(pipeline_dir):
            ttl = failed_ttl
        else:
            ttl = completed_ttl

        if age > ttl:
            removed = cleanup_artifacts(entry, force=True)
            if removed > 0:
                results[entry] = removed
    return results


def save_failed_marker(pipeline_id: str) -> None:
    """Write a marker file indicating the pipeline failed."""
    d = _ensure_dir(pipeline_id)
    try:
        with open(os.path.join(d, ".failed"), "w") as f:
            f.write("")
    except OSError:
        pass


def save_completed_marker(pipeline_id: str) -> None:
    """Write a marker file indicating the pipeline completed."""
    d = _ensure_dir(pipeline_id)
    try:
        with open(os.path.join(d, ".completed"), "w") as f:
            f.write("")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


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
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _json_fallback(obj: Any) -> str:
    """Fallback serializer for non-JSON-serializable objects."""
    return str(obj)


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
    d = os.path.join(_get_artifact_root(), pipeline_id)
    return os.path.isdir(d) and _has_no_terminal_marker(d)


def _contains_running_marker(pipeline_dir: str) -> bool:
    return _has_no_terminal_marker(pipeline_dir)


def _has_no_terminal_marker(pipeline_dir: str) -> bool:
    has_completed = os.path.isfile(os.path.join(pipeline_dir, ".completed"))
    has_failed = os.path.isfile(os.path.join(pipeline_dir, ".failed"))
    return not has_completed and not has_failed


def _contains_failed_marker(pipeline_dir: str) -> bool:
    return os.path.isfile(os.path.join(pipeline_dir, ".failed"))
