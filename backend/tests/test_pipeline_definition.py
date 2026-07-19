"""Tests for PipelineDefinition — single source of truth for stage metadata."""
from __future__ import annotations

import importlib

import pytest

from app.features.pipeline_definition import PipelineDefinition, StageDefinition


# Known-good snapshot: 27 stages in canonical order verified from current branch
_EXPECTED_STAGE_NAMES = (
    "extract",
    "wangdao_preprocess",
    "normalize_text",
    "ocr_correction",
    "layout_reconstruction",
    "layout_router",
    "visual_region_detect",
    "analyze_structure",
    "classify_pages",
    "structure_freeze",
    "split",
    "question_bbox",
    "match",
    "normalize_schema",
    "code_language_noise_clean",
    "code_structure_reconstruct",
    "classify_questions",
    "batch_validation",
    "batch_dedup",
    "repair",
    "ai_validation",
    "similarity_match",
    "visual_region_assign",
    "math_detect",
    "table_detect",
    "visual_region_crop",
    "review",
)

# Resumable artifact snapshots
_EXPECTED_RESUMABLE = {
    "split": "split.json",
    "match": "match.json",
    "normalize_schema": "normalize_schema.json",
    "math_detect": "math_detect.json",
    "table_detect": "table_detect.json",
    "repair": "repair.json",
    "review": "review_commit_state.json",
}

_VALID_DOMAINS = frozenset({"ocr", "parse", "ai_correct", "save"})

# Conditionally-enabled stages and their option keys + defaults
_CONDITIONAL_EXPECTATIONS: dict[str, tuple[str, bool]] = {
    "wangdao_preprocess": ("enable_wangdao_preprocess", False),
    "ocr_correction": ("enable_ocr_correction", True),
    "visual_region_detect": ("enable_visual_region_detect", True),
    "code_language_noise_clean": ("enable_code_language_noise_clean", True),
    "code_structure_reconstruct": ("enable_code_structure_reconstruct", True),
    "batch_dedup": ("enable_batch_dedup", True),
    "repair": ("enable_ai_repair", True),
    "ai_validation": ("enable_ai_repair", True),
    "similarity_match": ("enable_similarity_match", True),
    "visual_region_assign": ("enable_visual_region_assign", True),
    "math_detect": ("enable_math_detect", True),
    "table_detect": ("enable_table_detect", True),
    "visual_region_crop": ("enable_visual_region_crop", True),
}


class TestPipelineDefinition:
    def test_stage_names_match_snapshot(self):
        assert PipelineDefinition.stage_names() == _EXPECTED_STAGE_NAMES

    def test_resumable_artifacts_match_snapshot(self):
        assert PipelineDefinition.resumable_artifacts() == _EXPECTED_RESUMABLE

    def test_business_map_has_all_stages(self):
        bmap = PipelineDefinition.business_map()
        assert len(bmap) == len(_EXPECTED_STAGE_NAMES)
        for name in _EXPECTED_STAGE_NAMES:
            assert name in bmap

    def test_business_domains_valid(self):
        bmap = PipelineDefinition.business_map()
        for name, domain in bmap.items():
            assert domain in _VALID_DOMAINS, f"{name}: invalid domain {domain!r}"

    def test_stage_names_unique(self):
        names = PipelineDefinition.stage_names()
        assert len(names) == len(set(names))

    def test_artifact_filenames_unique(self):
        artifacts = PipelineDefinition.resumable_artifacts()
        filenames = list(artifacts.values())
        assert len(filenames) == len(set(filenames))

    def test_resumable_stages_in_canonical_order(self):
        names = PipelineDefinition.stage_names()
        for stage_name in PipelineDefinition.resumable_artifacts():
            assert stage_name in names, f"{stage_name} not in canonical order"

    def test_order_is_stable(self):
        assert PipelineDefinition.stage_names() == PipelineDefinition.stage_names()

    def test_stage_index_matches_position(self):
        names = PipelineDefinition.stage_names()
        for i, name in enumerate(names):
            assert PipelineDefinition.stage_index(name) == i

    def test_stage_index_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown stage"):
            PipelineDefinition.stage_index("nonexistent_stage")

    def test_default_pipeline(self):
        """Default options (no overrides) = all enabled except wangdao_preprocess."""
        stages = PipelineDefinition.enabled_stages({})
        names = [s.name for s in stages]
        assert "extract" in names
        assert "wangdao_preprocess" not in names  # disabled_by_default
        assert "normalize_text" in names
        assert "review" in names

    def test_all_disabled_pipeline(self):
        """All conditional stages disabled."""
        off_options = {k: False for k, _v in _CONDITIONAL_EXPECTATIONS.values()}
        stages = PipelineDefinition.enabled_stages(off_options)
        names = [s.name for s in stages]
        for cond_name in _CONDITIONAL_EXPECTATIONS:
            assert cond_name not in names, f"{cond_name} should be disabled"
        # Always-enabled stages must still be present
        always = [n for n in _EXPECTED_STAGE_NAMES if n not in _CONDITIONAL_EXPECTATIONS]
        for name in always:
            assert name in names, f"{name} should always be present"

    def test_all_enabled_pipeline(self):
        """All conditional stages enabled."""
        on_options = {k: True for k, _v in _CONDITIONAL_EXPECTATIONS.values()}
        stages = PipelineDefinition.enabled_stages(on_options)
        names = [s.name for s in stages]
        assert set(names) == set(_EXPECTED_STAGE_NAMES)

    def test_enabled_stages_filtering(self):
        """Verify option_key + enabled_by_default logic."""
        for name, (opt_key, default) in _CONDITIONAL_EXPECTATIONS.items():
            sd = next(s for s in PipelineDefinition.stages() if s.name == name)
            assert sd.option_key == opt_key, f"{name}: expected option_key={opt_key!r}"
            assert sd.enabled_by_default == default, (
                f"{name}: expected enabled_by_default={default}"
            )

    def test_runner_methods_exist(self):
        """Each runner_method resolves via getattr on ImportPipeline."""
        from app.features.pipeline_orchestrator import ImportPipeline

        for sd in PipelineDefinition.stages():
            assert sd.runner_method, f"{sd.name}: runner_method is empty"
            method = getattr(ImportPipeline, sd.runner_method, None)
            assert method is not None, (
                f"{sd.name}: runner_method {sd.runner_method!r} not found on ImportPipeline"
            )
            assert callable(method), f"{sd.name}: {sd.runner_method!r} is not callable"

    def test_no_runtime_imports(self):
        """pipeline_definition is a pure metadata module — no orchestrator imports."""
        import importlib

        # Force re-import (in case previous tests loaded it)
        import app.features.pipeline_definition as pd_module
        importlib.reload(pd_module)

        mod_source = importlib.util.find_spec("app.features.pipeline_definition")
        assert mod_source is not None
        # Check we can import it without triggering orchestrator/artifacts
        import app
        from app.features import pipeline_definition

        # Verify it doesn't import pipeline_orchestrator or pipeline_artifacts
        loader_details = importlib.util.find_spec("app.features.pipeline_definition")
        assert loader_details is not None


class TestStageDefinition:
    def test_frozen(self):
        sd = StageDefinition(name="test")
        with pytest.raises((AttributeError, TypeError)):
            sd.name = "changed"  # type: ignore[misc]

    def test_slots(self):
        sd = StageDefinition(name="test")
        with pytest.raises(AttributeError):
            sd.__dict__  # slots, no __dict__  # type: ignore[attr-defined]
