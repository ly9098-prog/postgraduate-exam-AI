"""Artifact Fingerprint Compatibility Tests.

Verifies that artifact compatibility checks use the PipelineRunFingerprint
to detect incompatible versions, model changes, and config differences.
"""

from __future__ import annotations

from app.features.pipeline_fingerprint import PipelineRunFingerprint


class TestArtifactFingerprintCompatibility:
    """Compatibility checks using PipelineRunFingerprint."""

    def test_artifact_compatible_when_identical(self):
        """Identical fingerprints on artifact and current pipeline → compatible."""
        fp = PipelineRunFingerprint(
            pipeline_version="v1",
            document_ir_schema_version="1",
            artifact_schema_version="1",
            config_hash="abc123",
        )
        compatible, reasons = fp.is_compatible_with(fp)
        assert compatible
        assert reasons == []

    def test_artifact_rejected_on_pipeline_version_mismatch(self):
        """Different pipeline_version causes rejection."""
        artifact_fp = PipelineRunFingerprint(
            pipeline_version="v1",
            document_ir_schema_version="1",
        )
        current_fp = PipelineRunFingerprint(
            pipeline_version="v2",
            document_ir_schema_version="1",
        )
        compatible, reasons = artifact_fp.is_compatible_with(current_fp)
        assert not compatible
        assert any("pipeline_version" in r for r in reasons)

    def test_artifact_rejected_on_ocr_model_change(self):
        """Different OCR model fingerprint causes rejection."""
        artifact_fp = PipelineRunFingerprint(
            pipeline_version="v1",
            ocr_model_fingerprint="ppocr_v1.6",
        )
        current_fp = PipelineRunFingerprint(
            pipeline_version="v1",
            ocr_model_fingerprint="ppocr_v2.0",
        )
        compatible, reasons = artifact_fp.is_compatible_with(current_fp)
        assert not compatible
        assert any("ocr_model" in r for r in reasons)

    def test_artifact_accepted_with_extra_metadata(self):
        """Extra metadata fields do not cause rejection."""
        artifact_fp = PipelineRunFingerprint(pipeline_version="v1")
        current_fp = PipelineRunFingerprint(
            pipeline_version="v1",
            extra={"new_field": "value"},
        )
        compatible, _ = artifact_fp.is_compatible_with(current_fp)
        assert compatible

    def test_empty_artifact_fingerprint_accepted(self):
        """Empty/unknown artifact fingerprint is accepted (migration path)."""
        artifact_fp = PipelineRunFingerprint()  # empty
        current_fp = PipelineRunFingerprint(pipeline_version="v1")
        compatible, _ = artifact_fp.is_compatible_with(current_fp)
        # Empty fields are not checked
        assert compatible
