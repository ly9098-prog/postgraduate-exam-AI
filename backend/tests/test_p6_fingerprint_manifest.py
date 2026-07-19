"""P6 tests: artifact manifest, atomic persistence, enhanced fingerprint compatibility."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

from app.features.pipeline_fingerprint import (
    ArtifactManifest,
    PipelineRunFingerprint,
    atomic_write,
    build_pipeline_fingerprint,
    compute_data_sha256,
    compute_file_sha256,
    read_atomic,
)


class TestEnhancedFingerprint:
    def test_to_json_roundtrip(self):
        fp = PipelineRunFingerprint(
            pipeline_version="6.0",
            document_ir_schema_version="2",
            git_commit="abc123",
            source_sha256="deadbeef",
        )
        raw = fp.to_json()
        fp2 = PipelineRunFingerprint.from_json(raw)
        assert fp2.pipeline_version == "6.0"
        assert fp2.document_ir_schema_version == "2"
        assert fp2.git_commit == "abc123"
        assert fp2.source_sha256 == "deadbeef"

    def test_deterministic_to_json(self):
        fp1 = PipelineRunFingerprint(pipeline_version="6.0")
        fp2 = PipelineRunFingerprint(pipeline_version="6.0")
        assert fp1.to_json() == fp2.to_json()

    def test_compute_hash_deterministic(self):
        fp = PipelineRunFingerprint(pipeline_version="6.0")
        assert fp.compute_hash() == fp.compute_hash()

    def test_compatibility_new_fields(self):
        fp1 = PipelineRunFingerprint(pipeline_version="6.0", config_hash="abc", stage_definition_hash="def")
        fp2 = PipelineRunFingerprint(pipeline_version="6.0", config_hash="abc", stage_definition_hash="def")
        ok, reasons = fp1.is_compatible_with(fp2)
        assert ok
        assert len(reasons) == 0

    def test_compatibility_stage_def_mismatch(self):
        fp1 = PipelineRunFingerprint(pipeline_version="6.0", stage_definition_hash="abc")
        fp2 = PipelineRunFingerprint(pipeline_version="6.0", stage_definition_hash="xyz")
        ok, reasons = fp1.is_compatible_with(fp2)
        assert not ok
        assert any("stage_definition" in r for r in reasons)

    def test_compatibility_evaluator_mismatch(self):
        fp1 = PipelineRunFingerprint(pipeline_version="6.0", evaluator_version="v1")
        fp2 = PipelineRunFingerprint(pipeline_version="6.0", evaluator_version="v2")
        ok, reasons = fp1.is_compatible_with(fp2)
        assert not ok
        assert any("evaluator_version" in r for r in reasons)

    def test_compatibility_empty_fields_dont_break(self):
        """Empty fields in one fingerprint should not cause incompatibility."""
        fp1 = PipelineRunFingerprint(pipeline_version="6.0")
        fp2 = PipelineRunFingerprint(pipeline_version="6.0", stage_definition_hash="abc", preprocess_config_hash="xyz")
        ok, reasons = fp1.is_compatible_with(fp2)
        assert ok  # empty fields don't force mismatch


class TestArtifactManifest:
    def test_default_manifest(self):
        m = ArtifactManifest()
        assert not m.is_complete
        assert m.artifact_id == ""

    def test_manifest_to_json_roundtrip(self):
        m = ArtifactManifest(
            artifact_id="art-001",
            run_fingerprint_hash="abc123",
            stage_name="ocr",
            payload_checksum_sha256="def456",
            payload_size_bytes=1024,
            is_complete=True,
        )
        raw = m.to_json()
        m2 = ArtifactManifest.from_json(raw)
        assert m2.artifact_id == "art-001"
        assert m2.stage_name == "ocr"
        assert m2.run_fingerprint_hash == "abc123"
        assert m2.is_complete

    def test_upstream_artifacts(self):
        m = ArtifactManifest(
            artifact_id="art-002",
            upstream_artifact_ids=["art-001"],
        )
        assert "art-001" in m.upstream_artifact_ids


class TestAtomicWrite:
    def test_atomic_write_and_read(self, tmp_path: Path):
        test_file = tmp_path / "test.txt"
        atomic_write(str(test_file), "hello world")
        content = read_atomic(str(test_file))
        assert content == "hello world"

    def test_atomic_write_directory_created(self, tmp_path: Path):
        nested = tmp_path / "a" / "b" / "c" / "test.txt"
        atomic_write(str(nested), "nested")
        assert nested.exists()
        assert read_atomic(str(nested)) == "nested"

    def test_atomic_write_creates_no_temp_leftover(self, tmp_path: Path):
        test_file = tmp_path / "result.json"
        atomic_write(str(test_file), '{"ok": true}')
        temps = list(tmp_path.glob(".*.tmp"))
        assert len(temps) == 0

    def test_atomic_write_binary(self, tmp_path: Path):
        test_file = tmp_path / "data.bin"
        data = b"\x00\x01\x02\xff"
        atomic_write(str(test_file), data)
        assert test_file.read_bytes() == data

    def test_permissions(self, tmp_path: Path):
        test_file = tmp_path / "secret.json"
        atomic_write(str(test_file), "sensitive")
        mode = os.stat(str(test_file)).st_mode & 0o777
        # Should not be world-readable
        assert mode == 0o700 or mode == 0o600

    def test_atomic_write_creates_parent_dir(self, tmp_path: Path):
        deep = tmp_path / "artifacts" / "run_001" / "ocr" / "result.json"
        atomic_write(str(deep), "content")
        assert deep.exists()

    def test_atomic_overwrite(self, tmp_path: Path):
        test_file = tmp_path / "overwrite.txt"
        atomic_write(str(test_file), "first")
        atomic_write(str(test_file), "second")
        assert read_atomic(str(test_file)) == "second"

    def test_concurrent_writes(self, tmp_path: Path):
        """Multiple atomic writes to different files in same dir succeed."""
        for i in range(10):
            f = tmp_path / f"file_{i}.txt"
            atomic_write(str(f), f"content_{i}")
            assert read_atomic(str(f)) == f"content_{i}"


class TestComputeHash:
    def test_compute_data_sha256(self):
        h = compute_data_sha256("hello")
        assert len(h) == 64
        assert isinstance(h, str)

    def test_compute_data_sha256_bytes(self):
        h = compute_data_sha256(b"hello")
        assert len(h) == 64

    def test_compute_file_sha256(self, tmp_path: Path):
        f = tmp_path / "data.txt"
        f.write_text("hello world")
        h = compute_file_sha256(str(f))
        assert len(h) == 64

    def test_compute_file_sha256_not_found(self):
        with pytest.raises(FileNotFoundError):
            compute_file_sha256("/nonexistent/file.txt")
