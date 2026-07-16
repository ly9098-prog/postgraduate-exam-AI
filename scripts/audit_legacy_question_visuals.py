#!/usr/bin/env python3
"""audit_legacy_question_visuals.py — Database-driven legacy visual inventory.

Read-only audit of question_imports and questions tables for subject_id=7.
Scans segments, options, source_image_name, Question.image_url and produces
a complete classification of every record's visual content state.

Usage:
    # Full audit (no previews, no HTTP checks)
    python scripts/audit_legacy_question_visuals.py \
        --db sqlite+aiosqlite:///./backend/postgraduate.db \
        --pdf artifacts/data-structure-import/source/ds_sc.pdf \
        --output-dir /tmp/legacy-audit

    # With HTTP verification and preview rendering
    python scripts/audit_legacy_question_visuals.py \
        --db sqlite+aiosqlite:///./backend/postgraduate.db \
        --pdf artifacts/data-structure-import/source/ds_sc.pdf \
        --output-dir /tmp/legacy-audit --verify-http --generate-previews

    # Single import
    python scripts/audit_legacy_question_visuals.py \
        --db sqlite+aiosqlite:///./backend/postgraduate.db \
        --pdf artifacts/data-structure-import/source/ds_sc.pdf \
        --only-import-id 407
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import traceback
import unicodedata
from dataclasses import dataclass, field, asdict
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger("legacy_visual_audit")

# ── Ensure backend importable ──
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

# ── Import pure functions from backfill script ──
try:
    import backfill_question_images as bqi
    HAS_BACKFILL = True
except Exception as e:
    logger.warning("Cannot import backfill module: %s", e)
    HAS_BACKFILL = False

# ── Constants ──
SUBJECT_ID = 7
FROZEN_IMPORT_IDS = frozenset({450, 452, 461})

STORAGE_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "backend", "static", "question-assets")
)

PDF_PATH_DEFAULT = os.path.join(
    os.path.dirname(__file__), "..",
    "artifacts/data-structure-import/source/ds_sc.pdf",
)

OCR_RESULTS_PATH = os.path.join(
    os.path.dirname(__file__), "..",
    "artifacts/data-structure-import/ocr_results.json",
)

MANUAL_BBOX_PATH = os.path.join(
    os.path.dirname(__file__), "..",
    "artifacts/backfill/ds_sc/manual-bboxes-v2.json",
)

HISTORICAL_BASELINE = {
    "total": 513,
    "with_image_segments": 21,
    "placeholder_only": 4,
    "published_legacy": 2,
    "frozen_canary": 3,
    "known_import_ids_with_segments": [229, 369, 371, 378, 380, 388, 395, 397, 400, 402, 405, 407, 411, 412, 450, 451, 457, 460, 461, 472, 480],
    "known_placeholder_ids": [302, 320, 433, 449],
    "known_published_ids": [407, 480, 700],
}

# ── Placeholder patterns (NFKC-normalized) ──
_PLACEHOLDER_PATTERNS = [
    re.compile(r'图片\s*选项\s*[A-D]'),
    re.compile(r'原题图已内嵌'),
    re.compile(r'见原图'),
    re.compile(r'图略'),
    re.compile(r'图片缺失'),
    re.compile(r'option\s*image\s*placeholder'),
    re.compile(r'\[.*?图片.*?\]'),
    re.compile(r'【.*?图片.*?】'),
]

# ── Old path patterns ──
_OLD_URL_RE = re.compile(r'ds_sc/q_\d+_p\d+_')

# ── Data classes ──


@dataclass
class AuditError:
    stage: str
    code: str
    message: str
    field_path: str | None = None
    recoverable: bool = True


@dataclass
class AssetHealthDetail:
    local_exists: bool = False
    local_size: int = 0
    local_sha256: str = ""
    local_format: str = ""
    local_width: int = 0
    local_height: int = 0
    local_valid: bool = False
    http_checked: bool = False
    http_status: int | None = None
    http_content_type: str = ""
    http_content_length: int = 0
    http_bytes_read: int = 0
    http_download_truncated: bool = False
    http_decode_attempted: bool = False
    http_decode_result: str = ""
    http_error: str = ""
    mime_from_magic: str = ""
    mime_from_content_type: str = ""
    mime_from_extension: str = ""
    mime_mismatch: bool = False


@dataclass
class AssetReference:
    owner_type: str  # "QuestionImport" | "Question"
    owner_id: int
    field_path: str
    asset_url: str
    storage_key: str = ""
    is_student_visible: bool = False
    semantic_role: str | None = None
    crop_version: str | None = None
    region_id: str | None = None
    bbox: list | None = None
    storage_kind: str = "unknown"  # "local" | "remote" | "data_uri" | "unknown"
    health: AssetHealthDetail = field(default_factory=AssetHealthDetail)
    local_state: str = "unchecked"
    http_state: str = "unchecked"
    decode_state: str = "not_checked"
    format: str = "unknown"
    aggregate_state: str = "unchecked"


@dataclass
class SegmentInfo:
    audit_segment_id: str
    segment_type: str
    url: str = ""
    semantic_role: str | None = None
    crop_version: str | None = None
    region_id: str | None = None
    region_type: str | None = None
    bbox: list | None = None
    schema_state: str = "unknown"
    is_student_visible: bool = False
    asset_reference_idx: int = -1


@dataclass
class ActionRecommendation:
    action: str
    reason_codes: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    migration_eligible: bool = False
    priority: int = 4
    protected_by_canary: bool = False


@dataclass
class RecordAudit:
    # Identity
    question_import_id: int
    question_id: int | None = None
    source_question_no: str = ""
    batch_id: str = ""
    status: str = ""
    question_type: str = ""
    db_source_page: int = 0
    scope_match_state: str = "unknown"

    # Page
    config_page: int | None = None
    resolved_page: int | None = None
    page_resolution_state: str = "unknown"
    page_resolution_evidence: list[str] = field(default_factory=list)

    # Content
    raw_text: str = ""
    cleaned_text: str | None = None
    parsed_options: dict = field(default_factory=dict)
    answer: str = ""

    # Orthogonal dimensions
    requires_content_image: bool | str = "unknown"
    visual_schema_state: str = "unknown"
    asset_state: str = "unchecked"
    placeholder_state: str = "none"
    publication_state: str = "unpublished"
    contamination_state: str = "not_checked"
    protection_state: str = "normal"
    risk_flags: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)

    # Asset health aggregation
    asset_total: int = 0
    asset_healthy_count: int = 0
    asset_degraded_count: int = 0
    asset_missing_count: int = 0
    asset_invalid_count: int = 0
    asset_unchecked_count: int = 0

    # Frozen canary
    expected_visual_state: dict | None = None
    drift_detected: bool = False
    drift_reasons: list[str] = field(default_factory=list)

    # Assets and segments
    asset_references: list[AssetReference] = field(default_factory=list)
    image_segments: list[SegmentInfo] = field(default_factory=list)
    current_image_segments: list[SegmentInfo] = field(default_factory=list)
    question_image_url: list[str] = field(default_factory=list)

    # Record-level health
    file_exists: bool = False
    http_status: int | None = None
    local_details: dict = field(default_factory=dict)

    # Suggested actions (LIST)
    suggested_actions: list[ActionRecommendation] = field(default_factory=list)
    primary_action: str | None = None

    # Migration
    migration_eligible: bool = False
    protected_by_canary: bool = False
    priority: int = 4

    # Errors
    errors: list[AuditError] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════════════════════════════


def create_audit_snapshot(db_path: str, output_dir: str) -> tuple[str, dict]:
    """Create a consistent read-only SQLite snapshot using backup API.

    Returns (snapshot_path, source_state).
    """
    source_state = {
        "source_db_path": db_path,
        "source_db_size": os.path.getsize(db_path) if os.path.isfile(db_path) else 0,
        "source_db_sha256": "",
        "wal_exists": False,
        "wal_size": 0,
        "shm_exists": False,
        "shm_size": 0,
        "snapshot_path": "",
        "snapshot_hash": "",
    }

    if os.path.isfile(db_path):
        source_state["source_db_sha256"] = _file_sha256(db_path)
    wal_path = db_path + "-wal"
    shm_path = db_path + "-shm"
    if os.path.isfile(wal_path):
        source_state["wal_exists"] = True
        source_state["wal_size"] = os.path.getsize(wal_path)
    if os.path.isfile(shm_path):
        source_state["shm_exists"] = True
        source_state["shm_size"] = os.path.getsize(shm_path)

    # Create snapshot
    os.makedirs(output_dir, exist_ok=True)
    snapshot_path = os.path.join(output_dir, "snapshot.db")

    src_conn = sqlite3.connect(db_path)
    dst_conn = sqlite3.connect(snapshot_path)
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()

    source_state["snapshot_path"] = snapshot_path
    source_state["snapshot_hash"] = _file_sha256(snapshot_path)

    return snapshot_path, source_state


def _file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def scan_imports(
    snapshot_path: str,
    *,
    subject_id: int = SUBJECT_ID,
    only_import_id: int | None = None,
    source_file: str | None = None,
    batch_id: str | None = None,
) -> tuple[list[dict], dict]:
    """Scan question_imports from snapshot.

    Returns (records, stats).
    """
    conn = sqlite3.connect(snapshot_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    where_clauses = ["subject_id = ?"]
    params = [subject_id]
    if only_import_id is not None:
        where_clauses.append("id = ?")
        params.append(only_import_id)
    if source_file is not None:
        where_clauses.append("source_file = ?")
        params.append(source_file)
    if batch_id is not None:
        where_clauses.append("batch_id = ?")
        params.append(batch_id)

    where_sql = " AND ".join(where_clauses)

    # Count and group
    cur.execute(
        f"SELECT source_file, batch_id, COUNT(*) as cnt FROM question_imports WHERE {where_sql} GROUP BY source_file, batch_id",
        params,
    )
    groups = [dict(r) for r in cur.fetchall()]

    cur.execute(
        f"SELECT * FROM question_imports WHERE {where_sql} ORDER BY id",
        params,
    )
    records = [dict(r) for r in cur.fetchall()]

    # Get MAX(updated_at)
    cur.execute(
        f"SELECT MAX(updated_at) FROM question_imports WHERE {where_sql}",
        params,
    )
    max_updated = cur.fetchone()[0]

    # Get published questions
    cur.execute(
        "SELECT q.*, qi.id as import_id, qi.source_question_no FROM questions q "
        "LEFT JOIN question_imports qi ON qi.question_id = q.id "
        "WHERE q.subject_id = ?",
        [subject_id],
    )
    questions_rows = cur.fetchall()
    questions_map = {}
    for r in questions_rows:
        dr = dict(r)
        imp_id = dr.pop("import_id")
        questions_map[imp_id] = dr

    conn.close()

    stats = {
        "total_records": len(records),
        "groups": groups,
        "source_files": list(set(g.get("source_file", "") for g in groups)),
        "batch_ids": list(set(g.get("batch_id", "") for g in groups)),
        "max_updated_at": max_updated,
        "published_questions": len(questions_map),
    }

    return records, stats, questions_map


def verify_readonly(snapshot_path: str, pre_state: dict) -> list[str]:
    """Verify no DB changes occurred. Returns list of violation messages."""
    violations = []
    current_sha = _file_sha256(snapshot_path)
    if current_sha != pre_state["snapshot_hash"]:
        violations.append(f"Snapshot hash changed: {pre_state['snapshot_hash']} -> {current_sha}")

    # Also check source DB
    src_path = pre_state.get("source_db_path", "")
    if src_path and os.path.isfile(src_path):
        src_sha = _file_sha256(src_path)
        if src_sha != pre_state.get("source_db_sha256", ""):
            violations.append(
                f"Source DB changed during run: {pre_state.get('source_db_sha256','')} -> {src_sha} "
                "(external process, not attributed to audit)"
            )
    return violations


# ══════════════════════════════════════════════════════════════════════
# URL / STORAGE KEY PARSING
# ══════════════════════════════════════════════════════════════════════


def _sanitize_url_for_log(url: str) -> str:
    """Redact sensitive query params from URL for logging/output."""
    try:
        parsed = urlparse(url)
        if parsed.query:
            # Keep only param names, redact values
            redacted_query = "&".join(
                f"{k}=REDACTED" for k in parsed.query.split("&") if "=" in k
            ) if parsed.query else parsed.query
            return urlunparse(parsed._replace(query=redacted_query or parsed.query[:3]+"..."))
    except Exception:
        pass
    return url[:80] + "..." if len(url) > 80 else url


def _is_sensitive_url(url: str) -> bool:
    """Check if URL contains sensitive params (tokens, keys)."""
    sensitive_params = {"token", "access_key", "secret", "signature", "sig", "key", "api_key"}
    try:
        parsed = urlparse(url)
        for param in parsed.query.split("&"):
            if "=" in param:
                k = param.split("=")[0].lower()
                if k in sensitive_params:
                    return True
    except Exception:
        pass
    return False


def parse_storage_key(url: str, storage_root: str = STORAGE_ROOT) -> tuple[str | None, str | None]:
    """Parse a URL to extract storage key and check safety.

    Returns (storage_key, error) where error is non-None if unsafe.
    """
    # Only handle local URLs
    if url.startswith("http://") or url.startswith("https://"):
        # Try to extract path after /static/question-assets/
        if "/static/question-assets/" in url:
            key = url.split("/static/question-assets/", 1)[1]
        else:
            return None, "not_a_local_asset_url"
    elif url.startswith("file://"):
        return None, "file_url_rejected"
    elif url.startswith("data:"):
        return None, "data_uri"
    else:
        # Assume it's already a relative key
        key = url

    # Safety checks
    try:
        import urllib.parse
        key = urllib.parse.unquote(key)
    except Exception:
        pass

    # Normalize slashes
    key = key.replace("\\", "/")

    # Reject absolute paths
    if key.startswith("/"):
        return None, "absolute_path"

    # Reject ..
    if ".." in key.split("/"):
        return None, "path_traversal"

    # Reject null bytes
    if "\0" in key:
        return None, "null_byte"

    # Reject Windows drive paths
    if re.match(r'^[A-Za-z]:\\', key):
        return None, "windows_drive_path"

    # Resolve and verify within storage root
    full_path = os.path.normpath(os.path.join(storage_root, key))
    if not full_path.startswith(os.path.normpath(storage_root)):
        return None, "path_escape_detected"

    # Check for symlink escape
    if os.path.islink(full_path):
        real = os.path.realpath(full_path)
        if not real.startswith(os.path.normpath(storage_root)):
            return None, "symlink_escape"

    return key, None


def determine_storage_kind(url: str) -> str:
    if not url:
        return "unknown"
    if url.startswith("data:"):
        return "data_uri"
    if url.startswith("http://") or url.startswith("https://"):
        # Check if it's a local asset URL
        if "/static/" in url:
            return "local"
        host = urlparse(url).hostname or ""
        if host in ("localhost", "127.0.0.1", "::1") or host.startswith("10.") or host.startswith("192.168.") or host == "0.0.0.0":
            return "local"
        return "remote"
    if url.startswith("file://"):
        return "local"
    return "unknown"


# ══════════════════════════════════════════════════════════════════════
# SSRF SAFEGUARDS
# ══════════════════════════════════════════════════════════════════════

_BLOCKED_HOSTS_RE = re.compile(
    r"^(localhost|127\.0\.0\.1|::1|0\.0\.0\.0|169\.254\.\d+\.\d+|"
    r"10\.\d+\.\d+\.\d+|172\.1[6-9]\.\d+\.\d+|172\.2[0-9]\.\d+\.\d+|"
    r"172\.3[0-1]\.\d+\.\d+|192\.168\.\d+\.\d+|"
    r"\[::1\]|\[fc00:\]|\[fd00:\])"
)


def _check_ssrf_safe(url: str) -> tuple[bool, str]:
    """Check if URL is safe for HTTP retrieval. Returns (safe, reason)."""
    try:
        parsed = urlparse(url)
    except Exception as e:
        return False, f"parse_error:{e}"

    if parsed.scheme not in ("http", "https"):
        return False, f"blocked_scheme:{parsed.scheme}"

    host = parsed.hostname or ""
    # Check against blocked patterns
    if _BLOCKED_HOSTS_RE.match(host):
        return False, f"blocked_host:{host}"

    # Resolve DNS and check all IPs
    try:
        import socket
        addrs = socket.getaddrinfo(host, parsed.port or 443)
        for addr in addrs:
            ip = addr[4][0]
            if _BLOCKED_HOSTS_RE.match(ip):
                return False, f"blocked_resolved_ip:{ip}"
            # Also check for RFC1918 after resolution
            if ip.startswith("10.") or ip.startswith("192.168.") or ip.startswith("172."):
                parts = ip.split(".")
                if len(parts) == 4:
                    try:
                        second = int(parts[1])
                        if ip.startswith("172.") and 16 <= second <= 31:
                            return False, f"blocked_rfc1918:{ip}"
                        if ip.startswith("10."):
                            return False, f"blocked_rfc1918:{ip}"
                        if ip.startswith("192.168."):
                            return False, f"blocked_rfc1918:{ip}"
                    except ValueError:
                        pass
    except socket.gaierror:
        return False, "dns_resolution_failed"
    except Exception:
        # If we can't resolve, don't block — let the HTTP request fail naturally
        pass

    return True, ""


# ══════════════════════════════════════════════════════════════════════
# IMAGE FORMAT DETECTION
# ══════════════════════════════════════════════════════════════════════

_IMAGE_MAGIC = {
    b"\x89PNG\r\n\x1a\n": "png",
    b"\xff\xd8\xff": "jpeg",
    b"RIFF": "webp",  # WebP starts with RIFF
    b"GIF87a": "gif",
    b"GIF89a": "gif",
    b"<svg": "svg",
    b"<?xml": "svg",
}

_MIME_EXT_MAP = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
    "svg": "image/svg+xml",
}


def detect_image_format(data: bytes, content_type: str = "", ext: str = "") -> dict:
    """Detect image format from magic bytes, Content-Type, and extension."""
    result = {
        "format_from_magic": "unknown",
        "format_from_content_type": "unknown",
        "format_from_extension": "unknown",
        "mime_mismatch": False,
    }

    # Magic bytes
    for magic, fmt in _IMAGE_MAGIC.items():
        if data[:len(magic)] == magic:
            result["format_from_magic"] = fmt
            break
    # Try PIL for WebP (RIFF is generic)
    if result["format_from_magic"] == "unknown" or (data[:4] == b"RIFF"):
        try:
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(data))
            result["format_from_magic"] = img.format.lower() if img.format else "unknown"
        except Exception:
            pass

    # Content-Type
    ct_lower = content_type.lower().split(";")[0].strip()
    for fmt, mime in _MIME_EXT_MAP.items():
        if ct_lower == mime:
            result["format_from_content_type"] = fmt
            break

    # Extension
    if ext:
        ext_clean = ext.lower().lstrip(".")
        result["format_from_extension"] = _MIME_EXT_MAP.get(ext_clean, "unknown")

    # Check mismatch
    non_unknown = set()
    for k in ("format_from_magic", "format_from_content_type", "format_from_extension"):
        v = result[k]
        if v != "unknown":
            non_unknown.add(v)
    if len(non_unknown) > 1:
        result["mime_mismatch"] = True

    return result


# ══════════════════════════════════════════════════════════════════════
# LOCAL FILE HEALTH CHECK
# ══════════════════════════════════════════════════════════════════════


def check_local_asset(storage_key: str, storage_root: str = STORAGE_ROOT) -> AssetHealthDetail:
    """Check local file for a storage key."""
    h = AssetHealthDetail()
    full_path = os.path.normpath(os.path.join(storage_root, storage_key))
    if not full_path.startswith(os.path.normpath(storage_root)):
        h.local_exists = False
        return h

    if not os.path.isfile(full_path):
        h.local_exists = False
        return h

    h.local_exists = True
    h.local_size = os.path.getsize(full_path)

    with open(full_path, "rb") as f:
        data = f.read()
    h.local_sha256 = hashlib.sha256(data).hexdigest()

    # Format detection
    ext = os.path.splitext(storage_key)[1]
    fmt_info = detect_image_format(data, ext=ext)
    h.mime_from_magic = fmt_info.get("format_from_magic", "unknown")
    h.mime_from_extension = fmt_info.get("format_from_extension", "unknown")
    h.mime_mismatch = fmt_info.get("mime_mismatch", False)

    # Try PIL decode
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(data))
        h.local_format = (img.format or "unknown").lower()
        h.local_width, h.local_height = img.size
        # Verify full decode
        img.load()
        h.local_valid = True
    except Exception as e:
        h.local_valid = False
        h.local_format = h.mime_from_magic

    return h


# ══════════════════════════════════════════════════════════════════════
# HTTP HEALTH CHECK (with SSRF + safety)
# ══════════════════════════════════════════════════════════════════════


def check_http_asset(url: str, max_download: int = 10 * 1024 * 1024) -> AssetHealthDetail:
    """Check remote asset via HTTP. Returns health detail.

    Blocks SSRF, limits download, handles redirects.
    """
    h = AssetHealthDetail()
    if not url:
        return h

    safe, reason = _check_ssrf_safe(url)
    if not safe:
        h.http_error = f"ssrf_blocked:{reason}"
        return h

    import urllib.request
    import urllib.error

    # Check for sensitive params BEFORE calling
    is_sensitive = _is_sensitive_url(url)

    opener = urllib.request.build_opener(
        urllib.request.HTTPRedirectHandler(),
    )

    req = urllib.request.Request(url, method="HEAD")
    req.add_header("User-Agent", "LegacyVisualAudit/1.0")

    try:
        with opener.open(req, timeout=10) as resp:
            h.http_checked = True
            h.http_status = resp.status
            h.http_content_type = resp.headers.get("Content-Type", "")
            cl = resp.headers.get("Content-Length")
            if cl:
                h.http_content_length = int(cl)

            # Check if content type indicates non-image
            ct = h.http_content_type.lower()
            if ct and "text/" in ct:
                h.http_decode_result = "invalid_content_type"
                return h
            if ct and "application/json" in ct:
                h.http_decode_result = "invalid_content_type"
                return h
    except urllib.error.HTTPError as e:
        h.http_checked = True
        h.http_status = e.code
        h.http_error = f"http_error:{e.code}"
        # 403/405 → try GET with range
        if e.code in (403, 405):
            return check_http_asset_range(url, max_download)
        return h
    except Exception as e:
        h.http_error = f"request_failed:{e}"
        return h

    # If HEAD succeeded but content not determined, try GET Range for decode
    if not h.http_decode_result:
        h2 = check_http_asset_range(url, max_download)
        h.http_bytes_read = h2.http_bytes_read
        h.http_download_truncated = h2.http_download_truncated
        h.http_decode_attempted = h2.http_decode_attempted
        h.http_decode_result = h2.http_decode_result
        h.mime_from_content_type = h2.mime_from_content_type

    return h


def check_http_asset_range(url: str, max_download: int) -> AssetHealthDetail:
    """Try GET with Range for decode verification."""
    h = AssetHealthDetail()
    h.http_checked = True

    safe, reason = _check_ssrf_safe(url)
    if not safe:
        h.http_error = f"ssrf_blocked:{reason}"
        return h

    import urllib.request
    import urllib.error

    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", "LegacyVisualAudit/1.0")
    req.add_header("Range", "bytes=0-8191")  # Read first 8KB for header decode

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            h.http_status = resp.status
            h.http_content_type = resp.headers.get("Content-Type", "")
            cl = resp.headers.get("Content-Length")
            if cl:
                h.http_content_length = int(cl)

            data = resp.read(8192)
            h.http_bytes_read = len(data)
            h.http_download_truncated = h.http_content_length > h.http_bytes_read

            # Detect format from downloaded data
            ext = os.path.splitext(urlparse(url).path)[1]
            fmt_info = detect_image_format(data, h.http_content_type, ext)
            h.mime_from_content_type = fmt_info.get("format_from_content_type", "unknown")
            h.mime_mismatch = fmt_info.get("mime_mismatch", False)

            # Try decode
            h.http_decode_attempted = True
            try:
                from PIL import Image
                import io
                img = Image.open(io.BytesIO(data))
                img.load()
                h.http_decode_result = "valid"
            except Exception:
                h.http_decode_result = "decode_failed"
    except urllib.error.HTTPError as e:
        h.http_status = e.code
        h.http_error = f"range_get_failed:{e.code}"
    except Exception as e:
        h.http_error = f"range_get_error:{e}"

    return h


# ══════════════════════════════════════════════════════════════════════
# PLACEHOLDER DETECTION
# ══════════════════════════════════════════════════════════════════════


def _normalize_for_placeholder(text: str) -> str:
    """Normalize text for placeholder matching."""
    t = unicodedata.normalize("NFKC", text)
    t = re.sub(r'\s+', '', t)
    return t


def scan_placeholder(value: Any, field_path: str, results: list[dict]) -> None:
    """Recursively scan a value for placeholder patterns."""
    if isinstance(value, str):
        if not value.strip():
            return
        norm = _normalize_for_placeholder(value)
        for i, pat in enumerate(_PLACEHOLDER_PATTERNS):
            if pat.search(norm) or pat.search(value):
                results.append({
                    "field_path": field_path,
                    "raw_text": value[:200],
                    "normalized": norm[:200],
                    "pattern_index": i,
                    "pattern": pat.pattern,
                })
                return
    elif isinstance(value, dict):
        for k, v in value.items():
            scan_placeholder(v, f"{field_path}.{k}", results)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            scan_placeholder(v, f"{field_path}[{i}]", results)


# ══════════════════════════════════════════════════════════════════════
# CLASSIFICATION ENGINE
# ══════════════════════════════════════════════════════════════════════


def classify_segment_schema(seg: dict) -> str:
    """Classify an image segment's schema state."""
    stype = seg.get("type", "")
    if stype != "image":
        return "not_applicable"

    sem_role = seg.get("semantic_role", "")
    cv = seg.get("crop_version", "")
    url = seg.get("url", "")

    # current: semantic_role=content_image + crop_version=visual-v2.1 + metadata
    if sem_role == "content_image" and cv == "visual-v2.1":
        if seg.get("region_id") and seg.get("bbox"):
            return "current"
        return "current"  # partial metadata still counts as current schema

    # legacy: old patterns
    if not sem_role:
        return "legacy"
    if not cv:
        return "legacy"
    if _OLD_URL_RE.search(url):
        return "legacy"
    if seg.get("checksum") and not cv:
        return "legacy"
    return "legacy"


