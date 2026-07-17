"""Tests for question_bbox pipeline integration.

Covers:
- question_bbox stage exists in pipeline stage list
- question_bbox runs between split and match
- crop_region is importable in visual_region_crop context
- question_bbox fields survive normalize_schema
"""
from __future__ import annotations

import pytest

from app.features.pipeline_orchestrator import ImportPipeline
from app.services.visual_region_cropper import crop_region


class TestQuestionBboxPipelineStage:
    def test_stage_in_pipeline(self):
        """question_bbox stage should exist in the pipeline."""
        pipeline = ImportPipeline(options={})
        pipeline._build_pipeline()
        assert "question_bbox" in pipeline.stages
        assert "split" in pipeline.stages
        assert "match" in pipeline.stages

    def test_stage_order(self):
        """question_bbox should run between split and match."""
        pipeline = ImportPipeline(options={})
        pipeline._build_pipeline()
        stage_names = list(pipeline.stages.keys())
        split_idx = stage_names.index("split")
        qbbox_idx = stage_names.index("question_bbox")
        match_idx = stage_names.index("match")
        assert split_idx < qbbox_idx < match_idx


class TestCropRegionImportable:
    def test_crop_region_importable(self):
        """crop_region should be importable (fixes NameError in pipeline)."""
        from app.services.visual_region_cropper import crop_region
        assert callable(crop_region)

    def test_crop_and_upload_region_importable(self):
        """Both crop functions should be importable."""
        from app.services.visual_region_cropper import crop_and_upload_region
        assert callable(crop_and_upload_region)


class TestQuestionNormalizerPreservesBbox:
    def test_bbox_fields_preserved(self):
        """question_bbox fields should survive normalize_output."""
        from app.features.question_normalizer import normalize_output

        question = {
            "stem": "测试题干",
            "question_type": "single_choice",
            "options": [{"key": "A", "text": "opt"}],
            "answer": "A",
            "analysis": "",
            "question_bbox": [100, 100, 500, 400],
            "question_bbox_coordinate_space": "image_pixels",
            "question_bbox_page_width": 800,
            "question_bbox_page_height": 1000,
            "question_bbox_confidence": 0.95,
            "question_bbox_strategy": "test",
            "question_bbox_diagnostics": {"coverage": 1.0},
            "page_start": 1,
            "page_end": 1,
            "source_question_no": 1,
            "source_question_label": "1. 测试",
        }
        result = normalize_output(question)
        assert result.get("question_bbox") == [100, 100, 500, 400]
        assert result.get("question_bbox_coordinate_space") == "image_pixels"
        assert result.get("question_bbox_page_width") == 800
        assert result.get("question_bbox_page_height") == 1000
        assert result.get("question_bbox_confidence") == 0.95
        assert result.get("question_bbox_strategy") == "test"
        assert result.get("question_bbox_diagnostics", {}).get("coverage") == 1.0
        assert result.get("page_start") == 1
        assert result.get("source_question_no") == 1

    def test_cache_hit_re_attaches_bbox(self):
        """When cache hits, bbox fields from raw_question should be re-attached."""
        from app.features.question_normalizer import (
            normalize_question,
            parse_cache_clear,
        )

        parse_cache_clear()

        raw_q = {
            "number": 1,
            "page_start": 1,
            "source_question_no": 1,
            "raw_question_text": "1. 缓存测试\nA. opt A\nB. opt B",
            "has_options": True,
            "option_lines": {"A": "opt A", "B": "opt B"},
            "question_bbox": [50, 100, 500, 200],
            "question_bbox_coordinate_space": "image_pixels",
            "question_bbox_confidence": 0.95,
        }

        matched = {"question_number": 1, "answer": "A"}
        source_info = {"subject": "math2", "file": "test.pdf"}

        # First call populates cache
        result1 = normalize_question(raw_q, matched, source_info)
        assert result1.get("question_bbox") == [50, 100, 500, 200]

        # Second call hits cache — bbox should still be present
        result2 = normalize_question(raw_q, matched, source_info)
        assert result2.get("question_bbox") == [50, 100, 500, 200]
        assert result2.get("question_bbox_confidence") == 0.95
