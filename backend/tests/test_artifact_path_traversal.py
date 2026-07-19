"""Tests for artifact path traversal safety (S0-08)."""

from __future__ import annotations

import os
import tempfile

import pytest

from app.features.pipeline_artifacts import (
    _RESUMABLE_ARTIFACTS,
    _SAFE_ID_RE,
    _artifact_path,
    _safe_artifact_dir,
    _validate_pipeline_id,
)


class TestPipelineIdValidation:
    """Verify _validate_pipeline_id rejects path traversal patterns."""

    _INVALID_IDS = [
        "../../etc/passwd",
        "../foo",
        "a/b/c",
        "",
        ".",
        "..",
        "foo/bar",
        "/etc/passwd",
        "foo\\bar",
        "a\nb",
    ]

    _VALID_IDS = [
        "abc123",
        "ABC-123_def",
        "pipeline-2026-07-19",
        "single",
    ]

    def test_rejects_path_traversal(self):
        for pid in self._INVALID_IDS:
            with pytest.raises(ValueError):
                _validate_pipeline_id(pid)

    def test_accepts_safe_ids(self):
        for pid in self._VALID_IDS:
            assert _validate_pipeline_id(pid) == pid

    def test_regex_matches_validation(self):
        """Verify the regex pattern matches _validate_pipeline_id behavior."""
        for pid in self._INVALID_IDS:
            assert not _SAFE_ID_RE.match(pid), (
                f"_SAFE_ID_RE should reject {pid!r}"
            )
        for pid in self._VALID_IDS:
            assert _SAFE_ID_RE.match(pid), (
                f"_SAFE_ID_RE should accept {pid!r}"
            )


class TestSafeArtifactDir:
    """Verify _safe_artifact_dir prevents path traversal."""

    def test_safe_id_within_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_root = os.environ.get("PIPELINE_ARTIFACT_DIR")
            os.environ["PIPELINE_ARTIFACT_DIR"] = tmp
            try:
                d = _safe_artifact_dir("valid-id")
                assert d.startswith(os.path.realpath(tmp))
            finally:
                if old_root is None:
                    del os.environ["PIPELINE_ARTIFACT_DIR"]
                else:
                    os.environ["PIPELINE_ARTIFACT_DIR"] = old_root

    def test_traversal_id_rejected(self):
        with pytest.raises(ValueError, match="Unsafe pipeline_id"):
            _safe_artifact_dir("../../etc/passwd")

    def test_slash_id_rejected(self):
        with pytest.raises(ValueError, match="Unsafe pipeline_id"):
            _safe_artifact_dir("a/b")


class TestArtifactPathFilename:
    """Verify filename-based traversal is not possible through public API."""

    def test_public_api_uses_dict_lookup(self):
        """All public functions use _RESUMABLE_ARTIFACTS dict, not raw filenames."""
        for filename in _RESUMABLE_ARTIFACTS.values():
            assert "../" not in filename
            assert filename == os.path.basename(filename)

    def test_direct_artifact_path_with_traversal_filename(self):
        """_artifact_path rejects filenames with path separators."""
        with tempfile.TemporaryDirectory() as tmp:
            old_root = os.environ.get("PIPELINE_ARTIFACT_DIR")
            os.environ["PIPELINE_ARTIFACT_DIR"] = tmp
            try:
                with pytest.raises(ValueError, match="Unsafe filename"):
                    _artifact_path("safe-id", "../../etc/passwd")
            finally:
                if old_root is None:
                    del os.environ["PIPELINE_ARTIFACT_DIR"]
                else:
                    os.environ["PIPELINE_ARTIFACT_DIR"] = old_root


class TestResumableArtifactsSafe:
    """Verify _RESUMABLE_ARTIFACTS contains only safe paths."""

    def test_no_resumable_artifact_is_a_path(self):
        for stage_name, filename in _RESUMABLE_ARTIFACTS.items():
            assert "/" not in filename, (
                f"Filename for {stage_name} contains path separator: {filename!r}"
            )
            assert "\\" not in filename, (
                f"Filename for {stage_name} contains backslash: {filename!r}"
            )
            assert filename == os.path.basename(filename), (
                f"Filename for {stage_name} is not a bare name: {filename!r}"
            )
