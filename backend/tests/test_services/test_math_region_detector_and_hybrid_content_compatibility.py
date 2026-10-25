"""Pure-function compatibility baseline for math region detection and hybrid content.

Pins the pure helpers in ``math_region_detector`` (math character/font detection,
median height fallback) and the segment builder in ``hybrid_content_builder`` so
later refactors of math detection or content segmentation cannot silently change
which Unicode characters trigger detection, how empty inputs fall back, or how
text is sliced/rebuilt around math images.
"""

from __future__ import annotations

from app.services.hybrid_content_builder import _build_segments, _rebuild_text, build
from app.services.math_region_detector import (
    MathRegion,
    MathRegionType,
    _is_math_char,
    _is_math_font,
    _median_height,
)


class TestIsMathChar:
    def test_ascii_math_punct_passes(self):
        for ch in ["^", "_", "{", "}", "\\", "$"]:
            # "$" is not in _MATH_ASCII but the others are
            if ch in {"^", "_", "{", "}", "\\"}:
                assert _is_math_char(ch) is True

    def test_dollar_is_not_math_ascii(self):
        # "$" is a delimiter, not part of _MATH_ASCII; pin so future "fix" does not silently add it.
        assert _is_math_char("$") is False

    def test_greek_uppercase_alpha(self):
        assert _is_math_char("Α") is True  # U+0391

    def test_greek_lowercase_omega(self):
        assert _is_math_char("ω") is True  # U+03C9

    def test_math_operator_integral(self):
        assert _is_math_char("∫") is True  # U+222B

    def test_math_operator_leq(self):
        assert _is_math_char("≤") is True  # U+2264

    def test_letterlike_double_struck_r(self):
        assert _is_math_char("ℝ") is True  # U+211D

    def test_superscript_two(self):
        # U+00B2 (²) is NOT in the [0x2070, 0x209C] superscript range; pin so future
        # widening of the range cannot silently flag Latin-1 supplement chars.
        assert _is_math_char("²") is False

    def test_superscript_in_range(self):
        # U+2070 "⁰" is at the start of the superscript/subscript Unicode block.
        assert _is_math_char("⁰") is True

    def test_subscript_in_range(self):
        assert _is_math_char("ₓ") is True  # U+2093

    def test_plain_ascii_letter_is_not_math(self):
        assert _is_math_char("a") is False

    def test_plain_ascii_digit_is_not_math(self):
        assert _is_math_char("1") is False

    def test_cjk_is_not_math(self):
        assert _is_math_char("中") is False

    def test_space_is_not_math(self):
        assert _is_math_char(" ") is False

    def test_empty_string_raises_type_error(self):
        # The implementation calls ord("") which raises; pin this so callers
        # know empty input is not silently treated as non-math.
        import pytest

        with pytest.raises(TypeError):
            _is_math_char("")

    def test_just_below_greek_range_not_math(self):
        # U+0390 just before Α (U+0391) is not flagged
        assert _is_math_char("ΐ") is False

    def test_just_above_greek_range_not_math(self):
        # U+03D0 (ϐ) just after ω (U+03C9) is not flagged (outside the [0x0391, 0x03C9] range)
        assert _is_math_char("ϐ") is False


class TestIsMathFont:
    def test_empty_string_returns_false(self):
        assert _is_math_font("") is False

    def test_none_returns_false(self):
        assert _is_math_font(None) is False  # type: ignore[arg-type]

    def test_exact_keyword_math(self):
        assert _is_math_font("Math") is True

    def test_keyword_substring_cmmi(self):
        assert _is_math_font("CMMI10") is True

    def test_keyword_substring_symbol(self):
        assert _is_math_font("Some-Symbol-Bold") is True

    def test_keyword_case_sensitive(self):
        # The keyword list uses literal casing; lowercase "math" must not match "Math"
        assert _is_math_font("mathfont") is False

    def test_math_suffix_with_plus(self):
        assert _is_math_font("Foo+Math") is True

    def test_stix_keyword(self):
        assert _is_math_font("STIXGeneral") is True

    def test_cambria_keyword(self):
        assert _is_math_font("Cambria Math") is True

    def test_mt_extra_keyword(self):
        assert _is_math_font("MT Extra") is True

    def test_mathmaru_keyword(self):
        assert _is_math_font("Mathmaru") is True

    def test_plain_arial_is_not_math(self):
        assert _is_math_font("Arial") is False

    def test_partial_keyword_not_matched(self):
        # "Mat" is a prefix of "Math" but not in the keyword list
        assert _is_math_font("Mat") is False

    def test_keyword_in_middle(self):
        assert _is_math_font("prefix-Math-suffix") is True


