"""Coordinate transform tracking for OCR preprocessing.

Records each preprocessing transform (crop, deskew, resize, quality enhancement)
as a 3x3 affine matrix, enabling bbox/polygon coordinates to be mapped back
to the original page coordinate space.

Usage::

    tracker = TransformTracker(orig_width=2000, orig_height=3000)
    # After each transform:
    tracker.record("crop", matrix, description="crop blank margins")
    tracker.record("resize", matrix, description="resize to max side")

    # Map detection boxes back to original coordinates:
    orig_bbox = tracker.map_back(output_bbox)
"""

from __future__ import annotations

from typing import Any

import numpy as np


def _identity() -> np.ndarray:
    return np.eye(3, dtype=np.float64)


def _translate_matrix(dx: float, dy: float) -> np.ndarray:
    mat = _identity()
    mat[0, 2] = dx
    mat[1, 2] = dy
    return mat


def _scale_matrix(sx: float, sy: float) -> np.ndarray:
    mat = _identity()
    mat[0, 0] = sx
    mat[1, 1] = sy
    return mat


def _rotate_matrix(angle_deg: float, cx: float = 0, cy: float = 0) -> np.ndarray:
    """Rotation around (cx, cy) in degrees (counter-clockwise)."""
    rad = np.radians(angle_deg)
    cos_a = np.cos(rad)
    sin_a = np.sin(rad)
    # Translate to origin, rotate, translate back
    t1 = _translate_matrix(-cx, -cy)
    r = np.array(
        [
            [cos_a, -sin_a, 0],
            [sin_a, cos_a, 0],
            [0, 0, 1],
        ],
        dtype=np.float64,
    )
    t2 = _translate_matrix(cx, cy)
    return t2 @ r @ t1


class TransformRecord:
    """A single recorded transform in the preprocessing pipeline."""

    def __init__(
        self,
        name: str,
        matrix: np.ndarray,
        description: str = "",
    ):
        self.name = name
        self.matrix = matrix.copy()
        self.description = description

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "matrix": self.matrix.flatten().tolist(),
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TransformRecord:
        mat = np.array(data["matrix"], dtype=np.float64).reshape(3, 3)
        return cls(
            name=data["name"],
            matrix=mat,
            description=data.get("description", ""),
        )


class TransformTracker:
    """Accumulates geometric transforms applied to an image during preprocessing.

    Maintains a combined forward matrix (input -> current) and can compute
    the inverse mapping (current -> input).
    """

    def __init__(self, orig_width: float = 0, orig_height: float = 0):
        self.orig_width = orig_width
        self.orig_height = orig_height
        self._transforms: list[TransformRecord] = []
        self._combined = _identity()

    @property
    def transforms(self) -> list[TransformRecord]:
        return list(self._transforms)

    @property
    def combined_matrix(self) -> np.ndarray:
        return self._combined.copy()

    @property
    def inverse_matrix(self) -> np.ndarray:
        """Return the inverse of the combined transform (current -> original)."""
        return np.linalg.inv(self._combined)

    def record(self, name: str, matrix: np.ndarray, description: str = "") -> None:
        """Record a transform and update the combined matrix.

        The *matrix* represents the transform applied to coordinates:
        ``current_coord = matrix @ previous_coord``
        """
        self._transforms.append(TransformRecord(name, matrix, description))
        self._combined = matrix @ self._combined

    def record_crop(self, left: float, top: float, **_kw: Any) -> None:
        """Record a crop operation (origin shift by -left, -top)."""
        self.record(
            "crop",
            _translate_matrix(-left, -top),
            description=f"crop offset ({left}, {top})",
        )

    def record_resize(self, scale_x: float, scale_y: float, **_kw: Any) -> None:
        """Record a resize operation."""
        self.record(
            "resize",
            _scale_matrix(scale_x, scale_y),
            description=f"resize ({scale_x:.4f}, {scale_y:.4f})",
        )

    def record_rotate(self, angle_deg: float, cx: float = 0, cy: float = 0) -> None:
        """Record a rotation operation."""
        self.record(
            "rotate",
            _rotate_matrix(angle_deg, cx, cy),
            description=f"rotate {angle_deg:.1f}deg around ({cx}, {cy})",
        )

    def map_forward(self, x: float, y: float) -> tuple[float, float]:
        """Map a point from original coordinates to current (preprocessed) space."""
        pt = self._combined @ np.array([x, y, 1], dtype=np.float64)
        return (float(pt[0] / pt[2]), float(pt[1] / pt[2]))

    def map_back(self, x: float, y: float) -> tuple[float, float]:
        """Map a point from current (preprocessed) back to original coordinates."""
        inv = self.inverse_matrix
        pt = inv @ np.array([x, y, 1], dtype=np.float64)
        return (float(pt[0] / pt[2]), float(pt[1] / pt[2]))

    def map_bbox_back(
        self, bbox: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        """Map a BBox (x0, y0, x1, y1) back to original coordinates."""
        x0, y0 = self.map_back(bbox[0], bbox[1])
        x1, y1 = self.map_back(bbox[2], bbox[3])
        return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))

    def to_dict_list(self) -> list[dict[str, Any]]:
        return [t.to_dict() for t in self._transforms]

    def to_ir_transforms(self) -> list[dict[str, Any]]:
        """Return transforms in DocumentIR-compatible format."""
        return self.to_dict_list()

    def record_metadata(self, key: str, value: Any) -> None:
        """Record non-geometric metadata (e.g. quality metrics, enhancement strategy)."""
        if not hasattr(self, "_metadata"):
            self._metadata: dict[str, Any] = {}
        self._metadata[key] = value

    @property
    def metadata(self) -> dict[str, Any]:
        return getattr(self, "_metadata", {})

    @classmethod
    def from_dict_list(
        cls,
        data: list[dict],
        orig_width: float = 0,
        orig_height: float = 0,
    ) -> TransformTracker:
        tracker = cls(orig_width=orig_width, orig_height=orig_height)
        for d in data:
            tracker._transforms.append(TransformRecord.from_dict(d))
        # Rebuild combined matrix
        tracker._combined = _identity()
        for t in tracker._transforms:
            tracker._combined = t.matrix @ tracker._combined
        return tracker

    def reset(self) -> None:
        self._transforms.clear()
        self._combined = _identity()