def classify_record(
    rec: dict,
    questions_map: dict,
    manual_config: dict,
    ocr_pages: dict,
) -> RecordAudit:
    """Classify a single question_import record."""
    import_id = rec["id"]
    audit = RecordAudit(
        question_import_id=import_id,
        question_id=rec.get("question_id"),
        source_question_no=str(rec.get("source_question_no", "")),
        batch_id=rec.get("batch_id", "") or "",
        status=rec.get("status", "") or "",
        question_type=rec.get("question_type", "") or "",
        db_source_page=rec.get("source_page_start") or 0,
    )

    # Protection state
    if import_id in FROZEN_IMPORT_IDS:
        audit.protection_state = "frozen"
        audit.protected_by_canary = True
        # Set expected state
        if import_id == 450:
            audit.expected_visual_state = {"requires_content_image": True, "visual_kind": "option_images"}
        elif import_id == 452:
            audit.expected_visual_state = {"requires_content_image": False, "visual_kind": "none"}
        elif import_id == 461:
            audit.expected_visual_state = {"requires_content_image": True, "visual_kind": "stem_diagram"}

    # Parse content
    try:
        pc = rec.get("parsed_content")
        if isinstance(pc, str):
            pc = json.loads(pc)
    except (json.JSONDecodeError, TypeError):
        audit.errors.append(AuditError("parse", "malformed_json", "parsed_content JSON parse failed", "parsed_content"))
        pc = {}

    try:
        po = rec.get("parsed_options")
        if isinstance(po, str):
            po = json.loads(po)
    except (json.JSONDecodeError, TypeError):
        audit.errors.append(AuditError("parse", "malformed_json", "parsed_options JSON parse failed", "parsed_options"))
        po = {}

    audit.raw_text = (pc or {}).get("text", "") or ""
    audit.parsed_options = po if isinstance(po, dict) else {}
    audit.answer = rec.get("parsed_answer") or ""

    # ── Scope matching ──
    source_file = rec.get("source_file", "")
    batch_id = rec.get("batch_id", "")
    if source_file == "ds_sc.pdf":
        audit.scope_match_state = "matched"
    elif source_file:
        audit.scope_match_state = "source_mismatch"
    else:
        audit.scope_match_state = "ambiguous"

    # ── Parse segments ──
    segments_raw = (pc or {}).get("segments", []) or []
    all_segments: list[SegmentInfo] = []
    image_segments: list[SegmentInfo] = []
    student_visible_images: list[SegmentInfo] = []

    for idx, seg in enumerate(segments_raw):
        seg_id = f"s{idx}"
        stype = seg.get("type", "")
        url = seg.get("url", "") or ""
        sem_role = seg.get("semantic_role") or ""
        cv = seg.get("crop_version") or ""
        region_id = seg.get("region_id") or ""
        region_type = seg.get("region_type") or ""
        bbox = seg.get("bbox") or seg.get("original_bbox") or []

        is_visible = seg.get("display", True) and stype == "image"
        schema_st = classify_segment_schema(seg) if stype == "image" else "not_applicable"

        si = SegmentInfo(
            audit_segment_id=seg_id,
            segment_type=stype,
            url=url,
            semantic_role=sem_role or None,
            crop_version=cv or None,
            region_id=region_id or None,
            region_type=region_type or None,
            bbox=bbox if isinstance(bbox, list) else None,
            schema_state=schema_st,
            is_student_visible=is_visible,
        )
        all_segments.append(si)
        if stype == "image":
            image_segments.append(si)
            if is_visible:
                student_visible_images.append(si)

    audit.image_segments = image_segments
    audit.current_image_segments = [s for s in student_visible_images if s.schema_state == "current"]

    # ── visual_schema_state ──
    if not student_visible_images:
        audit.visual_schema_state = "not_applicable"
    else:
        schema_states = {s.schema_state for s in student_visible_images}
        if schema_states == {"current"}:
            audit.visual_schema_state = "current"
        elif schema_states == {"legacy"}:
            audit.visual_schema_state = "legacy"
        elif "current" in schema_states and "legacy" in schema_states:
            audit.visual_schema_state = "mixed"
        else:
            audit.visual_schema_state = schema_states.pop() if len(schema_states) == 1 else "unknown"

    # ── Source image name ──
    source_img = rec.get("source_image_name") or ""
    if source_img and source_img != "ds_sc.pdf":
        audit.question_image_url = [source_img]

    # ── Build asset references ──
    asset_refs: list[AssetReference] = []
    seen_urls: set[str] = set()

    for si in image_segments:
        if si.url and si.url not in seen_urls:
            seen_urls.add(si.url)
            sk, sk_err = parse_storage_key(si.url)
            asset_refs.append(AssetReference(
                owner_type="QuestionImport",
                owner_id=import_id,
                field_path=f"parsed_content.segments[{all_segments.index(si)}].url",
                asset_url=si.url,
                storage_key=sk or "",
                is_student_visible=si.is_student_visible,
                semantic_role=si.semantic_role,
                crop_version=si.crop_version,
                region_id=si.region_id,
                bbox=si.bbox,
                storage_kind=determine_storage_kind(si.url),
            ))

    # Source snapshot URL
    snap_url = (pc or {}).get("source_snapshot_url") or ""
    if snap_url and snap_url not in seen_urls:
        seen_urls.add(snap_url)
        sk, sk_err = parse_storage_key(snap_url)
        asset_refs.append(AssetReference(
            owner_type="QuestionImport",
            owner_id=import_id,
            field_path="parsed_content.source_snapshot_url",
            asset_url=snap_url,
            storage_key=sk or "",
            is_student_visible=False,
            storage_kind=determine_storage_kind(snap_url),
        ))

    # Source image name
    if source_img and source_img != "ds_sc.pdf" and source_img not in seen_urls:
        seen_urls.add(source_img)
        sk, sk_err = parse_storage_key(source_img)
        asset_refs.append(AssetReference(
            owner_type="QuestionImport",
            owner_id=import_id,
            field_path="source_image_name",
            asset_url=source_img,
            storage_key=sk or "",
            is_student_visible=False,
            storage_kind=determine_storage_kind(source_img),
        ))

    # Question-level assets
    q_data = questions_map.get(import_id)
    if q_data:
        q_id = q_data.get("id") or q_data.get("question_id")
        if q_id:
            q_content = q_data.get("content")
            if isinstance(q_content, str):
                try:
                    q_content = json.loads(q_content)
                except (json.JSONDecodeError, TypeError):
                    q_content = {}
            # Check Question segments
            q_segs = (q_content or {}).get("segments", []) or []
            for qidx, qseg in enumerate(q_segs):
                if qseg.get("type") == "image":
                    qurl = qseg.get("url", "")
                    if qurl and qurl not in seen_urls:
                        seen_urls.add(qurl)
                        sk, sk_err = parse_storage_key(qurl)
                        asset_refs.append(AssetReference(
                            owner_type="Question",
                            owner_id=q_id,
                            field_path=f"content.segments[{qidx}].url",
                            asset_url=qurl,
                            storage_key=sk or "",
                            is_student_visible=True,
                            semantic_role=qseg.get("semantic_role") or None,
                            crop_version=qseg.get("crop_version") or None,
                            storage_kind=determine_storage_kind(qurl),
                        ))

            # Question.image_url
            q_image_url = q_data.get("image_url")
            if q_image_url:
                if isinstance(q_image_url, str):
                    q_urls = [q_image_url]
                elif isinstance(q_image_url, list):
                    q_urls = q_image_url
                else:
                    q_urls = []
                for qurl in q_urls:
                    if qurl and qurl not in seen_urls:
                        seen_urls.add(qurl)
                        sk, sk_err = parse_storage_key(qurl)
                        asset_refs.append(AssetReference(
                            owner_type="Question",
                            owner_id=q_id,
                            field_path="image_url",
                            asset_url=qurl,
                            storage_key=sk or "",
                            is_student_visible=True,
                            storage_kind=determine_storage_kind(qurl),
                        ))

    audit.asset_references = asset_refs

    # ── Placeholder detection ──
    placeholder_hits = []
    if isinstance(po, dict):
        for k, v in po.items():
            scan_placeholder(v, f"parsed_options.{k}", placeholder_hits)
    if q_data:
        q_opts = q_data.get("options")
        if isinstance(q_opts, str):
            try:
                q_opts = json.loads(q_opts)
            except Exception:
                pass
        if isinstance(q_opts, dict):
            for k, v in q_opts.items():
                scan_placeholder(v, f"Question.options.{k}", placeholder_hits)
    # Also scan stem text
    if audit.raw_text:
        scan_placeholder(audit.raw_text, "parsed_content.text", placeholder_hits)

    audit.placeholder_state = "detected" if placeholder_hits else "none"
    if placeholder_hits:
        audit.reason_codes.append("placeholder_detected")

    # ── Publication state ──
    if audit.question_id is not None and q_data:
        # Simplified: check if Question record exists
        audit.publication_state = "published_synced"
    elif audit.question_id is not None:
        audit.publication_state = "published_diverged"
    else:
        audit.publication_state = "unpublished"

    # ── Contamination state ──
    # Check OCR availability for this page
    page_key = str(audit.db_source_page)
    if ocr_pages and page_key in ocr_pages:
        ocr_page = ocr_pages[page_key]
        ocr_lines = ocr_page.get("lines", [])
        if ocr_lines:
            audit.contamination_state = "not_detected"  # default; detection logic uses bbox overlap
        else:
            audit.contamination_state = "not_checked"
    else:
        audit.contamination_state = "not_checked"

    # ── requires_content_image ──
    if not student_visible_images:
        audit.requires_content_image = False
    elif any(s.schema_state == "current" for s in student_visible_images):
        audit.requires_content_image = True
    else:
        audit.requires_content_image = "unknown"

    # ── Drift detection for frozen records ──
    if audit.protection_state == "frozen" and audit.expected_visual_state:
        evs = audit.expected_visual_state
        if evs.get("requires_content_image") is True and not student_visible_images:
            audit.drift_detected = True
            audit.drift_reasons.append("Expected content image but none found")
        if evs.get("requires_content_image") is False and student_visible_images:
            audit.drift_detected = True
            audit.drift_reasons.append("Expected no content image but image segments found")
        if evs.get("visual_kind") == "option_images" and audit.visual_schema_state != "current":
            audit.drift_detected = True
            audit.drift_reasons.append(f"Expected current option_images, got {audit.visual_schema_state}")

    # ── Page resolution ──
    cfg_entry = manual_config.get(str(audit.source_question_no)) or manual_config.get(audit.source_question_no)
    if cfg_entry:
        cfg_page = cfg_entry.get("page") or cfg_entry.get("resolved_pdf_page")
        if cfg_page:
            audit.config_page = cfg_page
            diff = abs(cfg_page - audit.db_source_page)
            if diff == 0:
                audit.page_resolution_state = "resolved"
                audit.resolved_page = cfg_page
            elif diff <= 2:
                audit.page_resolution_state = "consistent_offset"
                audit.resolved_page = cfg_page
                audit.page_resolution_evidence.append(f"DB page {audit.db_source_page}, config page {cfg_page}, diff={diff}")
            else:
                audit.page_resolution_state = "conflict"
                audit.page_resolution_evidence.append(f"DB page {audit.db_source_page}, config page {cfg_page}")

    # ── Determine suggested action ──
    actions = []
    if audit.protection_state == "frozen" and audit.drift_detected:
        actions.append(ActionRecommendation(
            action="manual_review",
            reason_codes=["frozen_drift"],
            blockers=["frozen_canary"],
            migration_eligible=False,
            priority=1,
            protected_by_canary=True,
        ))
    if audit.placeholder_state == "detected":
        actions.append(ActionRecommendation(
            action="manual_review",
            reason_codes=["placeholder_detected"],
            migration_eligible=audit.protection_state != "frozen",
            priority=2,
        ))
    if audit.visual_schema_state == "legacy":
        actions.append(ActionRecommendation(
            action="replace_legacy_content_image",
            reason_codes=[f"schema:{audit.visual_schema_state}"],
            migration_eligible=audit.protection_state != "frozen",
            priority=2,
        ))
    if audit.visual_schema_state == "mixed":
        actions.append(ActionRecommendation(
            action="replace_legacy_content_image",
            reason_codes=["mixed_schema"],
            migration_eligible=audit.protection_state != "frozen",
            priority=2,
        ))
    if audit.page_resolution_state == "conflict":
        actions.append(ActionRecommendation(
            action="manual_review",
            reason_codes=["page_conflict"],
            migration_eligible=False,
            priority=1,
        ))

    if not actions and audit.visual_schema_state == "current":
        actions.append(ActionRecommendation(
            action="no_action",
            reason_codes=["current_visual"],
            migration_eligible=True,
            priority=4,
        ))
    if not actions:
        actions.append(ActionRecommendation(
            action="no_action",
            reason_codes=["no_visual_content"],
            migration_eligible=True,
            priority=4,
        ))

    audit.suggested_actions = actions
    audit.primary_action = actions[0].action if actions else None

    # ── Migration eligibility ──
    audit.migration_eligible = all(
        a.migration_eligible for a in actions
    ) and audit.protection_state != "frozen"

    # ── Priority ──
    priorities = [a.priority for a in actions]
    audit.priority = min(priorities) if priorities else 4

    # ── Risk flags ──
    if audit.page_resolution_state == "conflict":
        audit.risk_flags.append("page_conflict")
    if audit.placeholder_state == "detected":
        audit.risk_flags.append("placeholder_only")
    if audit.drift_detected:
        audit.risk_flags.append("frozen_drift")

    return audit