class TestMedianHeight:
    def test_empty_returns_default_8(self):
        assert _median_height([]) == 8.0

    def test_single_char_returns_that_height(self):
        chars = [(0, 0, 10, 12, "a")]  # height 12
        assert _median_height(chars) == 12

    def test_odd_count_returns_middle(self):
        # heights sorted: [4, 10, 20] -> middle is 10
        chars = [(0, 0, 1, 4, "a"), (0, 0, 1, 10, "b"), (0, 0, 1, 20, "c")]
        assert _median_height(chars) == 10

    def test_even_count_returns_upper_middle(self):
        # heights sorted: [4, 10, 20, 30] -> len//2 = 2 -> index 2 = 20
        chars = [
            (0, 0, 1, 4, "a"),
            (0, 0, 1, 10, "b"),
            (0, 0, 1, 20, "c"),
            (0, 0, 1, 30, "d"),
        ]
        assert _median_height(chars) == 20

    def test_duplicate_heights(self):
        chars = [(0, 0, 1, 8, "a"), (0, 0, 1, 8, "b"), (0, 0, 1, 8, "c")]
        assert _median_height(chars) == 8

    def test_unsorted_input_sorted_internally(self):
        # Inputs in arbitrary y1 order; result is the median of sorted heights.
        chars = [(0, 0, 1, 30, "a"), (0, 0, 1, 4, "b"), (0, 0, 1, 10, "c")]
        assert _median_height(chars) == 10


def _region(
    *,
    page_num=1,
    bbox=(0.0, 0.0, 10.0, 10.0),
    region_type=MathRegionType.INLINE,
    raw_latex=None,
    image_url=None,
):
    return MathRegion(
        page_num=page_num,
        bbox=bbox,
        region_type=region_type,
        raw_latex=raw_latex,
        image_url=image_url,
    )


class TestBuild:
    def test_no_regions_returns_plain_text_structure(self):
        result = build("hello", [])
        assert result == {"text": "hello"}

    def test_none_regions_returns_plain_text_structure(self):
        # Empty list / None both treated as "no regions" by the truthiness check.
        result = build("hello", None)  # type: ignore[arg-type]
        assert result == {"text": "hello"}

    def test_regions_without_image_url_return_plain_text(self):
        # Only regions with image_url and valid bbox are kept.
        result = build(
            "hello",
            [_region(raw_latex="x", image_url=None)],
        )
        assert result == {"text": "hello"}

    def test_regions_with_zero_width_bbox_return_plain_text(self):
        result = build(
            "hello",
            [_region(raw_latex="x", image_url="u", bbox=(0.0, 0.0, 0.0, 10.0))],
        )
        assert result == {"text": "hello"}

    def test_regions_with_negative_width_bbox_return_plain_text(self):
        result = build(
            "hello",
            [_region(raw_latex="x", image_url="u", bbox=(10.0, 0.0, 5.0, 10.0))],
        )
        assert result == {"text": "hello"}

    def test_single_region_with_image_url_and_valid_bbox(self):
        region = _region(
            raw_latex="x^2",
            image_url="img.png",
            bbox=(0.0, 0.0, 10.0, 10.0),
        )
        result = build("x^2", [region])
        assert result == {
            "text": "$x^2$",
            "segments": [
                {
                    "type": "math_image",
                    "url": "img.png",
                    "alt": "x^2",
                    "display": False,
                },
            ],
            "render_mode": "segments",
        }

    def test_regions_sorted_by_page_then_y_then_x(self):
        # Provide regions out of order; build must sort them.
        r1 = _region(page_num=1, bbox=(0.0, 30.0, 10.0, 40.0), raw_latex="a", image_url="a.png")
        r2 = _region(page_num=1, bbox=(0.0, 10.0, 10.0, 20.0), raw_latex="b", image_url="b.png")
        r3 = _region(page_num=2, bbox=(0.0, 5.0, 10.0, 15.0), raw_latex="c", image_url="c.png")
        result = build("ab c", [r1, r2, r3])
        urls = [s["url"] for s in result["segments"] if s["type"] == "math_image"]
        # order should be (page 1 y10), (page 1 y30), (page 2 y5)
        assert urls == ["b.png", "a.png", "c.png"]

    def test_invalid_regions_with_at_least_one_valid_still_segments(self):
        valid = _region(raw_latex="x", image_url="img.png")
        invalid = _region(raw_latex="y", image_url=None)  # filtered out
        result = build("x", [valid, invalid])
        assert result.get("render_mode") == "segments"


