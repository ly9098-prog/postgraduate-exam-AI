"""Coordinate transform round-trip tests for P3 coordinate consistency."""

from __future__ import annotations

import numpy as np

from app.core.transform_tracker import TransformTracker


def test_identity_transform():
    """Tracker with no transforms: forward and back return same point."""
    tracker = TransformTracker(orig_width=200, orig_height=300)
    x, y = tracker.map_forward(50, 75)
    bx, by = tracker.map_back(x, y)
    assert abs(bx - 50) < 0.01, f"Expected 50, got {bx}"
    assert abs(by - 75) < 0.01, f"Expected 75, got {by}"


def test_crop_forward_back():
    """Crop 100px from top-left: forward then back returns original."""
    tracker = TransformTracker(orig_width=200, orig_height=300)
    tracker.record_crop(left=100, top=50)

    # A point at (150, 125) in original → (50, 75) in cropped
    fx, fy = tracker.map_forward(150, 125)
    assert abs(fx - 50) < 0.01, f"Expected 50, got {fx}"
    assert abs(fy - 75) < 0.01, f"Expected 75, got {fy}"

    bx, by = tracker.map_back(fx, fy)
    assert abs(bx - 150) < 0.01, f"Expected 150, got {bx}"
    assert abs(by - 125) < 0.01, f"Expected 125, got {by}"


def test_resize_forward_back():
    """Resize 50%: forward then back returns original."""
    tracker = TransformTracker(orig_width=200, orig_height=300)
    tracker.record_resize(scale_x=0.5, scale_y=0.5)

    fx, fy = tracker.map_forward(100, 200)
    assert abs(fx - 50) < 0.01, f"Expected 50, got {fx}"
    assert abs(fy - 100) < 0.01, f"Expected 100, got {fy}"

    bx, by = tracker.map_back(fx, fy)
    assert abs(bx - 100) < 0.01, f"Expected 100, got {bx}"
    assert abs(by - 200) < 0.01, f"Expected 200, got {by}"


def test_crop_then_resize_forward_back():
    """Crop then resize: round-trip stays within 0.5px error."""
    tracker = TransformTracker(orig_width=400, orig_height=500)
    tracker.record_crop(left=50, top=30)
    tracker.record_resize(scale_x=0.5, scale_y=0.5)

    original_points = [(60, 40), (200, 300), (350, 450), (80, 100)]
    for ox, oy in original_points:
        fx, fy = tracker.map_forward(ox, oy)
        bx, by = tracker.map_back(fx, fy)
        assert abs(bx - ox) < 0.5, f"X error too large at ({ox},{oy}): {bx} vs {ox}"
        assert abs(by - oy) < 0.5, f"Y error too large at ({ox},{oy}): {by} vs {oy}"


def test_bbox_round_trip():
    """BBox forward then back returns original within tolerance."""
    tracker = TransformTracker(orig_width=400, orig_height=500)
    tracker.record_crop(left=50, top=30)
    tracker.record_resize(scale_x=0.5, scale_y=0.5)

    original_bbox = (100, 80, 300, 400)
    pre_x0 = original_bbox[0] - 50  # crop offset
    pre_y0 = original_bbox[1] - 30
    pre_x1 = original_bbox[2] - 50
    pre_y1 = original_bbox[3] - 30
    forward_bbox = (
        pre_x0 * 0.5, pre_y0 * 0.5,
        pre_x1 * 0.5, pre_y1 * 0.5,
    )

    restored = tracker.map_bbox_back(forward_bbox)
    for i in range(4):
        assert abs(restored[i] - original_bbox[i]) < 0.5, (
            f"BBox element {i}: expected {original_bbox[i]}, got {restored[i]}"
        )


def test_to_ir_transforms():
    """TransformTracker.to_ir_transforms() returns list of dicts with name/matrix."""
    tracker = TransformTracker(orig_width=200, orig_height=300)
    tracker.record_crop(left=50, top=30)
    tracker.record_resize(scale_x=0.5, scale_y=0.5)

    ir = tracker.to_ir_transforms()
    assert len(ir) == 2
    assert ir[0]["name"] == "crop"
    assert "matrix" in ir[0]
    assert len(ir[0]["matrix"]) == 9  # 3x3 flattened
    assert ir[1]["name"] == "resize"
    assert "matrix" in ir[1]
    assert len(ir[1]["matrix"]) == 9


def test_to_dict_list_round_trip():
    """TransformTracker serializes and deserializes correctly via to_dict_list/from_dict_list."""
    tracker = TransformTracker(orig_width=200, orig_height=300)
    tracker.record_crop(left=50, top=30)
    tracker.record_resize(scale_x=0.5, scale_y=0.5)

    data = tracker.to_dict_list()
    restored = TransformTracker.from_dict_list(
        data, orig_width=200, orig_height=300,
    )

    assert restored.orig_width == 200
    assert restored.orig_height == 300
    assert len(restored.transforms) == 2
    assert restored.transforms[0].name == "crop"
    assert restored.transforms[1].name == "resize"

    # Round-trip after serialization
    fx, fy = restored.map_forward(60, 40)
    # (60-50)*0.5 = 5, (40-30)*0.5 = 5
    assert abs(fx - 5) < 0.01, f"Expected 5, got {fx}"
    assert abs(fy - 5) < 0.01, f"Expected 5, got {fy}"


def test_transform_record_bridge_to_document_ir():
    """transform_tracker.TransformRecord can be converted to document_ir.TransformRecord."""
    from app.core.transform_tracker import TransformRecord as TrackerRecord
    from app.core.document_ir import TransformRecord as IrRecord
    import numpy as np

    # A proper affine matrix (scale x,y + translation)
    mat = np.array([
        [0.5, 0.0, 10.0],
        [0.0, 0.5, 20.0],
        [0.0, 0.0, 1.0],
    ], dtype=np.float64)
    tracker_rec = TrackerRecord("resize", mat, description="scale 50% + translate")
    d = tracker_rec.to_dict()

    ir_rec = IrRecord(name=d["name"], matrix=d["matrix"], description=d.get("description", ""))
    assert ir_rec.name == "resize"
    assert ir_rec.matrix == [0.5, 0.0, 10.0, 0.0, 0.5, 20.0, 0.0, 0.0, 1.0]
    assert ir_rec.description == "scale 50% + translate"