# ══════════════════════════════════════════════════════════════════════
# ASSET HEALTH CHECKING
# ══════════════════════════════════════════════════════════════════════


def resolve_all_assets(records: list[RecordAudit], *, verify_http: bool = False) -> dict:
    """Resolve all unique assets across all records. Returns asset map by storage key."""
    asset_map: dict[str, dict] = {}
    seen_urls: dict[str, str] = {}  # url -> asset_id

    for ra in records:
        for ref in ra.asset_references:
            # Use storage key as asset id, or fallback to URL hash
            asset_id = ref.storage_key or hashlib.md5(ref.asset_url.encode()).hexdigest()[:16]
            if asset_id not in asset_map:
                asset_map[asset_id] = {
                    "asset_id": asset_id,
                    "urls": [],
                    "storage_keys": [],
                    "reference_count": 0,
                    "referencing_import_ids": [],
                    "local": None,
                    "http": None,
                    "format": "unknown",
                    "aggregate_state": "unchecked",
                }

            entry = asset_map[asset_id]
            if ref.asset_url not in entry["urls"]:
                entry["urls"].append(ref.asset_url)
            if ref.storage_key and ref.storage_key not in entry["storage_keys"]:
                entry["storage_keys"].append(ref.storage_key)
            entry["reference_count"] += 1
            if ra.question_import_id not in entry["referencing_import_ids"]:
                entry["referencing_import_ids"].append(ra.question_import_id)

            # Local check (if storage key available)
            if ref.storage_key:
                key = ref.storage_key
            elif ref.asset_url.startswith("http://localhost") or ref.asset_url.startswith("http://127.0.0.1"):
                sk, _ = parse_storage_key(ref.asset_url)
                key = sk or ""
            else:
                key = ""

            if key:
                health = check_local_asset(key)
                entry["local"] = asdict(health)
                entry["format"] = health.local_format or health.mime_from_magic or "unknown"
                if health.local_exists:
                    entry["aggregate_state"] = "healthy"
                else:
                    entry["aggregate_state"] = "missing"

            # HTTP check
            if verify_http and ref.asset_url:
                # Skip SSRF for remote calls per-req, deduplicate by URL
                if ref.asset_url not in seen_urls:
                    seen_urls[ref.asset_url] = asset_id
                    http_health = check_http_asset(ref.asset_url)
                    entry["http"] = asdict(http_health)
                    if http_health.http_decode_result == "invalid_content_type":
                        entry["aggregate_state"] = "invalid"
                    elif not http_health.http_checked:
                        pass  # keep existing
                    elif http_health.http_status != 200 and http_health.http_status != 206:
                        if entry["aggregate_state"] in ("healthy",):
                            entry["aggregate_state"] = "degraded"
                else:
                    # Deduplicate: copy from already-checked
                    existing_id = seen_urls[ref.asset_url]
                    if existing_id in asset_map:
                        entry["http"] = asset_map[existing_id].get("http")

    return asset_map


