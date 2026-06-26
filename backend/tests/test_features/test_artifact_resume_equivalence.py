"""P0-2: Artifact resume equivalence tests.

Proves canonical(full_run) == canonical(resume_from_artifact(stage))
for normalize_schema and repair artifacts.

Uses deterministic fake stage functions and compares business-relevant
output (questions, counts) after filtering runtime-only fields.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
from unittest.mock import MagicMock

import pytest

from app.features.pipeline_orchestrator import (
    ImportPipeline,
    PipelineStage,
    _restore_from_artifacts,
    _save_stage_artifact,
)

# ---------------------------------------------------------------------------
# Deterministic fake stage outputs
# ---------------------------------------------------------------------------

_FAKE_QUESTIONS = [
    {
        "number": 1,
        "raw_question_text": "1. Test question A?",
        "has_options": True,
        "option_lines": {"A": "opt1", "B": "opt2", "C": "opt3"},
        "is_frozen": False,
        "risk_flags": [],
    },
    {
        "number": 2,
        "raw_question_text": "2. Test question B?",
        "has_options": True,
        "option_lines": {"A": "opt_a", "B": "opt_b"},
        "is_frozen": False,
        "risk_flags": ["code_uncertain"],
    },
]


def _fake_extract(**kw) -> dict:
    return {
        "raw_blocks": [{"page": 1, "block_index": 0, "text": "fake text"}],
        "extracted": 1,
    }


def _fake_normalize_text(**kw) -> dict:
    return {
        "normalized_blocks": [
            {"page": 1, "block_index": 0, "text": "fake", "normalized_text": "fake"},
        ],
    }


def _fake_split(**kw) -> dict:
    return {
        "raw_questions": copy.deepcopy(_FAKE_QUESTIONS),
        "split_count": len(_FAKE_QUESTIONS),
    }


def _fake_match(**kw) -> dict:
    return {
        "matched": [],
        "unmatched": list(range(1, len(_FAKE_QUESTIONS) + 1)),
        "matched_count": 0,
    }


def _fake_normalize_schema(**kw) -> dict:
    return {
        "questions": copy.deepcopy(_FAKE_QUESTIONS),
        "normalized_count": len(_FAKE_QUESTIONS),
    }


def _fake_noop_stage(**kw) -> dict:
    qs = copy.deepcopy(kw.get("questions", _FAKE_QUESTIONS))
    return {"questions": qs}


def _fake_review(**kw) -> dict:
    return {
        "batch_id": "REVIEW_test",
        "written": len(kw.get("questions", _FAKE_QUESTIONS)),
        "skipped": 0,
        "total": len(kw.get("questions", _FAKE_QUESTIONS)),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _canonical(data: dict) -> dict:
    """Extract business-relevant fields, filtering runtime-only values.

    Only compares questions (structure, risk_flags, options) — NOT
    stats dict, which is assembled differently in full vs resume runs.
    """
    questions = data.get("questions", [])
    canonical_qs = []
    for q in questions:
        canonical_qs.append({
            "number": q.get("number"),
            "raw_question_text": q.get("raw_question_text"),
            "has_options": q.get("has_options"),
            "option_lines": q.get("option_lines"),
            "risk_flags": q.get("risk_flags"),
            "is_frozen": q.get("is_frozen", False),
        })
    return {
        "question_count": len(canonical_qs),
        "questions": canonical_qs,
    }


def _make_pipeline(artifact_dir: str) -> ImportPipeline:
    """Create an ImportPipeline with deterministic fake stages."""
    pipeline = ImportPipeline()
    pipeline.pipeline_id = "test_artifact_resume"
    pipeline.stages.clear()
    os.environ["PIPELINE_ARTIFACT_DIR"] = artifact_dir

    stage_specs = [
        ("extract", _fake_extract),
        ("normalize_text", _fake_normalize_text),
        ("split", _fake_split),
        ("match", _fake_match),
        ("normalize_schema", _fake_normalize_schema),
        ("code_language_noise_clean", _fake_noop_stage),
        ("code_structure_reconstruct", _fake_noop_stage),
        ("classify_questions", _fake_noop_stage),
        ("batch_validation", _fake_noop_stage),
        ("batch_dedup", _fake_noop_stage),
        ("repair", _fake_noop_stage),
        ("ai_validation", _fake_noop_stage),
        ("similarity_match", _fake_noop_stage),
        ("math_detect", _fake_noop_stage),
        ("table_detect", _fake_noop_stage),
        ("review", _fake_review),
    ]
    for name, fn in stage_specs:
        stage = PipelineStage(name, fn)
        pipeline.stages[name] = stage

    pipeline.options = {
        "enable_code_language_noise_clean": True,
        "enable_code_structure_reconstruct": True,
        "enable_ai_repair": True,
        "enable_similarity_match": True,
        "enable_math_detect": True,
        "enable_table_detect": True,
        "enable_batch_dedup": True,
    }
    return pipeline


def _run_pipeline_to(pipeline, up_to_stage: str | None = None) -> dict:
    """Run pipeline stages up to (and including) up_to_stage, saving artifacts.

    If up_to_stage is None, runs all stages.
    """
    data = {}
    for name, stage in pipeline.stages.items():
        stage.status = "running"
        result = stage.fn(**data)
        if isinstance(result, dict):
            data.update(result)
        stage.status = "completed"
        _save_stage_artifact(pipeline.pipeline_id, name, data)
        if name == up_to_stage:
            break
    return data


def _run_full_pipeline(pipeline) -> dict:
    """Run all stages and save artifacts."""
    return _run_pipeline_to(pipeline, up_to_stage=None)


def _run_resume_from_artifact(pipeline, resume_stage: str) -> dict:
    """Restore from artifact, run remaining stages."""
    data = {}
    completed_stages = []

    restored, skipped = _restore_from_artifacts(
        pipeline.pipeline_id, completed_stages, data,
    )
    assert restored is not None, (
        f"No artifact found to resume from (expected {resume_stage})"
    )

    for name, stage in pipeline.stages.items():
        if name in skipped:
            stage.status = "completed"
            completed_stages.append(name)
            continue
        stage.status = "running"
        result = stage.fn(**data)
        if isinstance(result, dict):
            data.update(result)
        stage.status = "completed"
        completed_stages.append(name)
        _save_stage_artifact(pipeline.pipeline_id, name, data)
    return data


# ================================================================
# Tests
# ================================================================


class TestArtifactResumeEquivalence:
    """Prove full_run == resume_from_artifact for normalize_schema and repair."""

    @pytest.fixture(autouse=True)
    def setup_artifact_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_val = os.environ.pop("PIPELINE_ARTIFACT_DIR", None)
            os.environ["PIPELINE_ARTIFACT_DIR"] = tmpdir
            yield tmpdir
            if old_val is not None:
                os.environ["PIPELINE_ARTIFACT_DIR"] = old_val
            else:
                os.environ.pop("PIPELINE_ARTIFACT_DIR", None)

    # ── 1. full_run == resume(normalize_schema) ──
    def test_full_run_equals_resume_normalize_schema(self):
        artifact_dir = os.environ["PIPELINE_ARTIFACT_DIR"]

        # Full run: run all stages
        full = _make_pipeline(artifact_dir)
        full_data = _run_full_pipeline(full)
        full_canonical = _canonical(full_data)

        # Resume: run pipeline only to normalize_schema to create artifact,
        # then create a NEW pipeline and resume from it
        seed = _make_pipeline(artifact_dir)
        _run_pipeline_to(seed, "normalize_schema")

        resume = _make_pipeline(artifact_dir)
        resume_data = _run_resume_from_artifact(resume, "normalize_schema")
        resume_canonical = _canonical(resume_data)

        assert full_canonical == resume_canonical, (
            f"Resume from normalize_schema differs from full run.\n"
            f"Full: {json.dumps(full_canonical, indent=2, ensure_ascii=False)}\n"
            f"Resume: {json.dumps(resume_canonical, indent=2, ensure_ascii=False)}"
        )

    # ── 2. full_run == resume(repair) ──
    def test_full_run_equals_resume_repair(self):
        artifact_dir = os.environ["PIPELINE_ARTIFACT_DIR"]

        full = _make_pipeline(artifact_dir)
        full_data = _run_full_pipeline(full)
        full_canonical = _canonical(full_data)

        seed = _make_pipeline(artifact_dir)
        _run_pipeline_to(seed, "repair")

        resume = _make_pipeline(artifact_dir)
        resume_data = _run_resume_from_artifact(resume, "repair")
        resume_canonical = _canonical(resume_data)

        assert full_canonical == resume_canonical, (
            f"Resume from repair differs from full run.\n"
            f"Full: {json.dumps(full_canonical, indent=2, ensure_ascii=False)}\n"
            f"Resume: {json.dumps(resume_canonical, indent=2, ensure_ascii=False)}"
        )

    # ── 3. Resume from normalize_schema runs code_language_noise_clean ──
    def test_resume_normalize_schema_runs_noise_clean(self):
        artifact_dir = os.environ["PIPELINE_ARTIFACT_DIR"]

        # Create normalize_schema artifact
        seed = _make_pipeline(artifact_dir)
        _run_pipeline_to(seed, "normalize_schema")

        # Resume and spy on code_language_noise_clean
        pipeline = _make_pipeline(artifact_dir)
        run_log = []
        original_fn = pipeline.stages["code_language_noise_clean"].fn

        def _spy_noise(**kw):
            run_log.append("code_language_noise_clean")
            return original_fn(**kw)

        pipeline.stages["code_language_noise_clean"].fn = _spy_noise

        _run_resume_from_artifact(pipeline, "normalize_schema")

        assert "code_language_noise_clean" in run_log, (
            "code_language_noise_clean was skipped during resume from normalize_schema!"
        )

    # ── 4. Resume from repair runs ai_validation and similarity_match ──
    def test_resume_repair_runs_validation_and_similarity(self):
        artifact_dir = os.environ["PIPELINE_ARTIFACT_DIR"]

        # Create repair artifact
        seed = _make_pipeline(artifact_dir)
        _run_pipeline_to(seed, "repair")

        # Resume and spy
        pipeline = _make_pipeline(artifact_dir)
        run_log = []

        def _make_spy(name, original_fn):
            def spy(**kw):
                run_log.append(name)
                return original_fn(**kw)
            return spy

        for sn in ("ai_validation", "similarity_match"):
            pipeline.stages[sn].fn = _make_spy(
                sn, pipeline.stages[sn].fn
            )

        _run_resume_from_artifact(pipeline, "repair")

        assert "ai_validation" in run_log, (
            "ai_validation was skipped during resume from repair!"
        )
        assert "similarity_match" in run_log, (
            "similarity_match was skipped during resume from repair!"
        )

    # ── 5. Version mismatch rejects artifact ──
    def test_version_mismatch_rejects_artifact(self):
        import app.features.pipeline_artifacts as pa

        artifact_dir = os.environ["PIPELINE_ARTIFACT_DIR"]
        pid = "test_version_mismatch"

        _make_pipeline(artifact_dir)
        pa.save_artifact(pid, "normalize_schema", {"questions": _FAKE_QUESTIONS})

        original_version = pa.PIPELINE_VERSION
        try:
            pa.PIPELINE_VERSION = "999"
            compatible, reason = pa.check_artifact_compatibility(
                pid, "normalize_schema"
            )
            assert not compatible, "Version mismatch should reject artifact"
            assert "version" in reason.lower(), (
                f"Expected version-related reason, got: {reason}"
            )
        finally:
            pa.PIPELINE_VERSION = original_version

    # ── 6. Corrupted artifact → safe fallback (None, no crash) ──
    def test_corrupted_artifact_loads_as_none(self):
        from app.features.pipeline_artifacts import (
            _artifact_path,
            _ensure_dir,
            artifact_exists,
            load_artifact,
        )

        pid = "test_corrupted"
        _ensure_dir(pid)
        path = _artifact_path(pid, "normalize_schema.json")
        with open(path, "w") as f:
            f.write("not valid json {{{")

        result = load_artifact(pid, "normalize_schema")
        assert result is None, "Corrupted artifact should return None"
        assert not artifact_exists(pid, "normalize_schema"), (
            "Corrupted artifact should be cleaned up"
        )

    # ── 7. No artifact → (None, empty_set) ──
    def test_no_artifact_no_resume(self):
        pipeline = _make_pipeline(os.environ["PIPELINE_ARTIFACT_DIR"])

        restored, skipped = _restore_from_artifacts(
            pipeline.pipeline_id, [], {},
        )
        assert restored is None, "No restore when no artifacts exist"
        assert skipped == set(), "Expected empty skipped set"
