"""Pipeline Fingerprint Tests.

Verifies PipelineRunFingerprint construction, serialization,
compatibility checking, and artifact usage.
"""

from __future__ import annotations

from app.features.pipeline_fingerprint import (
    PipelineRunFingerprint,
    build_pipeline_fingerprint,
)


class TestPipelineRunFingerprint:
    """PipelineRunFingerprint fields and serialization."""

    def test_default_fingerprint(self):
        fp = PipelineRunFingerprint()
        d = fp.to_dict()
        assert isinstance(d, dict)
        assert "pipeline_version" in d
        assert "git_commit" in d
        assert "ocr_backend" in d
        assert "config_hash" in d

    def test_compute_hash_deterministic(self):
        fp1 = PipelineRunFingerprint(pipeline_version="v1")
        fp2 = PipelineRunFingerprint(pipeline_version="v1")
        assert fp1.compute_hash() == fp2.compute_hash()

    def test_different_version_different_hash(self):
        fp1 = PipelineRunFingerprint(pipeline_version="v1")
        fp2 = PipelineRunFingerprint(pipeline_version="v2")
        assert fp1.compute_hash() != fp2.compute_hash()

    def test_fingerprint_to_dict(self):
        fp = PipelineRunFingerprint(
            pipeline_version="v1",
            ocr_backend="paddleocr",
            config_hash="abc123",
        )
        d = fp.to_dict()
        assert d["pipeline_version"] == "v1"
        assert d["ocr_backend"] == "paddleocr"


class TestFingerprintCompatibility:
    """Compatibility checks between fingerprints."""

    def test_identical_fingerprints_compatible(self):
        fp = PipelineRunFingerprint(
            pipeline_version="v1",
            document_ir_schema_version="1",
            artifact_schema_version="1",
            config_hash="abc",
        )
        compatible, reasons = fp.is_compatible_with(fp)
        assert compatible
        assert reasons == []

    def test_same_version_compatible(self):
        fp1 = PipelineRunFingerprint(
            pipeline_version="v1",
            document_ir_schema_version="1",
            config_hash="abc",
        )
        fp2 = PipelineRunFingerprint(
            pipeline_version="v1",
            document_ir_schema_version="1",
            config_hash="abc",
        )
        compatible, reasons = fp1.is_compatible_with(fp2)
        assert compatible

    def test_config_hash_mismatch_incompatible(self):
        fp1 = PipelineRunFingerprint(
            pipeline_version="v1",
            config_hash="abc",
        )
        fp2 = PipelineRunFingerprint(
            pipeline_version="v1",
            config_hash="def",
        )
        compatible, reasons = fp1.is_compatible_with(fp2)
        assert not compatible
        assert any("config_hash" in r for r in reasons)

    def test_different_pipeline_version_incompatible(self):
        fp1 = PipelineRunFingerprint(
            pipeline_version="v1",
            document_ir_schema_version="1",
        )
        fp2 = PipelineRunFingerprint(
            pipeline_version="v2",
            document_ir_schema_version="1",
        )
        compatible, reasons = fp1.is_compatible_with(fp2)
        assert not compatible
        assert any("pipeline_version" in r for r in reasons)

    def test_different_ocr_model_incompatible(self):
        fp1 = PipelineRunFingerprint(
            pipeline_version="v1",
            ocr_model_fingerprint="model_a_v1",
        )
        fp2 = PipelineRunFingerprint(
            pipeline_version="v1",
            ocr_model_fingerprint="model_b_v2",
        )
        compatible, reasons = fp1.is_compatible_with(fp2)
        assert not compatible
        assert any("ocr_model" in r for r in reasons)

    def test_empty_fields_do_not_cause_incompatibility(self):
        fp1 = PipelineRunFingerprint(pipeline_version="v1")
        fp2 = PipelineRunFingerprint()  # empty pipeline_version
        compatible, _ = fp1.is_compatible_with(fp2)
        # Empty fields are not checked
        assert compatible


class TestBuildFingerprint:
    """build_pipeline_fingerprint utility."""

    def test_build_with_defaults(self):
        fp = build_pipeline_fingerprint()
        assert isinstance(fp, PipelineRunFingerprint)
        d = fp.to_dict()
        assert "python_version" in d
        assert "python_executable" in d

    def test_build_with_ocr_params(self):
        fp = build_pipeline_fingerprint(
            pipeline_version="v1",
            ocr_backend="paddleocr_vl",
            ocr_use_gpu=False,
        )
        assert fp.pipeline_version == "v1"
        assert fp.ocr_backend == "paddleocr_vl"
        assert fp.ocr_use_gpu is False

    def test_build_includes_config_hash(self):
        fp = build_pipeline_fingerprint()
        # config_hash should be populated (settings module available)
        assert fp.config_hash != ""

    def test_build_includes_quality_gate_versions(self):
        fp = build_pipeline_fingerprint()
        assert "QuestionStructureQualityGate" in fp.quality_gate_versions
