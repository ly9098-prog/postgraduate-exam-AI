"""Pure-function compatibility baseline for formula_image_cropper constants and wrapper.

Pins the module-level constants (_DPI per-region-type map, _PADDING_PT,
_PAGE_RENDER_DPI, _MIN_CROP_*), the MathRegionType enum values, and the
crop_from_page_ref wrapper's exception-conversion behaviour (PIL/CropError
failures wrapped into ValueError with the bbox+path in the message) so that
later refactors cannot silently change which DPI is used per region type, the
padding default, or the exception contract that callers depend on.

The existing ``test_formula_image_cropper.py`` covers ``crop_region`` with real
PyMuPDF pages; this file pins the constant/wrapper surface only and does NOT
duplicate that coverage.
"""

from __future__ import annotations

import inspect

import pytest
from PIL import Image

from app.services.formula_image_cropper import (
    _DPI,
    _MIN_CROP_HEIGHT,
    _MIN_CROP_WIDTH,
    _PAGE_RENDER_DPI,
    _PADDING_PT,
    crop_from_page_ref,
)
from app.services.math_region_detector import MathRegionType
from app.services.visual_region_cropper import CropError, EmptyCropError


class TestMathRegionTypeEnum:
    """The three math region types and their string values."""

    def test_inline_value(self):
        assert MathRegionType.INLINE.value == "inline"

    def test_display_value(self):
        assert MathRegionType.DISPLAY.value == "display"

    def test_mixed_value(self):
        assert MathRegionType.MIXED.value == "mixed"

    def test_members_are_distinct(self):
        values = [s.value for s in MathRegionType]
        assert len(values) == len(set(values)) == 3

    def test_is_str_enum(self):
        assert MathRegionType.INLINE == "inline"
        assert isinstance(MathRegionType.INLINE, str)

    def test_expected_member_set(self):
        assert {s.value for s in MathRegionType} == {"inline", "display", "mixed"}


class TestModuleConstants:
    """Module-level constants that gate DPI, padding, and minimum crop size."""

    def test_padding_pt_is_six(self):
        assert _PADDING_PT == 6.0

    def test_page_render_dpi_is_150(self):
        assert _PAGE_RENDER_DPI == 150

    def test_min_crop_width_is_sixteen(self):
        assert _MIN_CROP_WIDTH == 16

    def test_min_crop_height_is_sixteen(self):
        assert _MIN_CROP_HEIGHT == 16


class TestDpiMap:
    """_DPI maps each MathRegionType to its render DPI.

    INLINE and MIXED use 144 DPI; DISPLAY uses 240 DPI. This is the contract
    that crop_region relies on for resolution selection.
    """

    def test_inline_is_144(self):
        assert _DPI[MathRegionType.INLINE] == 144

    def test_mixed_is_144(self):
        assert _DPI[MathRegionType.MIXED] == 144

    def test_display_is_240(self):
        assert _DPI[MathRegionType.DISPLAY] == 240

    def test_map_has_three_entries(self):
        assert len(_DPI) == 3

    def test_keys_are_all_math_region_types(self):
        assert set(_DPI.keys()) == {
            MathRegionType.INLINE,
            MathRegionType.DISPLAY,
            MathRegionType.MIXED,
        }

    def test_display_higher_than_inline(self):
        # DISPLAY formulas need higher resolution than INLINE/MIXED
        assert _DPI[MathRegionType.DISPLAY] > _DPI[MathRegionType.INLINE]
        assert _DPI[MathRegionType.DISPLAY] > _DPI[MathRegionType.MIXED]


