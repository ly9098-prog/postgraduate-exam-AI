"""Old results cannot bypass OCR page binding through real artifact restore."""

import hashlib
from pathlib import Path

import pytest

from app.features import pipeline_artifacts as artifacts
from app.features import pipeline_orchestrator as target

STAGES = ("split", "normalize_schema", "repair", "math_detect", "table_detect")


def save_stage(stage, pipeline_id):
    payload = {
        "raw_questions": [{"stem": "synthetic OCR result", "page": 1}],
        "questions": [{"content": "synthetic OCR result", "page": 1}],
        "source_type": "pdf",
    }
    target._save_stage_artifact(pipeline_id, stage, payload)
    files = list(Path(artifacts._ensure_dir(pipeline_id)).glob("*.json"))
    assert len(files) == 1
    return files[0]


@pytest.mark.parametrize("stage", STAGES)
def test_version_three_results_rejected_without_mutating_files_or_resume_state(
    stage, monkeypatch, tmp_path
):
    monkeypatch.setenv("PIPELINE_ARTIFACT_DIR", str(tmp_path))
    pipeline_id = "old-ocr-binding-" + stage
    with monkeypatch.context() as previous:
        previous.setattr(artifacts, "_PIPELINE_SCHEMA_VERSION", "3")
        previous.setattr(
            artifacts, "PIPELINE_VERSION", artifacts._build_pipeline_fingerprint()
        )
        path = save_stage(stage, pipeline_id)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    data = {"sentinel": "retained"}
    completed = ["sentinel"]
    compatible, reason = artifacts.check_artifact_compatibility(pipeline_id, stage)
    restored = target._restore_from_artifacts(pipeline_id, completed, data)
    assert restored == (None, set())
    assert not compatible
    assert "version" in reason.lower()
    assert data == {"sentinel": "retained"}
    assert completed == ["sentinel"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("stage", STAGES)
def test_current_results_still_restore(stage, monkeypatch, tmp_path):
    monkeypatch.setenv("PIPELINE_ARTIFACT_DIR", str(tmp_path))
    pipeline_id = "current-ocr-binding-" + stage
    path = save_stage(stage, pipeline_id)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    data = {}
    restored_stage, skipped = target._restore_from_artifacts(pipeline_id, [], data)
    assert restored_stage == stage
    assert "extract" in skipped
    key = "raw_questions" if stage == "split" else "questions"
    assert len(data[key]) == 1
    assert data[key][0]["page"] == 1
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


def test_real_pass_restore_does_not_skip_extract_for_old_artifact(
    monkeypatch, tmp_path
):
    from types import SimpleNamespace

    from app.features.pipeline_single_pass_checkpoint import restore_pass_artifacts
    from app.features.pipeline_single_pass_loop import skip_pass_stage
    from app.features.pipeline_single_pass_state import resolve_pass_port

    monkeypatch.setenv("PIPELINE_ARTIFACT_DIR", str(tmp_path))
    pipeline_id = "old-ocr-pass-binding"
    with monkeypatch.context() as previous:
        previous.setattr(artifacts, "_PIPELINE_SCHEMA_VERSION", "3")
        previous.setattr(
            artifacts, "PIPELINE_VERSION", artifacts._build_pipeline_fingerprint()
        )
        save_stage("split", pipeline_id)
    state = SimpleNamespace(
        pipeline=SimpleNamespace(pipeline_id=pipeline_id),
        has_resume=True,
        completed_stages=["extract", "split"],
        data={},
        current_name="extract",
    )

    def ports(name):
        return resolve_pass_port(target.__dict__, name)

    restore_pass_artifacts(state, ports=ports)
    assert state.artifact_skipped == set()
    assert state.data == {}
    assert not skip_pass_stage(state, ports=ports)
