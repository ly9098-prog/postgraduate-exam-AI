"""Pipeline Run Fingerprint — unified run metadata for artifact traceability.

The fingerprint captures all relevant state for a pipeline execution,
enabling accurate artifact compatibility checks and run reproducibility.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_RESUME_KEY_PREFIX = "pipeline_resume:"


# ---------------------------------------------------------------------------
# PipelineRunFingerprint
# ---------------------------------------------------------------------------


@dataclass
class PipelineRunFingerprint:
    """Unified pipeline run fingerprint for artifact traceability.

    All fields must be populated at pipeline start. Fingerprint is
    included in all major artifacts: OCR output, DocumentIR, Reading Order,
    Structure Freeze, Cross-page Links, Quality Gate Shadow, Bench reports.

    Compatibility checks use the full fingerprint, not just schema version.
    """

    # Version identifiers
    pipeline_version: str = ""
    document_ir_schema_version: str = ""
    artifact_schema_version: str = ""
    stage_definition_hash: str = ""

    # Source content
    source_sha256: str = ""          # SHA-256 of the source file(s)
    source_page_range: str = ""      # e.g. "1-10"
    immutable_options_hash: str = "" # hash of frozen pipeline options

    # Git state
    git_commit: str = ""
    git_dirty: bool = False

    # Python / dependency environment
    python_version: str = ""
    python_executable: str = ""
    dependency_lock_hash: str = ""   # SHA-256 of requirements*.txt / lock file

    # OCR configuration
    ocr_backend: str = ""
    ocr_model_fingerprint: str = ""
    ocr_weights_digest: str = ""
    preprocessing_fingerprint: str = ""
    ocr_use_gpu: bool = False
    ocr_use_process_pool: bool = False

    # Adapter & evaluator versions
    adapter_config_version: str = ""
    adapter_secret_hmac: str = ""    # HMAC of secret (not the secret itself)
    evaluator_version: str = ""      # CandidateEvaluator version
    quality_gate_versions: dict[str, str] = field(default_factory=dict)
    rule_versions: dict[str, str] = field(default_factory=dict)

    # Pipeline module versions
    reading_order_version: str = ""
    numbering_parser_version: str = ""
    config_hash: str = ""
    preprocess_config_hash: str = ""

    # Deployment
    deployment_backend: str = ""     # e.g. "local_process", "paddlex_http", "docker"
    runtime_platform: str = ""       # e.g. "linux/amd64"

    # Additional metadata
    extra: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    def compute_hash(self) -> str:
        """Deterministic hash of all fingerprint fields."""
        raw = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def is_compatible_with(self, other: PipelineRunFingerprint) -> tuple[bool, list[str]]:
        """Check compatibility with another fingerprint.

        Returns (compatible, reasons) where reasons lists incompatible fields.
        Compatible means all version/pipeline-critical fields match.
        """
        reasons: list[str] = []

        _pairs = [
            ("pipeline_version", self.pipeline_version, other.pipeline_version),
            ("document_ir_schema", self.document_ir_schema_version, other.document_ir_schema_version),
            ("artifact_schema", self.artifact_schema_version, other.artifact_schema_version),
            ("stage_definition", self.stage_definition_hash, other.stage_definition_hash),
            ("ocr_model", self.ocr_model_fingerprint, other.ocr_model_fingerprint),
            ("config_hash", self.config_hash, other.config_hash),
            ("preprocess_config", self.preprocess_config_hash, other.preprocess_config_hash),
            ("evaluator_version", self.evaluator_version, other.evaluator_version),
            ("dependency_lock", self.dependency_lock_hash, other.dependency_lock_hash),
        ]
        for label, a, b in _pairs:
            if a and b and a != b:
                reasons.append(f"{label} mismatch: {a[:12]}... vs {b[:12]}...")

        return len(reasons) == 0, reasons

    def to_json(self) -> str:
        """JSON serialization with sorted keys for deterministic output."""
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False, indent=2, default=str)

    @classmethod
    def from_json(cls, raw: str) -> PipelineRunFingerprint:
        """Deserialize from JSON."""
        data = json.loads(raw)
        return cls(**{k: data[k] for k in data if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# ArtifactManifest
# ---------------------------------------------------------------------------


@dataclass
class ArtifactManifest:
    """Machine-verifiable artifact manifest.

    Every pipeline artifact (OCR output, DocumentIR, frozen structures, etc.)
    carries a manifest file alongside the payload data.
    """

    # Identity
    artifact_id: str = ""
    run_fingerprint_hash: str = ""       # PipelineRunFingerprint.compute_hash()
    stage_name: str = ""
    stage_version: str = ""

    # Payload integrity
    payload_checksum_sha256: str = ""    # SHA-256 of the artifact payload
    payload_size_bytes: int = 0
    payload_schema_version: str = ""

    # Provenance
    created_at: str = ""                 # ISO 8601 timestamp
    upstream_artifact_ids: list[str] = field(default_factory=list)

    # Idempotency
    completion_key: str = ""             # Enables idempotent writes
    is_complete: bool = False

    def to_json(self) -> str:
        return json.dumps(dataclasses.asdict(self), sort_keys=True, ensure_ascii=False, indent=2, default=str)

    @classmethod
    def from_json(cls, raw: str) -> ArtifactManifest:
        data = json.loads(raw)
        return cls(**{k: data[k] for k in data if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Atomic file writer
# ---------------------------------------------------------------------------


def atomic_write(path: str | Path, content: str | bytes, *, mode: int = 0o700) -> None:
    """Atomically write content to *path*.

    Writes to a unique tempfile in the same directory, flushes, fsyncs,
    then ``os.replace()`` (atomic rename on POSIX).  The target directory
    is created if it does not exist.

    The default *mode* (0o700) ensures artifact contents are never
    world-readable.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(content, str):
        content_bytes = content.encode("utf-8")
    else:
        content_bytes = content

    tmp = path.parent / f".{path.name}.{os.getpid()}.tmp"
    try:
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        try:
            os.write(fd, content_bytes)
            os.fsync(fd)      # flush kernel buffer to disk
        finally:
            os.close(fd)

        os.replace(str(tmp), str(path))

        # fsync parent directory for durability (POSIX)
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