class TestCropFromPageRefWrapper:
    """crop_from_page_ref delegates to crop_from_page_ref_compat and wraps
    failures into ValueError with bbox+path in the message."""

    @pytest.fixture
    def page_png(self, tmp_path):
        """Render an 800x600 white PNG to a temp file."""
        path = tmp_path / "page.png"
        Image.new("RGB", (800, 600), "white").save(path, format="PNG")
        return str(path)

    def test_valid_bbox_returns_png_bytes(self, page_png):
        result = crop_from_page_ref(page_png, (10.0, 10.0, 100.0, 100.0))
        assert isinstance(result, bytes)
        assert result[:4] == b"\x89PNG"
        assert len(result) > 100

    def test_valid_bbox_with_region_type_inline(self, page_png):
        result = crop_from_page_ref(
            page_png, (10.0, 10.0, 100.0, 100.0), MathRegionType.INLINE
        )
        assert result[:4] == b"\x89PNG"

    def test_valid_bbox_with_region_type_display(self, page_png):
        result = crop_from_page_ref(
            page_png, (10.0, 10.0, 100.0, 100.0), MathRegionType.DISPLAY
        )
        assert result[:4] == b"\x89PNG"

    def test_valid_bbox_with_region_type_mixed(self, page_png):
        result = crop_from_page_ref(
            page_png, (10.0, 10.0, 100.0, 100.0), MathRegionType.MIXED
        )
        assert result[:4] == b"\x89PNG"

    def test_inverted_bbox_raises_value_error(self, page_png):
        # Inverted bbox (x1 < x0) triggers EmptyCropError inside crop_region,
        # which the wrapper converts to ValueError with bbox+path in message.
        with pytest.raises(ValueError, match="crop_from_page_ref failed"):
            crop_from_page_ref(page_png, (100.0, 100.0, 50.0, 50.0))

    def test_inverted_bbox_value_error_contains_bbox_and_path(self, page_png):
        with pytest.raises(ValueError) as exc_info:
            crop_from_page_ref(page_png, (100.0, 100.0, 50.0, 50.0))
        message = str(exc_info.value)
        assert "bbox=(100.0, 100.0, 50.0, 50.0)" in message
        assert page_png in message

    def test_zero_area_bbox_passes_via_padding(self, page_png):
        # Pinned behaviour: a zero-area bbox does NOT raise because the 6pt
        # padding expands it on all sides, and after DPI conversion the
        # resulting crop exceeds _MIN_CROP_WIDTH/HEIGHT (16). This is the
        # current contract; a refactor that adds zero-area rejection here
        # would break callers that rely on padding rescue.
        result = crop_from_page_ref(page_png, (100.0, 100.0, 100.0, 100.0))
        assert result[:4] == b"\x89PNG"
        assert len(result) > 0

    def test_missing_file_raises_value_error(self, tmp_path):
        missing = str(tmp_path / "does_not_exist.png")
        with pytest.raises(ValueError, match="crop_from_page_ref failed"):
            crop_from_page_ref(missing, (10.0, 10.0, 100.0, 100.0))

    def test_missing_file_value_error_contains_path(self, tmp_path):
        missing = str(tmp_path / "does_not_exist.png")
        with pytest.raises(ValueError) as exc_info:
            crop_from_page_ref(missing, (10.0, 10.0, 100.0, 100.0))
        message = str(exc_info.value)
        assert missing in message
        assert "bbox=" in message

    def test_value_error_preserves_chain_on_inverted_bbox(self, page_png):
        # The wrapper uses `raise ... from e`, so __cause__ is set to the
        # underlying CropError subclass. On the inverted-bbox path the cause
        # is an EmptyCropError (a CropError subclass).
        with pytest.raises(ValueError) as exc_info:
            crop_from_page_ref(page_png, (100.0, 100.0, 50.0, 50.0))
        assert isinstance(exc_info.value.__cause__, EmptyCropError)
        assert isinstance(exc_info.value.__cause__, CropError)

    def test_value_error_preserves_chain_on_missing_file(self, tmp_path):
        # On the missing-file path the cause is a CropError (raised directly
        # by crop_region when the page image is not found), NOT an
        # EmptyCropError. Pin both the chain presence and the cause type.
        missing = str(tmp_path / "does_not_exist.png")
        with pytest.raises(ValueError) as exc_info:
            crop_from_page_ref(missing, (10.0, 10.0, 100.0, 100.0))
        assert isinstance(exc_info.value.__cause__, CropError)
        assert not isinstance(exc_info.value.__cause__, EmptyCropError)


class TestCropFromPageRefPadding:
    """crop_from_page_ref applies _PADDING_PT (6.0) before conversion."""

    @pytest.fixture
    def page_png(self, tmp_path):
        path = tmp_path / "page.png"
        Image.new("RGB", (800, 600), "white").save(path, format="PNG")
        return str(path)

    def test_padding_expands_zero_area_to_valid_crop(self, page_png):
        # Zero-area bbox + 6pt padding each side = 12pt total.
        # At 150/72 DPI fallback scale (~2.083), 12pt -> ~25px each axis,
        # which exceeds _MIN_CROP_WIDTH/HEIGHT (16). Pin this rescue behaviour.
        result = crop_from_page_ref(page_png, (100.0, 100.0, 100.0, 100.0))
        assert result[:4] == b"\x89PNG"

    def test_padding_applied_in_pdf_point_space(self, page_png):
        # The wrapper calls crop_from_page_ref_compat which uses
        # CoordinateSpace.PDF_POINTS, so padding is in PDF points (72 DPI),
        # NOT image pixels. A 1pt x 1pt bbox in PDF points is tiny, but
        # padding rescues it. Pin that the PDF-points padding contract holds.
        result = crop_from_page_ref(page_png, (50.0, 50.0, 51.0, 51.0))
        assert result[:4] == b"\x89PNG"
        assert len(result) > 0


class TestCropFromPageRefRegionTypeIrrelevance:
    """crop_from_page_ref passes region_type to the signature but the underlying
    crop_from_page_ref_compat ignores it (only padding_pt is used).

    This is a pinned contract: the region_type parameter exists for signature
    compatibility with crop_region (which DOES use _DPI), but the
    page-ref-based path uses a single DPI (_PAGE_RENDER_DPI) regardless of
    region_type. A refactor that started applying per-region-type DPI here
    would change output sizes silently.
    """

    @pytest.fixture
    def page_png(self, tmp_path):
        path = tmp_path / "page.png"
        Image.new("RGB", (800, 600), "white").save(path, format="PNG")
        return str(path)

    def test_inline_display_mixed_produce_same_bytes(self, page_png):
        # Same bbox, different region_types — output must be identical because
        # region_type is ignored on the page-ref path.
        bbox = (10.0, 10.0, 200.0, 200.0)
        result_inline = crop_from_page_ref(page_png, bbox, MathRegionType.INLINE)
        result_display = crop_from_page_ref(page_png, bbox, MathRegionType.DISPLAY)
        result_mixed = crop_from_page_ref(page_png, bbox, MathRegionType.MIXED)
        assert result_inline == result_display == result_mixed

    def test_default_equals_mixed(self, page_png):
        bbox = (10.0, 10.0, 200.0, 200.0)
        result_default = crop_from_page_ref(page_png, bbox)
        result_mixed = crop_from_page_ref(page_png, bbox, MathRegionType.MIXED)
        assert result_default == result_mixed

    def test_default_region_type_signature_is_mixed(self):
        # Pin the actual default value via signature inspection. The
        # behaviour-equivalence tests above cannot detect a default change
        # because crop_from_page_ref_compat ignores region_type entirely;
        # only the signature carries the default contract.
        sig = inspect.signature(crop_from_page_ref)
        param = sig.parameters["region_type"]
        assert param.default is MathRegionType.MIXED
