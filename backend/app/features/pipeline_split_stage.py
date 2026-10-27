"""Run split preparation, recovery, overlap filtering and final publication in order."""

from __future__ import annotations

from functools import partial
from typing import Any

from app.features.pipeline_split_binding import (
    execute_split_questions,
    initialize_split_binding,
)
from app.features.pipeline_split_fallback import resolve_split_fallback
from app.features.pipeline_split_input import (
    filter_split_layout,
    initialize_split_input,
    merge_split_pages,
    resolve_split_options,
)
from app.features.pipeline_split_overlap import deduplicate_chunk_overlap
from app.features.pipeline_split_prose import (
    filter_book_pdf_prose,
    record_book_pdf_prose_from_blocks,
)
from app.features.pipeline_split_rebuild import rebuild_split_input
from app.features.pipeline_split_result import (
    finish_split_result,
    initialize_split_diagnostics,
)
from app.features.pipeline_split_state import SplitState, resolve_split_port


def run_split_stage(
    pipeline: Any,
    normalized_blocks: list[dict],
    structure: dict | None,
    keyword_arguments: dict,
    *,
    namespace: dict,
) -> dict:
    """Preserve stage order while leaving import transaction ownership outside split."""
    state = SplitState(pipeline, normalized_blocks, structure, keyword_arguments)
    ports = partial(resolve_split_port, namespace)
    initialize_split_input(state, ports=ports)
    merge_split_pages(state, ports=ports)
    filter_split_layout(state, ports=ports)
    resolve_split_options(state, ports=ports)
    initialize_split_binding(state)
    rebuild_split_input(state, ports=ports)
    execute_split_questions(state, ports=ports)
    initialize_split_diagnostics(state, ports=ports)
    filter_book_pdf_prose(state, ports=ports)
    record_book_pdf_prose_from_blocks(state, ports=ports)
    resolve_split_fallback(state, ports=ports)
    deduplicate_chunk_overlap(state, ports=ports)
    return finish_split_result(state, ports=ports)