def read_atomic(path: str | Path) -> str:
    """Read content written by ``atomic_write``."""
    return Path(path).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Build helper
# ---------------------------------------------------------------------------


def compute_file_sha256(path: str | Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def compute_data_sha256(data: str | bytes) -> str:
    """Compute SHA-256 hex digest of a string or bytes."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def build_pipeline_fingerprint(
    *,
    pipeline_version: str = "",
    ocr_backend: str = "paddleocr",
    ocr_model_fingerprint: str = "",
    preprocessing_fingerprint: str = "",
    ocr_use_gpu: bool = False,
    ocr_use_process_pool: bool = False,
    source_path: str | Path | None = None,
    **extra: str,
) -> PipelineRunFingerprint:
    """Build a PipelineRunFingerprint from available context.

    Attempts to auto-detect git state, Python version, dependency lock, etc.
    Missing values are left as empty strings rather than guessed.
    """
    git_commit = ""
    git_dirty = False
    try:
        import subprocess
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            git_commit = result.stdout.strip()
        result2 = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=5,
        )
        git_dirty = bool(result2.stdout.strip())
    except Exception:
        pass

    config_hash = ""
    try:
        from app.core.config import settings
        settings_dict = {
            k: str(v) for k, v in sorted(settings.model_dump().items())
        }
        config_hash = hashlib.sha256(
            json.dumps(settings_dict, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:16]
    except Exception:
        pass

    source_sha256 = ""
    if source_path:
        try:
            source_sha256 = compute_file_sha256(source_path)
        except Exception:
            pass

    numbering_parser_version = ""
    try:
        from app.features import question_numbering
        numbering_parser_version = getattr(question_numbering, "__version__", "1.0")
    except Exception:
        pass

    dependency_lock_hash = ""
    _lock_paths = ["requirements.txt", "Pipfile.lock", "poetry.lock"]
    for lp in _lock_paths:
        try:
            dependency_lock_hash = compute_file_sha256(lp)
            break
        except Exception:
            continue

    return PipelineRunFingerprint(
        pipeline_version=pipeline_version,
        document_ir_schema_version="1",
        artifact_schema_version="1",
        source_sha256=source_sha256,
        git_commit=git_commit,
        git_dirty=git_dirty,
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        python_executable=sys.executable,
        dependency_lock_hash=dependency_lock_hash,
        ocr_backend=ocr_backend,
        ocr_model_fingerprint=ocr_model_fingerprint,
        preprocessing_fingerprint=preprocessing_fingerprint,
        ocr_use_gpu=ocr_use_gpu,
        ocr_use_process_pool=ocr_use_process_pool,
        quality_gate_versions={
            "QuestionStructureQualityGate": "1.0",
            "CodeQualityGate": "1.0",
            "PlainTextQualityGate": "1.0",
        },
        reading_order_version="1",
        numbering_parser_version=numbering_parser_version,
        config_hash=config_hash,
        extra=extra,
    )


def component_fingerprint(
    module_name: str,
    module_version: str = "",
    *,
    config_hash: str | None = None,
) -> str:
    """Generate a deterministic component fingerprint.

    Combines ``module_name + module_version + config_hash`` into a SHA256 hash.
    Uses ``PipelineRunFingerprint.config_hash`` when not explicitly provided.

    All Adapter ``component_fingerprint`` fields must use this function,
    not hand-written version strings.
    """
    if not config_hash:
        try:
            from app.core.config import settings
            settings_dict = {
                k: str(v) for k, v in sorted(settings.model_dump().items())
            }
            config_hash = hashlib.sha256(
                json.dumps(settings_dict, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()[:16]
        except Exception:
            config_hash = "unknown"

    raw = f"{module_name}::{module_version}::{config_hash}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
