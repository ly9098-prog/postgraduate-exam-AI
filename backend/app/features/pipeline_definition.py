"""Pipeline Stage Definition — single authoritative source for stage metadata.

This module is a *pure metadata* module: it must not import from
pipeline_orchestrator, pipeline_artifacts, or any runtime code to
avoid circular dependencies.

Usage::

    from app.features.pipeline_definition import PipelineDefinition

    for sd in PipelineDefinition.stages():
        print(sd.name, sd.business_domain)

    enabled = PipelineDefinition.enabled_stages({"enable_ai_repair": True})
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class StageDefinition:
    """Immutable definition of a single pipeline stage.

    Fields
    ------
    name:
        Unique stage name.
    runner_method:
        Method name on ``ImportPipeline`` resolved via ``getattr``.
    description:
        Human-readable description.
    option_key:
        Config option key for conditional enable (empty = always enabled).
    enabled_by_default:
        Default value when ``option_key`` is absent from runtime options.
    resumable_artifact_filename:
        File name for artifact persistence; empty means not resumable.
    business_domain:
        Logical category: ``ocr``, ``parse``, ``ai_correct``, or ``save``.
    """

    name: str
    runner_method: str = ""
    description: str = ""
    option_key: str = ""
    enabled_by_default: bool = True
    resumable_artifact_filename: str = ""
    business_domain: str = ""


# Convenience builder for always-enabled stages
def _always(
    name: str,
    *,
    business_domain: str = "parse",
    description: str = "",
) -> StageDefinition:
    return StageDefinition(
        name=name,
        runner_method=f"_run_{name}",
        description=description,
        business_domain=business_domain,
    )


# Convenience builder for conditionally-enabled stages
def _when(
    name: str,
    option_key: str,
    *,
    enabled_by_default: bool = True,
    business_domain: str = "parse",
    description: str = "",
    resumable_artifact_filename: str = "",
) -> StageDefinition:
    return StageDefinition(
        name=name,
        runner_method=f"_run_{name}",
        description=description,
        option_key=option_key,
        enabled_by_default=enabled_by_default,
        business_domain=business_domain,
        resumable_artifact_filename=resumable_artifact_filename,
    )


# Convenience builder for resumable stages (checkpointable)
def _resumable(
    name: str,
    filename: str,
    *,
    business_domain: str = "parse",
    description: str = "",
    option_key: str = "",
    enabled_by_default: bool = True,
) -> StageDefinition:
    return StageDefinition(
        name=name,
        runner_method=f"_run_{name}",
        description=description,
        option_key=option_key,
        enabled_by_default=enabled_by_default,
        resumable_artifact_filename=filename,
        business_domain=business_domain,
    )


_VALID_DOMAINS = frozenset({"ocr", "parse", "ai_correct", "save"})


class PipelineDefinition:
    """Single source of truth for pipeline stage definitions.

    All stage metadata — order, runners, conditional enable, resumability,
    business domain — lives here.  Consumers import this module instead
    of maintaining their own lists.
    """

    _STAGES: tuple[StageDefinition, ...] = (
        _always("extract", business_domain="ocr"),
        _when("wangdao_preprocess", "enable_wangdao_preprocess", enabled_by_default=False),
        _always("normalize_text"),
        _when("ocr_correction", "enable_ocr_correction", business_domain="ai_correct"),
        _always("layout_reconstruction"),
        _always("layout_router"),
        _when("visual_region_detect", "enable_visual_region_detect"),
        _always("analyze_structure"),
        _always("classify_pages"),
        _always("structure_freeze"),
        _resumable("split", "split.json"),
        _always("question_bbox"),
        _resumable("match", "match.json"),
        _resumable("normalize_schema", "normalize_schema.json"),
        _when("code_language_noise_clean", "enable_code_language_noise_clean"),
        _when("code_structure_reconstruct", "enable_code_structure_reconstruct"),
        _always("classify_questions"),
        _always("batch_validation"),
        _when("batch_dedup", "enable_batch_dedup"),
        _resumable("repair", "repair.json", option_key="enable_ai_repair", business_domain="ai_correct"),
        _when("ai_validation", "enable_ai_repair"),
        _when("similarity_match", "enable_similarity_match"),
        _when("visual_region_assign", "enable_visual_region_assign"),
        _resumable("math_detect", "math_detect.json", option_key="enable_math_detect"),
        _resumable("table_detect", "table_detect.json", option_key="enable_table_detect"),
        _when("visual_region_crop", "enable_visual_region_crop"),
        _resumable("review", "review_commit_state.json", business_domain="save"),
    )

    # ── classmethods ──────────────────────────────────────────────────────

    @classmethod
    def stages(cls) -> tuple[StageDefinition, ...]:
        """All stage definitions in canonical order."""
        return cls._STAGES

    @classmethod
    def stage_names(cls) -> tuple[str, ...]:
        """Canonical stage name list."""
        return tuple(s.name for s in cls._STAGES)

    @classmethod
    def stage_index(cls, name: str) -> int:
        """Return the position of *name* in the canonical stage order.

        Raises ``ValueError`` for unknown stage names.
        """
        for i, sd in enumerate(cls._STAGES):
            if sd.name == name:
                return i
        raise ValueError(f"Unknown stage name {name!r}")

    @classmethod
    def enabled_stages(
        cls, options: dict[str, bool] | None = None,
    ) -> tuple[StageDefinition, ...]:
        """Return stage definitions filtered by runtime *options*.

        Stages whose ``option_key`` is empty (always enabled) are always
        included.  For stages with an ``option_key`` the value from *options*
        (or ``enabled_by_default`` if absent) determines inclusion.
        """
        if options is None:
            options = {}
        result: list[StageDefinition] = []
        for sd in cls._STAGES:
            if not sd.option_key:
                result.append(sd)
            else:
                enabled = options.get(sd.option_key, sd.enabled_by_default)
                if enabled:
                    result.append(sd)
        return tuple(result)

    @classmethod
    def resumable_artifacts(cls) -> dict[str, str]:
        """Map stage name → artifact filename for resumable stages."""
        return {
            sd.name: sd.resumable_artifact_filename
            for sd in cls._STAGES
            if sd.resumable_artifact_filename
        }

    @classmethod
    def business_map(cls) -> dict[str, str]:
        """Map stage name → business domain for every stage."""
        return {sd.name: sd.business_domain for sd in cls._STAGES}