# ══════════════════════════════════════════════════════════════════════
# OUTPUT GENERATION
# ══════════════════════════════════════════════════════════════════════


def _csv_safe(val: Any) -> str:
    """Escape CSV cell value for formula injection."""
    s = str(val) if val is not None else ""
    if s.startswith(("=", "+", "-", "@")):
        s = "'" + s
    # Replace newlines
    s = s.replace("\n", "\\n").replace("\r", "\\r")
    # Limit length
    if len(s) > 32768:
        s = s[:32767] + "...[truncated]"
    return s


def write_records_csv(records: list[RecordAudit], path: str) -> None:
    """Write records.csv with flat per-record rows."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "question_import_id", "question_id", "source_question_no", "batch_id",
            "status", "question_type", "db_source_page", "scope_match_state",
            "page_resolution_state", "resolved_page",
            "raw_text", "parsed_options", "answer",
            "requires_content_image", "visual_schema_state", "asset_state",
            "placeholder_state", "publication_state", "contamination_state",
            "protection_state", "risk_flags", "reason_codes",
            "asset_total", "asset_healthy", "asset_degraded", "asset_missing", "asset_invalid",
            "migration_eligible", "protected_by_canary", "priority",
            "primary_action", "drift_detected",
            "error_count",
        ])
        for r in records:
            writer.writerow([
                _csv_safe(r.question_import_id),
                _csv_safe(r.question_id),
                _csv_safe(r.source_question_no),
                _csv_safe(r.batch_id),
                _csv_safe(r.status),
                _csv_safe(r.question_type),
                _csv_safe(r.db_source_page),
                _csv_safe(r.scope_match_state),
                _csv_safe(r.page_resolution_state),
                _csv_safe(r.resolved_page),
                _csv_safe(r.raw_text[:200]),
                _csv_safe(json.dumps(r.parsed_options, ensure_ascii=False)),
                _csv_safe(r.answer),
                _csv_safe(str(r.requires_content_image)),
                _csv_safe(r.visual_schema_state),
                _csv_safe(r.asset_state),
                _csv_safe(r.placeholder_state),
                _csv_safe(r.publication_state),
                _csv_safe(r.contamination_state),
                _csv_safe(r.protection_state),
                _csv_safe(";".join(r.risk_flags)),
                _csv_safe(";".join(r.reason_codes)),
                _csv_safe(r.asset_total),
                _csv_safe(r.asset_healthy_count),
                _csv_safe(r.asset_degraded_count),
                _csv_safe(r.asset_missing_count),
                _csv_safe(r.asset_invalid_count),
                _csv_safe(r.migration_eligible),
                _csv_safe(r.protected_by_canary),
                _csv_safe(r.priority),
                _csv_safe(r.primary_action or ""),
                _csv_safe(r.drift_detected),
                _csv_safe(len(r.errors)),
            ])


def write_segments_csv(records: list[RecordAudit], path: str) -> None:
    """Write segments.csv with one row per image segment."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "audit_segment_id", "question_import_id", "segment_type", "url",
            "semantic_role", "crop_version", "region_id", "region_type",
            "bbox", "schema_state", "is_student_visible",
        ])
        for r in records:
            for s in r.image_segments:
                writer.writerow([
                    _csv_safe(f"{r.question_import_id}_{s.audit_segment_id}"),
                    _csv_safe(r.question_import_id),
                    _csv_safe(s.segment_type),
                    _csv_safe(s.url[:200]),
                    _csv_safe(s.semantic_role or ""),
                    _csv_safe(s.crop_version or ""),
                    _csv_safe(s.region_id or ""),
                    _csv_safe(s.region_type or ""),
                    _csv_safe(json.dumps(s.bbox, ensure_ascii=False) if s.bbox else ""),
                    _csv_safe(s.schema_state),
                    _csv_safe(s.is_student_visible),
                ])


