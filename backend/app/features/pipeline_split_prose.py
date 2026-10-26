"""Book/PDF prose filtering and block-only diagnostics."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.features.pipeline_split_state import SplitState


def filter_book_pdf_prose(state: SplitState, *, ports: Callable[[str], Any]) -> None:
    """Filter prose candidates with capped previews and accumulated counters."""
    if (
        not state.raw_questions
        or not ports("_is_book_import_mode")(state.keyword_arguments.get("import_mode"))
        or ports("str")(state.keyword_arguments.get("source_type") or "").lower()
        != "pdf"
    ):
        return
    kept_questions = []
    prose_skipped = 0
    prose_preview: list[dict] = []
    for question in state.raw_questions:
        if ports("_looks_like_book_pdf_prose_candidate")(question):
            prose_skipped += 1
            if ports("len")(prose_preview) < 20:
                import hashlib

                raw_text = ports("str")(question.get("raw_question_text") or "")
                prose_preview.append(
                    {
                        "page": question.get("page_start"),
                        "number": question.get("number"),
                        "text_hash": hashlib.md5(raw_text.encode()).hexdigest()[:12],
                        "text_len": ports("len")(raw_text),
                    }
                )
            continue
        kept_questions.append(question)
    if prose_skipped:
        state.raw_questions = kept_questions
        state.warnings.append(f"book_pdf_prose_skipped: {prose_skipped}")
        state.split_diagnostics["book_pdf_prose_skipped"] = (
            state.split_diagnostics.get("book_pdf_prose_skipped", 0) + prose_skipped
        )
        state.split_diagnostics["prose_skipped_count"] = (
            state.split_diagnostics.get("prose_skipped_count", 0) + prose_skipped
        )
        state.split_diagnostics.setdefault("prose_skipped_preview", []).extend(
            prose_preview
        )
        state.split_diagnostics["raw_question_count_after_prose_filter"] = ports("len")(
            state.raw_questions
        )


def record_book_pdf_prose_from_blocks(
    state: SplitState, *, ports: Callable[[str], Any]
) -> None:
    """Record prose previews only when no raw questions survived."""
    if (
        state.raw_questions
        or not ports("_is_book_import_mode")(state.keyword_arguments.get("import_mode"))
        or ports("str")(state.keyword_arguments.get("source_type") or "").lower()
        != "pdf"
    ):
        return
    previews: list[dict] = []
    for block in state.text_blocks:
        text = ports("str")(block.get("normalized_text") or "").strip()
        first_line = text.split("\n", 1)[0].strip()
        match = ports("re").match("^(\\d+)\\s*[.．、]\\s*", first_line)
        if not match:
            continue
        if ports("_BOOK_PDF_QUESTION_SIGNAL_RE").search(text) or ports("re").search(
            "(?:^|\\n)\\s*[A-D]\\s*[.．、:：)）]", text
        ):
            continue
        marker_count = ports("len")(ports("_BOOK_PDF_PROSE_MARKER_RE").findall(text))
        sentence_count = ports("len")(ports("_BOOK_PDF_SENTENCE_END_RE").findall(text))
        if marker_count < 2 or sentence_count < 2:
            continue
        previews.append(
            {
                "page": block.get("page"),
                "number": ports("int")(match.group(1)),
                "text": ports("re").sub("\\s+", " ", text)[:80],
            }
        )
        if ports("len")(previews) >= 20:
            break
    if previews:
        state.split_diagnostics["prose_skipped_count"] = ports("len")(previews)
        state.split_diagnostics["prose_skipped_preview"] = previews
