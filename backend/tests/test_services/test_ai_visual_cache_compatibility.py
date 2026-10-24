"""Compatibility baseline for AI visual inputs and analysis cache freshness."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from app.ai.prompts import AI_ANALYSIS_PROMPT_VERSION
from app.services.ai_service import (
    _analysis_cache_age_ms,
    _analysis_cache_stale_reason,
    _collect_question_visual_sources,
    _detect_image_mime,
    _extract_structured_visual,
    _image_bytes_to_data_url,
    _iter_url_values,
    _question_has_unresolved_visual_slot,
    _visual_evidence_is_valid,
    ai_analysis_generated_at,
    is_ai_analysis_fresh,
)


@dataclass
class VisualQuestion:
    image_url: object = None
    content: dict = field(default_factory=dict)
    options: dict | None = None


def _question(
    *,
    image_url: object = None,
    segments: list | None = None,
    options: dict | None = None,
) -> VisualQuestion:
    content = {"segments": segments} if segments is not None else {}
    return VisualQuestion(image_url=image_url, content=content, options=options)


def _analysis(**meta: object) -> dict:
    return {
        "mistake_diagnosis": "诊断",
        "knowledge_patch": "补漏",
        "review_task": "任务",
        "_meta": meta,
    }


def _fresh_meta(**overrides: object) -> dict:
    meta = {
        "version": AI_ANALYSIS_PROMPT_VERSION,
        "grounding_guard": "passed",
        "generated_at": datetime.now(UTC).isoformat(),
        "visual_input_count": 1,
        "visual_evidence": "图中给出栈",
    }
    meta.update(overrides)
    return meta


class TestImageMimeAndDataUrl:
    @pytest.mark.parametrize(
        ("data", "expected"),
        [
            (b"\x89PNG\r\n\x1a\n", "image/png"),
            (b"RIFF____WEBP", "image/webp"),
            (b"GIF89a", "image/gif"),
            (b"\xff\xd8\xff", "image/jpeg"),
            (b"BM", "image/jpeg"),
        ],
    )
    def test_signature_detection(self, data, expected):
        assert _detect_image_mime(data) == expected

    def test_fallback_is_normalized_and_parameters_are_ignored(self):
        assert _detect_image_mime(b"unknown", "image/PNG; charset=utf-8") == "image/png"
        assert _detect_image_mime(b"unknown", "application/pdf") == "image/jpeg"

    def test_data_url_reencodes_and_uses_detected_mime(self):
        # 1x1 PNG. The service must re-encode rather than trust the caller MIME.
        png = bytes.fromhex(
            "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
            "1f15c4890000000d49444154789c63f8cfc0c00000040101004706cade"
            "0000000049454e44ae426082"
        )

        data_url = _image_bytes_to_data_url(png, content_type="image/jpeg")

        assert data_url.startswith("data:image/png;base64,")


class TestVisualSourceCollection:
    def test_url_values_are_trimmed_and_recursively_flattened(self):
        values = list(_iter_url_values([" a ", "", ("b", None), [["c"]], 42]))

        assert values == ["a", "b", "c"]

    def test_top_level_content_and_image_urls_are_deduplicated_in_order(self):
        question = _question(
            image_url=["same", "top"],
            segments=[
                {"type": "image", "url": "same", "source_image_url": "source"},
                {"type": "math_image", "fallback_image_url": "fallback"},
            ],
        )

        assert _collect_question_visual_sources(question) == [
            "same",
            "top",
            "source",
            "fallback",
        ]

    def test_table_and_code_segment_urls_are_collected(self):
        question = _question(
            segments=[
                {"type": "TABLE", "url": "table", "source_image_url": "table-src"},
                {"type": "code_image", "url": "code", "fallback_image_url": "code-alt"},
            ]
        )

        assert _collect_question_visual_sources(question) == [
            "table-src",
            "table",
            "code",
            "code-alt",
        ]

    def test_option_images_are_collected_but_text_is_ignored(self):
        question = _question(
            options={
                "A": {"text": "not-a-url", "image_url": "option-a"},
                "B": {"label": "B", "image": "option-b"},
            }
        )

        assert _collect_question_visual_sources(question) == ["option-a", "option-b"]

    def test_more_than_four_sources_are_capped(self):
        question = _question(
            image_url=[f"image-{index}" for index in range(5)],
        )

        assert _collect_question_visual_sources(question) == [
            "image-0",
            "image-1",
            "image-2",
            "image-3",
        ]


class TestUnresolvedVisualSlots:
    @pytest.mark.parametrize(
        "segment_type", ["image", "math_image", "table_image", "code_image"]
    )
    def test_declared_raster_segment_without_url_is_unresolved(self, segment_type):
        question = _question(segments=[{"type": segment_type, "url": ""}])

        assert _question_has_unresolved_visual_slot(question) is True

    def test_native_table_without_image_is_not_unresolved(self):
        question = _question(
            segments=[{"type": "table", "headers": ["列"], "rows": [["值"]]}]
        )

        assert _question_has_unresolved_visual_slot(question) is False

    def test_declared_image_option_without_url_is_unresolved(self):
        question = _question(options={"A": {"type": "image", "text": "图"}})

        assert _question_has_unresolved_visual_slot(question) is True

    def test_empty_image_url_on_text_option_is_not_unresolved(self):
        question = _question(options={"A": {"type": "text", "image_url": ""}})

        assert _question_has_unresolved_visual_slot(question) is False


class TestStructuredVisual:
    def test_native_tables_are_compacted_to_json(self):
        content = {
            "segments": [
                {
                    "type": "table",
                    "caption": "表",
                    "headers": ["列"],
                    "rows": [["值"]],
                    "empty": "",
                }
            ]
        }

        assert _extract_structured_visual(content) == (
            '[{"caption":"表","headers":["列"],"rows":[["值"]]}]'
        )

    def test_non_table_or_empty_content_returns_empty_string(self):
        assert _extract_structured_visual(None) == ""
        assert _extract_structured_visual({"segments": [{"type": "image"}]}) == ""
        assert (
            _extract_structured_visual({"segments": [{"type": "table", "rows": []}]})
            == ""
        )


class TestVisualEvidence:
    @pytest.mark.parametrize(
        "value",
        [
            "无法读取",
            "图片无法识别",
            "no_image",
            "unable-to-read",
            "  cannot read  ",
        ],
    )
    def test_unreadable_evidence_is_invalid(self, value):
        assert _visual_evidence_is_valid(value) is False

    @pytest.mark.parametrize(
        "value",
        ["图中给出栈", "image shows a stack", "可读取"],
    )
    def test_specific_evidence_is_valid(self, value):
        assert _visual_evidence_is_valid(value) is True


class TestAnalysisCacheFreshness:
    def test_age_is_zero_or_positive_for_current_generation(self):
        now = datetime.now(UTC)
        assert _analysis_cache_age_ms({"_meta": {"generated_at": now.isoformat()}}) == 0

        age = _analysis_cache_age_ms(
            {"_meta": {"generated_at": (now - timedelta(seconds=1)).isoformat()}}
        )

        assert 900 <= age <= 1100

    def test_age_accepts_z_and_naive_timestamps(self):
        now = datetime.now(UTC)
        z_value = now.isoformat().replace("+00:00", "Z")
        naive_value = now.replace(tzinfo=None).isoformat()

        assert _analysis_cache_age_ms({"_meta": {"generated_at": z_value}}) == 0
        assert _analysis_cache_age_ms({"_meta": {"generated_at": naive_value}}) == 0

    @pytest.mark.parametrize(
        "value",
        [None, {}, {"_meta": {}}, {"_meta": {"generated_at": "invalid"}}, "analysis"],
    )
    def test_invalid_age_inputs_return_none(self, value):
        assert _analysis_cache_age_ms(value) is None

    def test_valid_visual_cache_is_fresh(self):
        analysis = _analysis(**_fresh_meta())

        assert is_ai_analysis_fresh(analysis, requires_visual=True) is True
        assert _analysis_cache_stale_reason(analysis, requires_visual=True) is None

    @pytest.mark.parametrize(
        ("overrides", "reason"),
        [
            ({"version": f"{AI_ANALYSIS_PROMPT_VERSION}-old"}, "prompt_version"),
            ({"grounding_guard": "failed"}, "grounding_guard"),
            ({"visual_input_count": 0}, "visual_input"),
            ({"visual_evidence": "无法读取"}, "visual_evidence"),
            ({"input_signature": "old"}, "input_signature"),
            (
                {"input_signature": "current", "model_signature": "old"},
                "model_signature",
            ),
        ],
    )
    def test_stale_reasons_are_typed(self, overrides, reason):
        analysis = _analysis(**_fresh_meta(**overrides))

        assert (
            _analysis_cache_stale_reason(
                analysis,
                requires_visual=True,
                expected_input_signature="current",
                expected_model_signature="current",
            )
            == reason
        )
        assert (
            is_ai_analysis_fresh(
                analysis,
                requires_visual=True,
                expected_input_signature="current",
                expected_model_signature="current",
            )
            is False
        )

    def test_text_cache_does_not_require_visual_evidence(self):
        analysis = _analysis(**_fresh_meta(visual_input_count=0, visual_evidence=""))

        assert is_ai_analysis_fresh(analysis, requires_visual=False) is True

    def test_empty_or_invalid_content_is_stale(self):
        assert _analysis_cache_stale_reason(None) == "empty"
        assert _analysis_cache_stale_reason({}) == "empty"
        assert (
            _analysis_cache_stale_reason({"mistake_diagnosis": " "})
            == "content_invalid"
        )

    def test_signature_checks_are_optional(self):
        analysis = _analysis(**_fresh_meta())

        assert is_ai_analysis_fresh(analysis, requires_visual=True) is True

    def test_generated_at_is_exposed_without_internal_meta(self):
        generated_at = datetime.now(UTC).isoformat()
        analysis = _analysis(**_fresh_meta(generated_at=generated_at))

        assert ai_analysis_generated_at(analysis) == generated_at
        assert ai_analysis_generated_at({"_meta": {"generated_at": " "}}) is None
        assert ai_analysis_generated_at(None) is None