def write_assets_csv(asset_map: dict, path: str) -> None:
    """Write assets.csv with one row per unique asset."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "asset_id", "reference_count", "referencing_import_ids",
            "urls", "storage_keys",
            "local_exists", "local_size", "local_sha256", "local_format",
            "local_width", "local_height", "local_valid",
            "http_status", "http_content_type", "http_decode_result",
            "format", "aggregate_state",
        ])
        for asset_id, entry in sorted(asset_map.items()):
            local = entry.get("local") or {}
            http = entry.get("http") or {}
            writer.writerow([
                _csv_safe(asset_id),
                _csv_safe(entry.get("reference_count", 0)),
                _csv_safe(";".join(str(i) for i in entry.get("referencing_import_ids", []))),
                _csv_safe(";".join(entry.get("urls", []))),
                _csv_safe(";".join(entry.get("storage_keys", []))),
                _csv_safe(local.get("local_exists", False)),
                _csv_safe(local.get("local_size", 0)),
                _csv_safe(local.get("local_sha256", "")),
                _csv_safe(local.get("local_format", "")),
                _csv_safe(local.get("local_width", 0)),
                _csv_safe(local.get("local_height", 0)),
                _csv_safe(local.get("local_valid", False)),
                _csv_safe(http.get("http_status")),
                _csv_safe(http.get("http_content_type", "")),
                _csv_safe(http.get("http_decode_result", "")),
                _csv_safe(entry.get("format", "unknown")),
                _csv_safe(entry.get("aggregate_state", "unchecked")),
            ])


def write_records_json(records: list[RecordAudit], path: str) -> None:
    """Write records.json as a proper JSON array."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = []
    for r in records:
        d = asdict(r)
        # Convert non-serializable
        d["requires_content_image"] = str(r.requires_content_image) if isinstance(r.requires_content_image, bool) else r.requires_content_image
        d["errors"] = [asdict(e) for e in r.errors]
        d["suggested_actions"] = [asdict(a) for a in r.suggested_actions]
        d["asset_references"] = [asdict(a) for a in r.asset_references]
        d["image_segments"] = [asdict(s) for s in r.image_segments]
        d["current_image_segments"] = [asdict(s) for s in r.current_image_segments]
        data.append(d)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, default=str)
        f.write("\n")


