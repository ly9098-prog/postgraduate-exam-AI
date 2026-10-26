"""One-pass PDF OCR and exercise-region selection with partial-result retention."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExtractedContent:
    """Hold the accepted blocks even if later region handling fails."""

    raw_blocks: list[dict]
    exercise_regions: list[dict] = field(default_factory=list)
    exercise_regions_missing: bool = False
    ocr_ok: bool = False


def filter_exercise_regions(
    content: ExtractedContent,
    exercise_regions: Any,
    *,
    ports: Callable[[str], Any],
) -> None:
    """Publish regions before deriving pages and replacing the block list."""
    content.exercise_regions = [
        {
            "start_page": r.start_page,
            "end_page": r.end_page,
            "confidence": r.confidence,
            "matched_keyword": r.matched_keyword,
        }
        for r in exercise_regions
    ]
    region_pages = ports("set")()
    for r in exercise_regions:
        for p in ports("range")(r.start_page, r.end_page + 1):
            region_pages.add(p)
    content.raw_blocks = [
        b for b in content.raw_blocks if b.get("page", 0) in region_pages
    ]
    ports("logger").info(
        "Exercise region detection found %d region(s), filtered to %d blocks",
        ports("len")(exercise_regions),
        ports("len")(content.raw_blocks),
    )


def detect_regions_from_ocr(
    content: ExtractedContent,
    settings: Any,
    import_mode: str,
    user_specified_range: Any,
    options: dict,
    *,
    ports: Callable[[str], Any],
) -> None:
    """Reuse accepted OCR text only when exercise discovery is applicable."""
    if (
        settings.EXERCISE_DETECTION_ENABLED
        and import_mode != "exam"
        and not user_specified_range
    ):
        from app.features.exercise_region_detector import detect_exercise_regions

        page_texts = ports("_extract_page_texts_from_blocks")(content.raw_blocks)
        exercise_regions = detect_exercise_regions(
            page_texts,
            config={
                "max_empty_pages": settings.EXERCISE_DETECTION_MAX_EMPTY_PAGES,
                "min_confidence": settings.EXERCISE_DETECTION_MIN_CONFIDENCE,
            },
        )
        if exercise_regions:
            filter_exercise_regions(content, exercise_regions, ports=ports)
            del exercise_regions
        else:
            content.exercise_regions_missing = True
            ports("logger").info(
                "Exercise detection found no regions, keeping all %d OCR blocks",
                ports("len")(content.raw_blocks),
            )
    elif user_specified_range:
        ports("logger").info(
            "Skipping exercise detection: user specified page range %s-%s",
            options.get("page_start"),
            options.get("page_end"),
        )


def accept_single_ocr_pass(
    pipeline: Any,
    pdf_source: bytes | str,
    options: dict,
    settings: Any,
    content: ExtractedContent,
    *,
    ports: Callable[[str], Any],
) -> None:
    """Accept OCR before region discovery, retaining it on discovery failures."""
    import_mode = options.get("import_mode", "auto")
    user_specified_range = options.get("page_start") or options.get("page_end")
    ocr_page_start = options.get("page_start") or 1
    ocr_page_end = options.get("page_end")
    ocr_blocks = ports("_ocr_scanned_pdf")(
        pdf_source,
        pipeline_id=pipeline.pipeline_id,
        page_start=ocr_page_start,
        page_end=ocr_page_end,
    )
    if ocr_blocks:
        content.raw_blocks = ocr_blocks
        content.ocr_ok = True
        detect_regions_from_ocr(
            content,
            settings,
            import_mode,
            user_specified_range,
            options,
            ports=ports,
        )
        ports("logger").info(
            "OCR succeeded: %d blocks", ports("len")(content.raw_blocks)
        )
    else:
        ports("logger").warning("OCR returned no blocks")


def attempt_pdf_ocr(
    pipeline: Any,
    pdf_source: bytes | str,
    options: dict,
    settings: Any,
    content: ExtractedContent,
    *,
    ports: Callable[[str], Any],
) -> None:
    """Keep the original warning and exception boundary around the OCR attempt."""
    try:
        accept_single_ocr_pass(
            pipeline,
            pdf_source,
            options,
            settings,
            content,
            ports=ports,
        )
    except ports("RuntimeError") as exc:
        ports("logger").warning("OCR fallback unavailable: %s", exc)
    except ports("Exception") as exc:
        ports("logger").warning(
            "OCR fallback failed, using original extraction: %s",
            exc,
        )
    if not content.ocr_ok:
        ports("logger").warning(
            "Local OCR returned no blocks; downstream ocr_correction stage "
            "will attempt PaddleOCR-VL via OCRFixRouter"
        )


def extract_pdf_content(
    pipeline: Any,
    pdf_source: bytes | str,
    options: dict,
    *,
    ports: Callable[[str], Any],
) -> ExtractedContent:
    """Extract the text layer, then attempt OCR only below the original threshold."""
    raw_blocks = ports("_extract_pdf_blocks")(
        pdf_source,
        page_start=options.get("page_start") or 1,
        page_end=options.get("page_end"),
    )
    content = ExtractedContent(raw_blocks)
    total_text = ports("sum")(ports("len")(b.get("text", "")) for b in raw_blocks)
    if total_text < 100:
        from app.core.config import settings

        if settings.OCR_ENABLED:
            ports("logger").info(
                "PDF text only %d chars, attempting PaddleOCR fallback",
                total_text,
            )
            attempt_pdf_ocr(
                pipeline, pdf_source, options, settings, content, ports=ports
            )
        else:
            ports("logger").warning(
                "PDF text only %d chars but OCR_ENABLED=false, cannot extract scanned content",
                total_text,
            )
    if not content.raw_blocks:
        raise ports("ValueError")(
            "PDF 中未提取到文本内容（文本层为空且 OCR 未启用或失败）"
        )
    return content
