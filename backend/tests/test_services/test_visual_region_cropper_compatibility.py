"""Real compatibility baseline for visual region bbox validation and conversion."""

from __future__ import annotations

import pytest

from app.services.visual_region_cropper import validate_bbox


class TestValidateBbox:
    def test_none_returns_none(self):
        assert validate_bbox(None) is None

    def test_valid_tuple(self):
        assert validate_bbox((10, 20, 410, 420)) == (10, 20, 410, 420)

    def test_valid_list_converted_to_tuple(self):
        result = validate_bbox([10, 20, 100, 200])
        assert result == (10, 20, 100, 200)
        assert isinstance(result, tuple)

    def test_inverted_x_returns_none(self):
        assert validate_bbox((100, 0, 50, 100)) is None

    def test_inverted_y_returns_none(self):
        assert validate_bbox((0, 100, 100, 50)) is None

    def test_zero_area_returns_none(self):
        assert validate_bbox((50, 50, 50, 50)) is None

    def test_negative_coords_return_none(self):
        assert validate_bbox((-10, 0, 100, 100)) is None

    def test_absurd_coords_return_none(self):
        assert validate_bbox((0, 0, 2_000_000, 100)) is None

    def test_wrong_length_returns_none(self):
        assert validate_bbox((10, 20, 100)) is None
        assert validate_bbox((10, 20, 100, 200, 300)) is None

    def test_non_numeric_returns_none(self):
        assert validate_bbox(("a", "b", "c", "d")) is None

    def test_float_coords_accepted(self):
        result = validate_bbox((1.5, 2.5, 100.5, 200.5))
        assert result == (1.5, 2.5, 100.5, 200.5)
