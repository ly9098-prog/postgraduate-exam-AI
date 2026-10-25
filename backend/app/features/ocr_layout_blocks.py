"""Build layout-capable OCR blocks from an image OCR result."""

from __future__ import annotations

import io
import logging
from typing import Any

logger = logging.getLogger(__name__)


def build_pre_extracted_ocr_blocks(
    *,
    image_bytes: bytes,
    cleaned_text: str,
    ocr_result: dict[str, Any],
) -> list[dict]:
    """Return one block per OCR line, or one geometry-free fallback block."""
    width, height = _image_dimensions(image_bytes)
    engine_fingerprint = str(ocr_result.get("engine_fingerprint") or "")
    raw_lines = ocr_result.get("lines")
    blocks: list[dict] = []
    if isinstance(raw_lines, list):
        for index, line in enumerate(raw_lines):
            block = _line_block(
                line,
                index=index,
                width=width,
                height=height,
                fingerprint=engine_fingerprint,
            )
            if block is not None:
                blocks.append(block)
    if blocks:
        return blocks
    return _fallback_block(
        cleaned_text,
        ocr_result.get("boxes"),
        width=width,
        height=height,
        fingerprint=engine_fingerprint,
    )


def _image_dimensions(image_bytes: bytes) -> tuple[int, int]:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(image_bytes)) as image:
            return image.size
    except Exception as exc:
        logger.debug("Unable to read image dimensions for OCR block: %s", exc)
        return 0, 0


def _line_block(
    line: object,
    *,
    index: int,
    width: int,
    height: int,
    fingerprint: str,
) -> dict | None:
    if not isinstance(line, dict):
        return None
    text = str(line.get("text") or "").strip()
    if not text:
        return None
    bbox = line.get("bbox")
    valid_bbox = (
        isinstance(bbox, (list, tuple))
        and len(bbox) == 4
        and all(isinstance(value, (int, float)) for value in bbox)
    )
    confidence = line.get("confidence", line.get("conf", 0.0))
    boxes = (
        [{"bbox": list(bbox), "conf": float(confidence or 0.0), "text": text}]
        if valid_bbox
        else []
    )
    return _block(
        index,
        text,
        boxes,
        width=width,
        height=height,
        fingerprint=fingerprint,
    )


def _fallback_block(
    cleaned_text: str,
    boxes: object,
    *,
    width: int,
    height: int,
    fingerprint: str,
) -> list[dict]:
    box_entries = boxes if isinstance(boxes, list) else []
    return [
        _block(
            0,
            cleaned_text,
            box_entries,
            width=width,
            height=height,
            fingerprint=fingerprint,
        )
    ]


def _block(
    index: int,
    text: str,
    boxes: list,
    *,
    width: int,
    height: int,
    fingerprint: str,
) -> dict:
    return {
        "page": 1,
        "block_index": index,
        "text": text,
        "boxes": boxes,
        "page_width": width,
        "page_height": height,
        "source": "ocr",
        "has_boxes": bool(boxes),
        "engine_fingerprint": fingerprint,
    }