class TestBuildSegments:
    def test_text_only_when_region_alt_not_in_text(self):
        region = _region(raw_latex="zzz", image_url="img.png")
        segments = _build_segments("hello world", [region])
        # Region appended as math_image without slicing text; remaining text appended.
        assert segments == [
            {"type": "math_image", "url": "img.png", "alt": "zzz", "display": False},
            {"type": "text", "text": "hello world"},
        ]

    def test_alt_empty_string_never_located(self):
        # alt="" -> find returns 0 but the if-alt guard skips find -> appended.
        region = _region(raw_latex="", image_url="img.png")
        segments = _build_segments("hello", [region])
        assert segments == [
            {"type": "math_image", "url": "img.png", "alt": "", "display": False},
            {"type": "text", "text": "hello"},
        ]

    def test_alt_at_start_slices_off_leading_text_segment(self):
        region = _region(raw_latex="x", image_url="img.png")
        segments = _build_segments("x end", [region])
        assert segments == [
            {"type": "math_image", "url": "img.png", "alt": "x", "display": False},
            {"type": "text", "text": " end"},
        ]

    def test_alt_at_end_slices_off_trailing_text_segment(self):
        region = _region(raw_latex="x", image_url="img.png")
        segments = _build_segments("end x", [region])
        assert segments == [
            {"type": "text", "text": "end "},
            {"type": "math_image", "url": "img.png", "alt": "x", "display": False},
        ]

    def test_alt_in_middle_slices_both_sides(self):
        region = _region(raw_latex="mid", image_url="img.png")
        segments = _build_segments("pre mid post", [region])
        assert segments == [
            {"type": "text", "text": "pre "},
            {"type": "math_image", "url": "img.png", "alt": "mid", "display": False},
            {"type": "text", "text": " post"},
        ]

    def test_first_match_position_consumed_remaining_not_rematched(self):
        # Two regions with the same alt: second region searches only the
        # remaining text after the first match.
        region1 = _region(raw_latex="x", image_url="a.png")
        region2 = _region(raw_latex="x", image_url="b.png")
        segments = _build_segments("x x", [region1, region2])
        assert segments == [
            {"type": "math_image", "url": "a.png", "alt": "x", "display": False},
            {"type": "text", "text": " "},
            {"type": "math_image", "url": "b.png", "alt": "x", "display": False},
        ]

    def test_display_flag_propagated(self):
        region = _region(
            raw_latex="x",
            image_url="img.png",
            region_type=MathRegionType.DISPLAY,
        )
        segments = _build_segments("x", [region])
        assert segments[0]["display"] is True

    def test_mixed_type_neither_display(self):
        region = _region(
            raw_latex="x",
            image_url="img.png",
            region_type=MathRegionType.MIXED,
        )
        segments = _build_segments("x", [region])
        assert segments[0]["display"] is False

    def test_empty_text_with_region(self):
        region = _region(raw_latex="x", image_url="img.png")
        segments = _build_segments("", [region])
        # alt "x" not found in "" -> appended as math_image, no trailing text.
        assert segments == [
            {"type": "math_image", "url": "img.png", "alt": "x", "display": False},
        ]

    def test_empty_text_empty_alt_with_region(self):
        region = _region(raw_latex="", image_url="img.png")
        segments = _build_segments("", [region])
        # Empty alt -> appended; no remaining text.
        assert segments == [
            {"type": "math_image", "url": "img.png", "alt": "", "display": False},
        ]


class TestRebuildText:
    def test_empty_segments_returns_empty_string(self):
        assert _rebuild_text([]) == ""

    def test_text_only_segment(self):
        assert _rebuild_text([{"type": "text", "text": "hello"}]) == "hello"

    def test_text_segment_with_none_text_returns_empty(self):
        assert _rebuild_text([{"type": "text", "text": None}]) == ""

    def test_text_segment_with_missing_text_key_returns_empty(self):
        assert _rebuild_text([{"type": "text"}]) == ""

    def test_math_image_segment_wraps_alt_in_dollars(self):
        seg = [{"type": "math_image", "alt": "x^2"}]
        assert _rebuild_text(seg) == "$x^2$"

    def test_math_image_with_none_alt_renders_empty_dollars(self):
        seg = [{"type": "math_image", "alt": None}]
        assert _rebuild_text(seg) == "$$"

    def test_math_image_with_missing_alt_renders_empty_dollars(self):
        seg = [{"type": "math_image"}]
        assert _rebuild_text(seg) == "$$"

    def test_newline_segment_renders_newline_char(self):
        assert _rebuild_text([{"type": "newline"}]) == "\n"

    def test_unknown_type_skipped(self):
        assert _rebuild_text([{"type": "unknown"}]) == ""

    def test_mixed_sequence(self):
        segs = [
            {"type": "text", "text": "pre "},
            {"type": "math_image", "alt": "x"},
            {"type": "newline"},
            {"type": "text", "text": "post"},
        ]
        assert _rebuild_text(segs) == "pre $x$\npost"

    def test_order_preserved(self):
        segs = [
            {"type": "text", "text": "a"},
            {"type": "text", "text": "b"},
            {"type": "math_image", "alt": "y"},
        ]
        assert _rebuild_text(segs) == "ab$y$"

    def test_alt_with_dollar_inside_is_not_escaped(self):
        # The function does not escape; pin so callers know.
        seg = [{"type": "math_image", "alt": "a$b"}]
        assert _rebuild_text(seg) == "$a$b$"
