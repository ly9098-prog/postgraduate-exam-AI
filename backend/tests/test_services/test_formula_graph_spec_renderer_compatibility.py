"""Real compatibility baseline for formula graph spec renderer pure functions.

Covers ``_filter_finite``, ``_discontinuity_gap``, ``_auto_range``,
``_sanitize_label``, and ``check_quality``.
"""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from app.services.formula_graph_spec_renderer import (
    _auto_range,
    _discontinuity_gap,
    _filter_finite,
    _sanitize_label,
    check_quality,
)


class TestFilterFinite:
    def test_removes_nan(self):
        xs = np.array([1.0, 2.0, 3.0])
        ys = np.array([1.0, np.nan, 3.0])
        fx, fy = _filter_finite(xs, ys)
        assert list(fx) == [1.0, 3.0]
        assert list(fy) == [1.0, 3.0]

    def test_removes_inf(self):
        xs = np.array([1.0, 2.0, 3.0])
        ys = np.array([1.0, np.inf, 3.0])
        fx, fy = _filter_finite(xs, ys)
        assert list(fx) == [1.0, 3.0]

    def test_removes_neg_inf(self):
        xs = np.array([1.0, 2.0, 3.0])
        ys = np.array([1.0, -np.inf, 3.0])
        fx, fy = _filter_finite(xs, ys)
        assert list(fx) == [1.0, 3.0]

    def test_all_finite_preserved(self):
        xs = np.array([1.0, 2.0, 3.0])
        ys = np.array([1.0, 2.0, 3.0])
        fx, fy = _filter_finite(xs, ys)
        assert list(fx) == [1.0, 2.0, 3.0]

    def test_all_nan_returns_empty(self):
        xs = np.array([1.0, 2.0, 3.0])
        ys = np.array([np.nan, np.nan, np.nan])
        fx, fy = _filter_finite(xs, ys)
        assert len(fx) == 0


class TestDiscontinuityGap:
    def test_splits_at_large_jump(self):
        xs = np.array([1.0, 2.0, 3.0, 4.0])
        ys = np.array([1.0, 2.0, 100.0, 101.0])
        segs = _discontinuity_gap(xs, ys, threshold=10.0)
        assert len(segs) == 2

    def test_no_split_when_continuous(self):
        xs = np.array([1.0, 2.0, 3.0, 4.0])
        ys = np.array([1.0, 2.0, 3.0, 4.0])
        segs = _discontinuity_gap(xs, ys, threshold=10.0)
        assert len(segs) == 1

    def test_empty_arrays(self):
        segs = _discontinuity_gap(np.array([]), np.array([]))
        assert segs == []

    def test_single_point(self):
        segs = _discontinuity_gap(np.array([1.0]), np.array([2.0]))
        assert len(segs) == 1
        assert list(segs[0][0]) == [1.0]

    def test_default_threshold_auto(self):
        xs = np.array([1.0, 2.0, 3.0, 4.0])
        ys = np.array([0.0, 1.0, 50.0, 51.0])
        segs = _discontinuity_gap(xs, ys)
        assert len(segs) == 2


class TestAutoRange:
    def test_empty_returns_default(self):
        r = _auto_range([], [])
        assert r == (-6, 6, -6, 6)

    def test_auto_mode_uses_min_max(self):
        xs = [np.array([0.0, 1.0, 2.0])]
        ys = [np.array([0.0, 1.0, 4.0])]
        r = _auto_range(xs, ys, mode="auto")
        x_min, x_max, y_min, y_max = r
        assert x_min < 0 and x_max > 2
        assert y_min < 0 and y_max > 4

    def test_auto_robust_uses_percentile(self):
        xs = [np.array([0.0, 1.0, 2.0])]
        ys = [np.array([0.0, 1.0, 4.0])]
        r = _auto_range(xs, ys, mode="auto_robust")
        x_min, x_max, y_min, y_max = r
        assert x_min < 0 and x_max > 2

    def test_includes_annotation_points(self):
        xs = [np.array([0.0, 1.0, 2.0])]
        ys = [np.array([0.0, 1.0, 4.0])]
        r = _auto_range(xs, ys, annotations=[{"x": 5.0, "y": 10.0}])
        x_min, x_max, y_min, y_max = r
        assert x_max > 5 and y_max > 10

    def test_padding_added(self):
        xs = [np.array([0.0, 10.0])]
        ys = [np.array([0.0, 10.0])]
        r = _auto_range(xs, ys, mode="auto")
        x_min, x_max, y_min, y_max = r
        assert x_min < 0 and x_max > 10
        assert y_min < 0 and y_max > 10


class TestSanitizeLabel:
    def test_none_returns_empty(self):
        assert _sanitize_label(None) == ""

    def test_empty_returns_empty(self):
        assert _sanitize_label("") == ""

    def test_plain_text_preserved(self):
        assert _sanitize_label("hello") == "hello"

    def test_strips_control_chars(self):
        assert _sanitize_label("ab\x00cd") == "abcd"

    def test_preserves_newlines_and_tabs(self):
        assert _sanitize_label("a\nb\tc") == "a\nb\tc"

    def test_strips_whitespace(self):
        assert _sanitize_label("  hello  ") == "hello"


class TestCheckQuality:
    @staticmethod
    def _white_png() -> bytes:
        buf = io.BytesIO()
        Image.new("RGB", (100, 100), (255, 255, 255)).save(buf, format="PNG")
        return buf.getvalue()

    @staticmethod
    def _dark_png() -> bytes:
        buf = io.BytesIO()
        Image.new("RGB", (100, 100), (0, 0, 0)).save(buf, format="PNG")
        return buf.getvalue()

    def test_white_image_fails(self):
        result = check_quality(
            self._white_png(),
            {"panels": []},
            {"valid_points": 0, "total_points": 0, "panel_count": 0, "total_curves": 0},
        )
        assert result["passed"] is False
        assert any("全白" in e for e in result["errors"])

    def test_insufficient_valid_points(self):
        result = check_quality(
            self._dark_png(),
            {"panels": []},
            {"valid_points": 5, "total_points": 100, "panel_count": 0, "total_curves": 0},
        )
        assert result["passed"] is False
        assert any("有效数据点不足" in e for e in result["errors"])

    def test_all_nan_detected(self):
        result = check_quality(
            self._dark_png(),
            {"panels": []},
            {"valid_points": 0, "total_points": 100, "panel_count": 0, "total_curves": 0},
        )
        assert result["passed"] is False
        assert any("未产生有效数据点" in e for e in result["errors"])

    def test_panel_count_mismatch(self):
        result = check_quality(
            self._dark_png(),
            {"panels": [1, 2, 3]},
            {"valid_points": 100, "total_points": 100, "panel_count": 2, "total_curves": 1},
        )
        assert result["passed"] is False
        assert any("面板数量不匹配" in e for e in result["errors"])

    def test_passes_on_valid_render(self):
        result = check_quality(
            self._dark_png(),
            {"panels": []},
            {"valid_points": 100, "total_points": 100, "panel_count": 0, "total_curves": 1},
        )
        assert result["passed"] is True
        assert result["errors"] == []

    def test_returns_errors_and_warnings_keys(self):
        result = check_quality(
            self._dark_png(),
            {"panels": []},
            {"valid_points": 100, "total_points": 100, "panel_count": 0, "total_curves": 0},
        )
        assert "errors" in result
        assert "warnings" in result
        assert "passed" in result
