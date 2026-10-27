"""Invocation-owned dependencies and output for the visual crop stage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class VisualCropState:
    pipeline: Any
    page_image_refs: dict
    storage: Any
    virtual_import_id: str
    month: str
    hashlib: Any
    visual_region_type: Any
    crop_and_upload_region: Any
    logger: Any
    crop_warnings: list[str]
