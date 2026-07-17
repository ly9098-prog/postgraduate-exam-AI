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
from typing import Any


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

    # Git state
    git_commit: str = ""
    git_dirty: bool = False

    # Python environment
    python_version: str = ""
    python_executable: str = ""

    # OCR configuration
    ocr_backend: str = ""
    ocr_model_fingerprint: str = ""
    preprocessing_fingerprint: str = ""
    ocr_use_gpu: bool = False
    ocr_use_process_pool: bool = False

    # Quality gate versions
    quality_gate_versions: dict[str, str] = field(default_factory=dict)

    # Pipeline module versions
    reading_order_version: str = ""
    numbering_parser_version: str = ""
    config_hash: str = ""

    # Additional metadata
    extra: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    def compute_hash(self) -> str:
        """Deterministic hash of all fingerprint fields."""
        raw = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def is_compatible_with(self, other: PipelineRunFingerprint) -> tuple[bool, list[str]]:
        """Check compatibility with another fingerprint.

        Returns (compatible, reasons) where reasons lists incompatible fields.
        Compatible means all version/pipeline-critical fields match.
        """
        reasons: list[str] = []
        if self.pipeline_version and other.pipeline_version and self.pipeline_version != other.pipeline_version:
            reasons.append(f"pipeline_version mismatch: {self.pipeline_version} vs {other.pipeline_version}")
        if self.document_ir_schema_version and other.document_ir_schema_version and self.document_ir_schema_version != other.document_ir_schema_version:
            reasons.append(f"document_ir_schema mismatch: {self.document_ir_schema_version} vs {other.document_ir_schema_version}")
        if self.artifact_schema_version and other.artifact_schema_version and self.artifact_schema_version != other.artifact_schema_version:
            reasons.append(f"artifact_schema mismatch: {self.artifact_schema_version} vs {other.artifact_schema_version}")
        if self.ocr_model_fingerprint and other.ocr_model_fingerprint and self.ocr_model_fingerprint != other.ocr_model_fingerprint:
            reasons.append(f"ocr_model mismatch: {self.ocr_model_fingerprint[:8]}... vs {other.ocr_model_fingerprint[:8]}...")
        if self.config_hash and other.config_hash and self.config_hash != other.config_hash:
            reasons.append(f"config_hash mismatch: {self.config_hash} vs {other.config_hash}")
        return len(reasons) == 0, reasons


def build_pipeline_fingerprint(
    *,
    pipeline_version: str = "",
    ocr_backend: str = "paddleocr",
    ocr_model_fingerprint: str = "",
    preprocessing_fingerprint: str = "",
    ocr_use_gpu: bool = False,
    ocr_use_process_pool: bool = False,
    **extra: str,
) -> PipelineRunFingerprint:
    """Build a PipelineRunFingerprint from available context.

    Attempts to auto-detect git state, Python version, etc.
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
        # Hash all settings values (sorted keys for determinism)
        settings_dict = {
            k: str(v) for k, v in sorted(settings.model_dump().items())
        }
        config_hash = hashlib.sha256(
            json.dumps(settings_dict, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:16]
    except Exception:
        pass

    numbering_parser_version = ""
    try:
        from app.features import question_numbering
        numbering_parser_version = getattr(question_numbering, "__version__", "1.0")
    except Exception:
        pass

    return PipelineRunFingerprint(
        pipeline_version=pipeline_version,
        document_ir_schema_version="1",
        artifact_schema_version="1",
        git_commit=git_commit,
        git_dirty=git_dirty,
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        python_executable=sys.executable,
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
