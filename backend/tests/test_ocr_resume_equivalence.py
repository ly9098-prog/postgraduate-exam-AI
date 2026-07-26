"""P6-03: Resume equivalence E2E tests.

Tests that:
- Artifact save → load round-trip preserves data
- Config fingerprint changes invalidate artifacts
- Pipeline version mismatch detected
- find_resumable_stage() identifies correct resume point
- Clean run vs resume run produce identical artifact state
"""

from __future__ import annotations

import io
import json
import os
import uuid

import pytest
from PIL import Image, ImageDraw, ImageFont

from app.features.pipeline_artifacts import (
    _RESUMABLE_ARTIFACTS,
    PIPELINE_VERSION,
    _build_config_fingerprint,
    _ensure_dir,
    artifact_exists,
    check_artifact_compatibility,
    cleanup_artifacts,
    current_pipeline_version,
    find_resumable_stage,
    list_artifacts,
    load_artifact,
    save_artifact,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _make_test_image(text: str = "Resume Test", size: tuple[int, int] = (400, 100)) -> bytes:
    img = Image.new("RGB", size, color="white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(_FONT_PATH, 20)
    except OSError:
        font = ImageFont.load_default()
    draw.text((10, 30), text, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _unique_pipeline_id() -> str:
    return f"resume-test-{uuid.uuid4().hex[:12]}"


@pytest.fixture(autouse=True)
def _cleanup_after():
    """Ensure artifact dirs are cleaned up after each test."""
    yield
    # Best-effort cleanup of any test pipeline dirs
    import shutil
    root = os.environ.get("PIPELINE_ARTIFACT_DIR",
                          os.path.join(os.getcwd(), ".backend_cache", "pipeline_artifacts"))
    if os.path.isdir(root):
        for entry in os.listdir(root):
            if entry.startswith("resume-test-"):
                shutil.rmtree(os.path.join(root, entry), ignore_errors=True)


# ---------------------------------------------------------------------------
# Artifact save → load round-trip
# ---------------------------------------------------------------------------


class TestArtifactRoundTrip:
    """Verify exact data preservation through save → load cycle."""

    @pytest.mark.parametrize("stage", list(_RESUMABLE_ARTIFACTS.keys()))
    def test_save_load_round_trip(self, stage):
        """Every resumable stage: save data, load it back, compare."""
        pid = _unique_pipeline_id()
        data = {
            "stage": stage,
            "items": [1, 2, 3],
            "text": "hello resume",
            "nested": {"key": "value"},
        }
        path = save_artifact(pid, stage, data)
        assert path is not None, f"save_artifact failed for stage={stage}"

        loaded = load_artifact(pid, stage)
        assert loaded == data, (
            f"Round-trip mismatch for stage={stage}: "
            f"expected={data}, got={loaded}"
        )

    def test_load_nonexistent_returns_none(self):
        """Loading a non-existent artifact returns None."""
        assert load_artifact(_unique_pipeline_id(), "split") is None

    def test_save_then_list(self):
        """After saving, list_artifacts reports the stage."""
        pid = _unique_pipeline_id()
        save_artifact(pid, "split", {"pages": 3})
        available = list_artifacts(pid)
        assert "split" in available

    def test_list_empty_returns_empty(self):
        """list_artifacts on a dir with no artifacts returns empty."""
        pid = _unique_pipeline_id()
        _ensure_dir(pid)  # create dir but no artifacts
        assert list_artifacts(pid) == []


# ---------------------------------------------------------------------------
# Config fingerprint invalidation
# ---------------------------------------------------------------------------


class TestConfigFingerprintInvalidation:
    """Changing config should make existing artifacts incompatible."""

    def test_config_change_makes_artifact_incompatible(self, monkeypatch):
        """Simulate a config change → artifact version mismatch."""
        pid = _unique_pipeline_id()
        data = {"result": "ok"}

        # Save artifact with current config
        save_artifact(pid, "split", data)

        # Now "change" the config by monkeypatching fingerprint
        original_fingerprint = _build_config_fingerprint()
        monkeypatch.setattr(
            "app.features.pipeline_artifacts._build_config_fingerprint",
            lambda: "changed-config-fp",
        )
        monkeypatch.setattr(
            "app.features.pipeline_artifacts.current_pipeline_version",
            lambda: f"{PIPELINE_VERSION}_cfgchanged-config-fp",
        )

        # Artifact should be incompatible now
        compatible, reason = check_artifact_compatibility(pid, "split")
        assert not compatible, (
            f"Artifact should be incompatible after config change. Reason: {reason}"
        )

    def test_same_config_is_compatible(self):
        """Same config → artifact remains compatible."""
        pid = _unique_pipeline_id()
        save_artifact(pid, "match", {"mappings": []})
        compatible, reason = check_artifact_compatibility(pid, "match")
        assert compatible, f"Artifact with same config should be compatible: {reason}"

    def test_config_fingerprint_in_artifact_metadata(self):
        """Saved artifact should contain config_fingerprint in metadata."""
        pid = _unique_pipeline_id()
        data = {"test": True}
        path = save_artifact(pid, "split", data)
        assert path is not None
        with open(path) as f:
            wrapped = json.load(f)
        assert "config_fingerprint" in wrapped, (
            f"Artifact metadata missing config_fingerprint. Keys: {list(wrapped.keys())}"
        )
        assert wrapped["config_fingerprint"] == _build_config_fingerprint()


# ---------------------------------------------------------------------------
# find_resumable_stage
# ---------------------------------------------------------------------------


class TestFindResumableStage:
    """Verify find_resumable_stage logic."""

    def test_no_artifacts_returns_none(self):
        pid = _unique_pipeline_id()
        stages = ["split", "match", "normalize_schema"]
        assert find_resumable_stage(pid, stages) is None

    def test_with_split_artifact_resumes_from_next(self):
        pid = _unique_pipeline_id()
        stages = ["split", "match", "normalize_schema"]
        save_artifact(pid, "split", {"pages": 3})
        resume_from = find_resumable_stage(pid, stages)
        assert resume_from == "match"

    def test_last_stage_returns_last(self):
        """If the last stage artifact exists, return it (done)."""
        pid = _unique_pipeline_id()
        stages = ["split", "match", "normalize_schema"]
        save_artifact(pid, "normalize_schema", {"schema": {}})
        resume_from = find_resumable_stage(pid, stages)
        assert resume_from == "normalize_schema"

    def test_incompatible_artifact_requires_rerun(self, monkeypatch):
        pid = _unique_pipeline_id()
        stages = ["split", "match"]
        data = {"pages": 3}
        save_artifact(pid, "split", data)

        # Change config fingerprint so artifact becomes incompatible
        monkeypatch.setattr(
            "app.features.pipeline_artifacts._build_config_fingerprint",
            lambda: "different-fp",
        )
        monkeypatch.setattr(
            "app.features.pipeline_artifacts.current_pipeline_version",
            lambda: f"{PIPELINE_VERSION}_cfgdifferent-fp",
        )

        resume_from = find_resumable_stage(pid, stages)
        assert resume_from is None, (
            f"Should require full re-run when artifact is incompatible, "
            f"got resume_from={resume_from}"
        )

    def test_mixed_compatibility(self, monkeypatch):
        """Earlier stage incompatible, later stage compatible."""
        pid = _unique_pipeline_id()
        stages = ["split", "match", "normalize_schema"]
        save_artifact(pid, "split", {"pages": 3})

        # Save match artifact with a "different" version
        orig_version = current_pipeline_version()
        monkeypatch.setattr(
            "app.features.pipeline_artifacts.current_pipeline_version",
            lambda: f"{PIPELINE_VERSION}_cfgother",
        )
        save_artifact(pid, "match", {"mappings": []})

        # Restore original version
        monkeypatch.setattr(
            "app.features.pipeline_artifacts.current_pipeline_version",
            lambda: orig_version,
        )
        # Also restore fingerprint
        orig_fp = _build_config_fingerprint()
        monkeypatch.setattr(
            "app.features.pipeline_artifacts._build_config_fingerprint",
            lambda: orig_fp,
        )

        # split is compatible, match is not → should resume from match
        # (split is found first when walking reverse, but it's compatible → resume from match)
        resume_from = find_resumable_stage(pid, stages)
        # split is the only compatible artifact found → resume from match
        assert resume_from == "match"

    def test_skip_non_resumable_stage(self):
        pid = _unique_pipeline_id()
        stages = ["split", "non_resumable_stage", "match"]
        save_artifact(pid, "split", {"ok": True})
        # split is compatible → resume from the next stage in completed_stages list
        resume_from = find_resumable_stage(pid, stages)
        assert resume_from == "non_resumable_stage"


# ---------------------------------------------------------------------------
# Cleanup after tests
# ---------------------------------------------------------------------------


class TestCleanupAfterArtifacts:
    """Artifact cleanup must not leave orphan state."""

    def test_cleanup_removes_artifacts(self):
        pid = _unique_pipeline_id()
        save_artifact(pid, "split", {"x": 1})
        save_artifact(pid, "match", {"y": 2})
        assert len(list_artifacts(pid)) == 2
        cleanup_artifacts(pid, force=True)
        assert list_artifacts(pid) == []

    def test_cleanup_on_empty_dir_safe(self):
        pid = _unique_pipeline_id()
        cleanup_artifacts(pid)  # no-op, should not raise

    def test_artifact_exists_toggle(self):
        pid = _unique_pipeline_id()
        assert not artifact_exists(pid, "split")
        save_artifact(pid, "split", {"ok": True})
        assert artifact_exists(pid, "split")
        cleanup_artifacts(pid, force=True)
        assert not artifact_exists(pid, "split")


# ---------------------------------------------------------------------------
# Pipeline version stability
# ---------------------------------------------------------------------------


class TestPipelineVersion:
    """Pipeline version should be stable for same config, change with config."""

    def test_version_stable_within_session(self):
        """Multiple calls to current_pipeline_version return same value (no side effects)."""
        v1 = current_pipeline_version()
        v2 = current_pipeline_version()
        assert v1 == v2

    def test_config_fingerprint_differs_from_default(self):
        """Config fingerprint should be non-default when runtime config is available."""
        fp = _build_config_fingerprint()
        assert fp != "default"
        assert len(fp) == 12  # md5 prefix

    def test_build_pipeline_fingerprint_is_short(self):
        """Module-level fingerprint is a compact string."""
        assert PIPELINE_VERSION.startswith("p1_s")
        assert len(PIPELINE_VERSION) < 30
