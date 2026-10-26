"""Select extraction sources before projecting accepted blocks and diagnostics."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any

from app.features.pipeline_extract_diagnostics import (
    project_extract_result,
    resolve_extract_port,
)
from app.features.pipeline_extract_pdf import ExtractedContent, extract_pdf_content


def extract_non_pdf_content(
    file_content: bytes | None,
    file_path: str | None,
    pre_extracted_blocks: list[dict] | None,
    *,
    ports: Callable[[str], Any],
) -> ExtractedContent:
    """Copy structured OCR mappings or prefer cleaned bytes over an image path."""
    if pre_extracted_blocks:
        raw_blocks = [ports("dict")(block) for block in pre_extracted_blocks]
    else:
        text_source = file_content if file_content is not None else file_path
        if text_source is None:
            raise ports("ValueError")(
                "either file_content or file_path must be provided"
            )
        raw_blocks = ports("_extract_text_blocks")(text_source)
    return ExtractedContent(raw_blocks)


def run_extract_stage(
    pipeline: Any,
    file_content: bytes | None,
    source_type: str,
    file_path: str | None,
    pre_extracted_blocks: list[dict] | None,
    keyword_arguments: dict,
    *,
    namespace: dict,
) -> dict:
    """Preserve source precedence and defer diagnostic reads until extraction ends."""
    ports = partial(resolve_extract_port, namespace)
    if source_type == "pdf":
        pdf_source = file_path if file_path else file_content
        if pdf_source is None:
            raise ports("ValueError")(
                "either file_path or file_content must be provided"
            )
    if source_type == "pdf":
        options = keyword_arguments.get("options") or {}
        content = extract_pdf_content(pipeline, pdf_source, options, ports=ports)
    else:
        content = extract_non_pdf_content(
            file_content,
            file_path,
            pre_extracted_blocks,
            ports=ports,
        )
    return project_extract_result(
        content.raw_blocks,
        content.exercise_regions,
        content.exercise_regions_missing,
        keyword_arguments,
        ports=ports,
    )
