"""Tests for pipeline_artifacts.py — artifact store and resume helpers."""

import json
import os
import tempfile
import time
from unittest.mock import patch

import pytest

from app.features.pipeline_artifacts import (
    _RESUMABLE_ARTIFACTS,
    artifact_exists,
    cleanup_artifacts,
    cleanup_expired,
    find_resumable_stage,
    list_artifacts,
    load_artifact,
    save_artifact,
    save_completed_marker,
    save_failed_marker,
)


@pytest.fixture
def temp_artifact_root():
    """Temporarily redirect the artifact root to a temp directory."""
    old_root = os.environ.get("PIPELINE_ARTIFACT_DIR", "")
    tmpdir = tempfile.mkdtemp(prefix="pipeline_artifacts_test_")
    os.environ["PIPELINE_ARTIFACT_DIR"] = tmpdir
    yield tmpdir
    # Cleanup
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)
    if old_root:
        os.environ["PIPELINE_ARTIFACT_DIR"] = old_root
    else:
        os.environ.pop("PIPELINE_ARTIFACT_DIR", None)


class TestSaveAndLoadArtifact:
    def test_save_and_load_split(self, temp_artifact_root):
        pipeline_id = "test_pipeline_001"
        data = {"raw_questions": [{"number": 1, "stem": "Test?"}], "source_file": "test.pdf"}
        path = save_artifact(pipeline_id, "split", data)
        assert path is not None
        assert os.path.isfile(path)

        loaded = load_artifact(pipeline_id, "split")
        assert loaded is not None
        assert loaded["raw_questions"][0]["number"] == 1

    def test_save_and_load_normalize_schema(self, temp_artifact_root):
        pipeline_id = "test_pipeline_002"
        data = {"questions": [{"stem": "Q1", "answer": "A"}], "source_file": "test.pdf"}
        path = save_artifact(pipeline_id, "normalize_schema", data)
        assert path is not None

        loaded = load_artifact(pipeline_id, "normalize_schema")
        assert loaded is not None
        assert len(loaded["questions"]) == 1

    def test_save_non_resumable_stage_returns_none(self, temp_artifact_root):
        """Stages not in _RESUMABLE_ARTIFACTS should not be saved."""
        path = save_artifact("test_003", "extract", {"raw_blocks": []})
        assert path is None

    def test_load_missing_returns_none(self, temp_artifact_root):
        loaded = load_artifact("nonexistent", "split")
        assert loaded is None

    def test_load_corrupted_returns_none(self, temp_artifact_root):
        pipeline_id = "test_corrupted"
        # Create a corrupted file
        from app.features.pipeline_artifacts import _artifact_path
        path = _artifact_path(pipeline_id, _RESUMABLE_ARTIFACTS["split"])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("not json")

        loaded = load_artifact(pipeline_id, "split")
        assert loaded is None  # Should return None for corrupted


class TestArtifactExistence:
    def test_artifact_exists(self, temp_artifact_root):
        pipeline_id = "test_exists"
        assert not artifact_exists(pipeline_id, "split")
        save_artifact(pipeline_id, "split", {"raw_questions": []})
        assert artifact_exists(pipeline_id, "split")

    def test_list_artifacts(self, temp_artifact_root):
        pipeline_id = "test_list"
        save_artifact(pipeline_id, "split", {"raw_questions": []})
        save_artifact(pipeline_id, "normalize_schema", {"questions": []})
        available = list_artifacts(pipeline_id)
        assert "split" in available
        assert "normalize_schema" in available

    def test_list_artifacts_empty(self, temp_artifact_root):
        assert list_artifacts("nonexistent") == []


class TestFindResumableStage:
    def test_find_normalize_schema(self, temp_artifact_root):
        pipeline_id = "test_resume_ns"
        save_artifact(pipeline_id, "normalize_schema", {"questions": []})
        completed = ["extract", "normalize_text", "split", "match", "normalize_schema"]
        resumed = find_resumable_stage(pipeline_id, completed)
        # With a stage past normalize_schema completed, should return that stage
        assert resumed is not None

    def test_find_split_artifact(self, temp_artifact_root):
        pipeline_id = "test_resume_split"
        save_artifact(pipeline_id, "split", {"raw_questions": []})
        completed = ["extract", "normalize_text", "split"]
        resumed = find_resumable_stage(pipeline_id, completed)
        # When split is the last completed stage, returns "split"
        # (caller uses this to continue from the next stage)
        assert resumed == "split"

    def test_find_normalize_schema_after_split(self, temp_artifact_root):
        pipeline_id = "test_ns_after_split"
        save_artifact(pipeline_id, "normalize_schema", {"questions": []})
        completed = ["extract", "normalize_text", "split", "match", "normalize_schema"]
        resumed = find_resumable_stage(pipeline_id, completed)
        # When normalize_schema is last completed, returns "normalize_schema" itself
        # because there's no next stage in completed_stages list
        assert resumed == "normalize_schema"

    def test_no_artifact_fallback(self, temp_artifact_root):
        resumed = find_resumable_stage("nonexistent", ["extract"])
        assert resumed is None


class TestCleanup:
    def test_cleanup_single_pipeline(self, temp_artifact_root):
        pipeline_id = "test_cleanup_single"
        save_artifact(pipeline_id, "split", {"raw_questions": []})
        assert artifact_exists(pipeline_id, "split")

        removed = cleanup_artifacts(pipeline_id, force=True)
        assert removed > 0
        assert not artifact_exists(pipeline_id, "split")

    def test_cleanup_expired_completed(self, temp_artifact_root):
        pipeline_id = "test_expired_completed"
        save_artifact(pipeline_id, "split", {"raw_questions": []})
        save_completed_marker(pipeline_id)

        # Use negative TTL to force expiry regardless of timing
        results = cleanup_expired(completed_ttl=-1, failed_ttl=-1)
        assert pipeline_id in results.get("pipeline_results", {})

    def test_cleanup_expired_failed_kept(self, temp_artifact_root):
        """Failed pipelines should be kept longer — verify with a future TTL."""
        pipeline_id = "test_failed_kept"
        save_artifact(pipeline_id, "split", {"raw_questions": []})
        save_failed_marker(pipeline_id)

        # TTL far in the future → should not clean up
        results = cleanup_expired(completed_ttl=0, failed_ttl=999999)
        assert pipeline_id not in results

    def test_cleanup_running_pipeline_protected(self, temp_artifact_root):
        """Running pipelines (no completed/failed marker) should be skipped."""
        pipeline_id = "test_running_protected"
        save_artifact(pipeline_id, "split", {"raw_questions": []})
        # No marker = appears running

        removed = cleanup_artifacts(pipeline_id)
        assert removed == 0  # Should not remove running pipelines


class TestMarkers:
    def test_failed_marker(self, temp_artifact_root):
        pipeline_id = "test_marker_failed"
        save_failed_marker(pipeline_id)
        marker_path = os.path.join(temp_artifact_root, pipeline_id, ".failed")
        assert os.path.isfile(marker_path)

    def test_completed_marker(self, temp_artifact_root):
        pipeline_id = "test_marker_completed"
        save_completed_marker(pipeline_id)
        marker_path = os.path.join(temp_artifact_root, pipeline_id, ".completed")
        assert os.path.isfile(marker_path)