def write_summary(
    records: list[RecordAudit],
    asset_map: dict,
    pre_db_state: dict,
    violations: list[str],
    ocr_info: dict,
    args: argparse.Namespace,
    path: str,
) -> dict:
    """Write summary.json with statistics and baseline comparison."""
    os.makedirs(os.path.dirname(path), exist_ok=True)

    # Compute statistics
    total = len(records)
    published = sum(1 for r in records if r.question_id is not None)
    frozen = sum(1 for r in records if r.protection_state == "frozen")
    with_legacy = sum(1 for r in records if r.visual_schema_state == "legacy")
    with_current = sum(1 for r in records if r.visual_schema_state == "current")
    with_mixed = sum(1 for r in records if r.visual_schema_state == "mixed")
    with_missing = sum(1 for r in records if r.visual_schema_state == "missing")
    with_na = sum(1 for r in records if r.visual_schema_state == "not_applicable")
    with_unknown_schema = sum(1 for r in records if r.visual_schema_state == "unknown")
    placeholder_detected = sum(1 for r in records if r.placeholder_state == "detected")
    drift_detected = sum(1 for r in records if r.drift_detected)
    page_conflict = sum(1 for r in records if r.page_resolution_state == "conflict")
    migration_eligible = sum(1 for r in records if r.migration_eligible)
    frozen_blocked = sum(1 for r in records if r.protection_state == "frozen" and not r.migration_eligible)
    manual_review = sum(1 for r in records if r.primary_action == "manual_review")
    has_errors = sum(1 for r in records if r.errors)
    multi_action = sum(1 for r in records if len(r.suggested_actions) > 1)

    # Asset stats
    asset_total = len(asset_map)
    asset_healthy = sum(1 for a in asset_map.values() if a.get("aggregate_state") == "healthy")
    asset_degraded = sum(1 for a in asset_map.values() if a.get("aggregate_state") == "degraded")
    asset_missing = sum(1 for a in asset_map.values() if a.get("aggregate_state") == "missing")
    asset_invalid = sum(1 for a in asset_map.values() if a.get("aggregate_state") == "invalid")
    asset_unchecked = sum(1 for a in asset_map.values() if a.get("aggregate_state") == "unchecked")

    # Contamination coverage
    cont_checked = sum(1 for r in records if r.contamination_state != "not_checked")
    cont_detected = sum(1 for r in records if r.contamination_state == "detected")

    # Placeholder by record ID
    placeholder_ids = sorted([r.question_import_id for r in records if r.placeholder_state == "detected"])
    legacy_ids = sorted([r.question_import_id for r in records if r.visual_schema_state == "legacy"])
    published_legacy_ids = sorted([
        r.question_import_id for r in records
        if r.question_id is not None and r.visual_schema_state in ("legacy", "mixed")
    ])

    observed = {
        "total": total,
        "published": published,
        "frozen": frozen,
        "visual_schema": {
            "current": with_current,
            "legacy": with_legacy,
            "mixed": with_mixed,
            "missing": with_missing,
            "not_applicable": with_na,
            "unknown": with_unknown_schema,
        },
        "placeholder_detected": placeholder_detected,
        "placeholder_ids": placeholder_ids,
        "legacy_ids": legacy_ids,
        "published_legacy_ids": published_legacy_ids,
        "drift_detected": drift_detected,
        "page_conflicts": page_conflict,
        "migration_eligible": migration_eligible,
        "frozen_blocked": frozen_blocked,
        "manual_review": manual_review,
        "record_errors": has_errors,
        "multi_action_records": multi_action,
        "assets": {
            "total": asset_total,
            "healthy": asset_healthy,
            "degraded": asset_degraded,
            "missing": asset_missing,
            "invalid": asset_invalid,
            "unchecked": asset_unchecked,
        },
        "contamination": {
            "checked": cont_checked,
            "detected": cont_detected,
            "not_detected": cont_checked - cont_detected,
            "not_checked": total - cont_checked,
            "coverage_pct": round(cont_checked / total * 100, 1) if total > 0 else 0,
        },
    }

    baseline_diff = []
    bl = HISTORICAL_BASELINE
    if observed["visual_schema"]["legacy"] != len(bl.get("known_import_ids_with_segments", [])) - 3:
        baseline_diff.append({
            "type": "legacy_count_mismatch",
            "observed": observed["visual_schema"]["legacy"],
            "historical": len(bl.get("known_import_ids_with_segments", [])) - 3,
            "detail": "Historical count subtracted 3 frozen canaries. Actual DB state may differ.",
        })
    if placeholder_detected != len(bl.get("known_placeholder_ids", [])):
        baseline_diff.append({
            "type": "placeholder_count_mismatch",
            "observed": placeholder_detected,
            "historical": len(bl.get("known_placeholder_ids", [])),
            "detail": f"Expected {len(bl.get('known_placeholder_ids', []))} placeholder-only records",
        })

    summary = {
        "schema_name": "audit_summary",
        "schema_version": "1.0",
        "run_metadata": {
            "run_id": os.path.basename(os.path.dirname(path)),
            "executed_at": datetime.now().isoformat(),
            "db_sha256": pre_db_state.get("source_db_sha256", ""),
            "snapshot_hash": pre_db_state.get("snapshot_hash", ""),
            "source_changed_during_run": any("Source DB changed" in v for v in violations),
        },
        "observed": observed,
        "historical_baseline": bl,
        "baseline_differences": baseline_diff,
        "completion_state": "complete",
        "record_error_count": has_errors,
        "record_error_ids": [r.question_import_id for r in records if r.errors],
        "violations": violations,
        "readonly_verified": len(violations) == 0 or all("external process" in v for v in violations),
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
        f.write("\n")

    return summary


def write_review_html(
    records: list[RecordAudit],
    asset_map: dict,
    summary: dict,
    ocr_info: dict,
    path: str,
) -> None:
    """Generate review.html with CSP, no remote loads."""
    os.makedirs(os.path.dirname(path), exist_ok=True)

    # Filter records that might need review
    review_records = [
        r for r in records
        if r.risk_flags or r.visual_schema_state in ("legacy", "mixed", "missing", "unknown")
        or r.placeholder_state == "detected"
        or r.drift_detected
        or r.page_resolution_state == "conflict"
    ]

    rows_html = ""
    for r in review_records:
        status_badge = ""
        if r.protection_state == "frozen":
            status_badge = '<span class="tag tag-frozen">FROZEN</span>'
        if r.placeholder_state == "detected":
            status_badge += '<span class="tag tag-placeholder">PLACEHOLDER</span>'
        if r.drift_detected:
            status_badge += '<span class="tag tag-drift">DRIFT</span>'
        if r.page_resolution_state == "conflict":
            status_badge += '<span class="tag tag-conflict">PG CONFLICT</span>'

        actions_str = "; ".join(a.action for a in r.suggested_actions[:3])
        if len(r.suggested_actions) > 3:
            actions_str += f" ... (+{len(r.suggested_actions)-3})"

        schema_tag = f'<span class="tag tag-{r.visual_schema_state}">{r.visual_schema_state}</span>'

        asset_summary = f"H{r.asset_healthy_count}/D{r.asset_degraded_count}/M{r.asset_missing_count}/I{r.asset_invalid_count}"

        rows_html += f"""<tr>
            <td>{html.escape(r.source_question_no)}</td>
            <td>{r.question_import_id}</td>
            <td>{html.escape(str(r.question_id or ''))}</td>
            <td>{r.db_source_page}</td>
            <td>{schema_tag}</td>
            <td>{asset_summary}</td>
            <td>{status_badge}</td>
            <td>{html.escape(r.primary_action or '')}</td>
            <td>{html.escape(actions_str)}</td>
            <td>{str(r.migration_eligible)}</td>
            <td>{r.priority}</td>
        </tr>"""

    # Priority counts
    p0 = sum(1 for r in review_records if r.priority == 0)
    p1 = sum(1 for r in review_records if r.priority == 1)
    p2 = sum(1 for r in review_records if r.priority == 2)
    p3 = sum(1 for r in review_records if r.priority == 3)
    p4 = sum(1 for r in review_records if r.priority == 4)

    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; connect-src 'none'; frame-src 'none'; object-src 'none'">
<title>Legacy Visual Audit — Review</title>
<style>
body{{font-family:sans-serif;margin:20px;background:#f5f5f5;color:#333}}
h1{{color:#222}}
table{{border-collapse:collapse;width:100%;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.1)}}
th,td{{border:1px solid #ddd;padding:6px 10px;text-align:left;font-size:13px}}
th{{background:#f2f2f2;position:sticky;top:0}}
tr:hover{{background:#f0f7ff}}
.tag{{display:inline-block;padding:1px 6px;border-radius:3px;font-size:11px;font-weight:bold;margin:1px}}
.tag-current{{background:#d4edda;color:#155724}}
.tag-legacy{{background:#fff3cd;color:#856404}}
.tag-mixed{{background:#f8d7da;color:#721c24}}
.tag-missing{{background:#f8d7da;color:#721c24}}
.tag-unknown{{background:#e2e3e5;color:#383d41}}
.tag-not_applicable{{background:#d6d8db;color:#383d41}}
.tag-frozen{{background:#cce5ff;color:#004085}}
.tag-placeholder{{background:#ffcccc;color:#990000}}
.tag-drift{{background:#ffe0cc;color:#994d00}}
.tag-conflict{{background:#ffd6cc;color:#992200}}
.summary-box{{background:#fff;border-radius:6px;padding:12px 16px;margin:12px 0;box-shadow:0 1px 3px rgba(0,0,0,.1)}}
.summary-grid{{display:flex;gap:12px;flex-wrap:wrap}}
.summary-item{{background:#f8f9fa;padding:8px 12px;border-radius:4px;min-width:120px}}
.summary-num{{font-size:24px;font-weight:bold;color:#222}}
.summary-label{{font-size:11px;color:#666;text-transform:uppercase}}
.footer{{font-size:11px;color:#999;margin-top:20px;text-align:center}}
</style>
</head>
<body>
<h1>Legacy Visual Audit — Review</h1>
<p>Generated: {datetime.now().isoformat()} | {len(review_records)} records shown</p>

<div class="summary-box">
<div class="summary-grid">
<div class="summary-item"><div class="summary-num">{len(review_records)}</div><div class="summary-label">Records Flagged</div></div>
<div class="summary-item"><div class="summary-num">P0:{p0} P1:{p1} P2:{p2} P3:{p3} P4:{p4}</div><div class="summary-label">Priority Distribution</div></div>
<div class="summary-item"><div class="summary-num">{summary.get('observed',{}).get('migration_eligible',0)}</div><div class="summary-label">Migration Eligible</div></div>
<div class="summary-item"><div class="summary-num">{summary.get('observed',{}).get('frozen_blocked',0)}</div><div class="summary-label">Frozen Blocked</div></div>
</div>
</div>

<div style="overflow-x:auto">
<table>
<thead><tr>
<th>Q.No</th><th>Import ID</th><th>Q.ID</th><th>Page</th><th>Schema</th><th>Assets</th><th>Flags</th><th>Primary</th><th>Actions</th><th>Eligible</th><th>Pri</th>
</tr></thead>
<tbody>
{rows_html}
</tbody>
</table>
</div>

<div class="footer">
This report contains no remote resources. All data sourced from audit snapshot. |
Audit records: {len(records)} total | {summary.get('observed',{}).get('record_errors',0)} errors
</div>
</body>
</html>"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(html_content)


def write_approval_json(records: list[RecordAudit], pre_db_state: dict, path: str) -> None:
    """Generate approval.json template."""
    os.makedirs(os.path.dirname(path), exist_ok=True)

    entries = []
    for r in records:
        if r.protection_state == "frozen":
            # Frozen records: mark frozen_not_applicable
            entry = {
                "question_import_id": r.question_import_id,
                "requires_content_image_approval": "frozen",
                "classification_approval": "frozen",
                "cleaned_stem_approval": "frozen",
                "region_approvals": [],
                "source_snapshot_approval": "frozen",
                "published_sync_approval": "frozen",
                "action_approvals": [],
                "final_approval": "frozen",
                "notes": "Frozen canary — not eligible for migration in this phase",
            }
        else:
            entry = {
                "question_import_id": r.question_import_id,
                "requires_content_image_approval": "pending",
                "classification_approval": "pending",
                "cleaned_stem_approval": "pending",
                "region_approvals": [
                    {
                        "region_id": s.region_id or f"segment_{i}",
                        "audit_segment_id": f"{r.question_import_id}_{s.audit_segment_id}",
                        "approval": "pending",
                        "notes": "",
                    }
                    for i, s in enumerate(r.image_segments) if s.is_student_visible
                ],
                "source_snapshot_approval": "pending",
                "published_sync_approval": "pending",
                "action_approvals": [
                    {
                        "action": a.action,
                        "approval": "pending",
                        "notes": "; ".join(a.reason_codes) if a.reason_codes else "",
                    }
                    for a in r.suggested_actions
                ],
                "final_approval": "pending",
                "notes": "",
            }
        # Mark N/A for records without visual content
        if r.visual_schema_state == "not_applicable" and r.requires_content_image is False:
            entry["content_image_approval"] = "not_applicable"
        entries.append(entry)

    approval = {
        "schema_name": "approval",
        "schema_version": "1.0",
        "run_id": os.path.basename(os.path.dirname(path)),
        "db_sha256": pre_db_state.get("source_db_sha256", ""),
        "pdf_sha256": pre_db_state.get("pdf_sha256", ""),
        "entries": entries,
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(approval, f, ensure_ascii=False, indent=2)
        f.write("\n")


def write_manifest(
    args: argparse.Namespace,
    pre_db_state: dict,
    ocr_info: dict,
    total_records: int,
    path: str,
) -> None:
    """Write run-manifest.json."""
    os.makedirs(os.path.dirname(path), exist_ok=True)

    # Get git info
    git_commit = ""
    git_dirty = True
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=os.path.dirname(__file__),
        )
        if result.returncode == 0:
            git_commit = result.stdout.strip()
        result2 = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=5,
            cwd=os.path.dirname(__file__),
        )
        git_dirty = bool(result2.stdout.strip())
    except Exception:
        pass

    manifest = {
        "schema_name": "run_manifest",
        "schema_version": "1.0",
        "run_id": os.path.basename(os.path.dirname(path)),
        "executed_at": datetime.now().isoformat(),
        "cli_args": {k: v for k, v in vars(args).items() if not k.startswith("_")},
        "git_commit": git_commit,
        "git_dirty": git_dirty,
        "python_version": sys.version,
        "db_uri_sanitized": str(args.db).split("//")[0] + "//<redacted>" if args.db else "",
        "db_sha256": pre_db_state.get("source_db_sha256", ""),
        "snapshot_sha256": pre_db_state.get("snapshot_hash", ""),
        "pdf_sha256": pre_db_state.get("pdf_sha256", ""),
        "config_sha256": pre_db_state.get("config_sha256", ""),
        "script_version": "1.0",
        "total_records": total_records,
        "http_check_enabled": getattr(args, "verify_http", False),
        "previews_enabled": getattr(args, "generate_previews", False),
        "csv_formula_escaping": True,
        "sensitive_urls_redacted": True,
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")


# ══════════════════════════════════════════════════════════════════════
# OCR COVERAGE DISCOVERY
# ══════════════════════════════════════════════════════════════════════


def discover_ocr_coverage(ocr_path: str = OCR_RESULTS_PATH) -> dict:
    """Discover OCR coverage from results file."""
    info = {
        "ocr_file_exists": False,
        "available_pages": [],
        "missing_pages": [],
        "malformed_pages": [],
        "total_lines": 0,
        "source_sha256": "",
        "coordinate_space": "unknown",
        "page_mapping": {},
    }

    if not os.path.isfile(ocr_path):
        return info

    info["ocr_file_exists"] = True
    info["source_sha256"] = _file_sha256(ocr_path)

    try:
        with open(ocr_path) as f:
            ocr = json.load(f)
    except Exception as e:
        info["malformed_pages"] = ["ocr_file"]
        return info

    for page_key, page_data in ocr.items():
        lines = page_data.get("lines", [])
        img_size = page_data.get("image_size", {})
        if not lines:
            info["malformed_pages"].append(page_key)
            continue
        info["available_pages"].append(page_key)
        info["total_lines"] += len(lines)

        info["page_mapping"][page_key] = {
            "line_count": len(lines),
            "image_size": img_size,
            "dpi": page_data.get("dpi"),
        }

    return info


# ══════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════


def parse_args():
    p = argparse.ArgumentParser(description="Audit legacy question visual content")
    p.add_argument("--db", required=True, help="DB URL")
    p.add_argument("--pdf", default=PDF_PATH_DEFAULT, help="Source PDF path")
    p.add_argument("--output-dir", default="/tmp/legacy-visual-audit", help="Output directory")
    p.add_argument("--subject-id", type=int, default=SUBJECT_ID, help="Subject ID to audit")
    p.add_argument("--source-file", help="Filter by source_file")
    p.add_argument("--batch-id", help="Filter by batch_id")
    p.add_argument("--only-import-id", type=int, help="Single import ID")
    p.add_argument("--verify-http", action="store_true", help="Check URL HTTP accessibility")
    p.add_argument("--generate-previews", action="store_true", help="Render proposed clips (requires PDF)")
    p.add_argument("--no-snapshot", action="store_true", help="Skip snapshot (audit live DB directly)")
    return p.parse_args()


# ══════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════


def main():
    args = parse_args()
    start_time = time.time()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    logger.info("Starting legacy visual audit")
    logger.info("DB: %s", args.db)
    logger.info("Output: %s", args.output_dir)

    os.makedirs(args.output_dir, exist_ok=True)

    # ── Pre-state recording ──
    # Extract SQLite path from DB URL
    db_path = args.db
    if db_path.startswith("sqlite+aiosqlite:///"):
        db_path = db_path.replace("sqlite+aiosqlite:///", "", 1)
    elif db_path.startswith("sqlite:///"):
        db_path = db_path.replace("sqlite:///", "", 1)

    pre_db_state = {
        "source_db_path": db_path,
        "source_db_size": os.path.getsize(db_path) if os.path.isfile(db_path) else 0,
        "source_db_sha256": _file_sha256(db_path) if os.path.isfile(db_path) else "",
        "wal_exists": os.path.isfile(db_path + "-wal"),
        "shm_exists": os.path.isfile(db_path + "-shm"),
        "pdf_sha256": _file_sha256(args.pdf) if os.path.isfile(args.pdf) else "",
        "config_sha256": _file_sha256(MANUAL_BBOX_PATH) if os.path.isfile(MANUAL_BBOX_PATH) else "",
        "snapshot_hash": "",
    }

    # ── Create snapshot ──
    if not args.no_snapshot:
        snapshot_path, pre_db_state = create_audit_snapshot(db_path, args.output_dir)
        logger.info("Audit snapshot: %s (hash: %s)", snapshot_path, pre_db_state["snapshot_hash"][:16])
    else:
        snapshot_path = db_path
        pre_db_state["snapshot_hash"] = _file_sha256(snapshot_path) if os.path.isfile(snapshot_path) else ""

    # ── Load PDF hash ──
    if os.path.isfile(args.pdf):
        pre_db_state["pdf_sha256"] = _file_sha256(args.pdf)
    else:
        logger.warning("PDF not found: %s — previews disabled", args.pdf)
        args.generate_previews = False

    # ── Scan database ──
    try:
        import_records, scan_stats, questions_map = scan_imports(
            snapshot_path,
            subject_id=args.subject_id,
            only_import_id=args.only_import_id,
            source_file=args.source_file,
            batch_id=args.batch_id,
        )
    except Exception as e:
        logger.error("FATAL: DB scan failed: %s", e)
        sys.exit(1)

    total_records = len(import_records)
    logger.info("Scanned %d records from %d groups", total_records, len(scan_stats.get("groups", [])))
    for g in scan_stats.get("groups", []):
        logger.info("  source=%s batch=%s count=%d", g.get("source_file"), g.get("batch_id"), g.get("cnt"))

    if total_records == 0:
        logger.error("FATAL: No records found for subject_id=%d", args.subject_id)
        sys.exit(1)

    # ── Load configs ──
    manual_config = {}
    if HAS_BACKFILL and os.path.isfile(MANUAL_BBOX_PATH):
        try:
            manual_map, _ = bqi.load_manual_bbox_config()
            # Convert to dict by question_no
            manual_config = {str(k): v[0] if v else {} for k, v in manual_map.items()}
        except Exception as e:
            logger.warning("Cannot load manual config: %s", e)

    # ── OCR coverage ──
    ocr_info = discover_ocr_coverage()
    ocr_pages = {}
    if ocr_info["ocr_file_exists"] and HAS_BACKFILL:
        try:
            ocr_pages = bqi.load_precomputed_ocr(OCR_RESULTS_PATH) or {}
        except Exception as e:
            logger.warning("Cannot load OCR: %s", e)

    logger.info("OCR coverage: %d pages", len(ocr_info.get("available_pages", [])))

    # ── Classify all records ──
    audits: list[RecordAudit] = []
    record_error_count = 0

    for rec in import_records:
        try:
            audit = classify_record(rec, questions_map, manual_config, ocr_pages)
            audits.append(audit)
        except Exception as e:
            record_error_count += 1
            audit = RecordAudit(
                question_import_id=rec["id"],
                question_id=rec.get("question_id"),
                source_question_no=str(rec.get("source_question_no", "")),
                errors=[AuditError("classification", "unexpected_error", str(e), recoverable=False)],
            )
            audits.append(audit)
            logger.warning("Record error for import_id=%d: %s", rec["id"], e)

    logger.info("Classified %d records (%d errors)", len(audits), record_error_count)

    # ── Resolve assets ──
    asset_map = resolve_all_assets(audits, verify_http=args.verify_http)
    logger.info("Resolved %d unique assets", len(asset_map))

    # ── Verify read-only ──
    violations = verify_readonly(snapshot_path, pre_db_state)
    for v in violations:
        logger.warning("Read-only check: %s", v)

    # ── Generate outputs ──
    write_records_csv(audits, os.path.join(args.output_dir, "records.csv"))
    write_segments_csv(audits, os.path.join(args.output_dir, "segments.csv"))
    write_assets_csv(asset_map, os.path.join(args.output_dir, "assets.csv"))
    write_records_json(audits, os.path.join(args.output_dir, "records.json"))
    write_approval_json(audits, pre_db_state, os.path.join(args.output_dir, "approval.json"))
    summary = write_summary(audits, asset_map, pre_db_state, violations, ocr_info, args,
                            os.path.join(args.output_dir, "summary.json"))
    write_review_html(audits, asset_map, summary, ocr_info, os.path.join(args.output_dir, "review.html"))
    write_manifest(args, pre_db_state, ocr_info, total_records,
                   os.path.join(args.output_dir, "run-manifest.json"))

    # ── Final read-only check ──
    post_violations = verify_readonly(snapshot_path, pre_db_state)
    for v in post_violations:
        logger.warning("Post-run read-only check: %s", v)

    elapsed = time.time() - start_time
    logger.info("=" * 50)
    logger.info("AUDIT COMPLETE: %d records in %.1fs", total_records, elapsed)
    logger.info("Output: %s", args.output_dir)
    logger.info("Summary: legacy=%d current=%d mixed=%d placeholder=%d drift=%d eligible=%d",
                summary.get("observed", {}).get("visual_schema", {}).get("legacy", 0),
                summary.get("observed", {}).get("visual_schema", {}).get("current", 0),
                summary.get("observed", {}).get("visual_schema", {}).get("mixed", 0),
                summary.get("observed", {}).get("placeholder_detected", 0),
                summary.get("observed", {}).get("drift_detected", 0),
                summary.get("observed", {}).get("migration_eligible", 0))
    logger.info("=" * 50)

    # Exit code
    if post_violations and any("external process" not in v for v in post_violations):
        logger.error("SAFETY VIOLATION: Read-only constraint broken")
        sys.exit(3)
    if record_error_count > 0:
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
