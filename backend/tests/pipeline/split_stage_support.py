"""Synthetic split-stage boundaries without OCR, files or provider calls."""

from types import SimpleNamespace

from app.features import pipeline_orchestrator as orchestrator


def question(number=1, page=1, **values):
    return {
        "number": number,
        "page_start": page,
        "page_end": page,
        "raw_question_text": f"question {number}",
        "has_options": True,
        "option_lines": {"A": "a", "B": "b", "C": "c", "D": "d"},
        **values,
    }


def split_harness(monkeypatch):
    harness = SimpleNamespace(
        events=[],
        questions=[question()],
        merged=None,
        links=[],
        merge_warnings=[],
        merge_results=[],
        rebuilt=None,
        infos=[],
        warnings=[],
    )

    def merge(blocks):
        harness.events.append(("merge", blocks))
        return (
            harness.merged if harness.merged is not None else blocks,
            harness.links,
            harness.merge_warnings,
            harness.merge_results,
        )

    def split(blocks, **kwargs):
        harness.events.append(("split", blocks, kwargs))
        return harness.questions

    def rebuild(*args, **kwargs):
        harness.events.append(("rebuild", args, kwargs))
        return harness.rebuilt

    harness.pipeline = orchestrator.ImportPipeline()
    monkeypatch.setattr(orchestrator, "_merge_cross_page_blocks", merge)
    monkeypatch.setattr(orchestrator, "split_questions", split)
    monkeypatch.setattr(
        orchestrator,
        "_looks_like_book_pdf_prose_candidate",
        lambda question: question.get("prose", False),
    )
    monkeypatch.setattr(harness.pipeline, "_run_vl_rebuild_blocks", rebuild)
    install_split_observers(monkeypatch, harness)
    harness.blocks = [{"page": 1, "normalized_text": "1. question"}]
    return harness


def install_split_observers(monkeypatch, harness):
    def log_stage(*args, **kwargs):
        harness.events.append(("multi_blank", args, kwargs))

    def freeze(*args, **kwargs):
        harness.events.append(("freeze", args, kwargs))

    monkeypatch.setattr(orchestrator, "_safe_hash_preview", lambda value: "raw-hash")
    monkeypatch.setattr(orchestrator, "_log_multi_blank_stage", log_stage)
    monkeypatch.setattr(orchestrator, "_apply_frozen_options", freeze)
    monkeypatch.setattr(
        orchestrator,
        "logger",
        SimpleNamespace(
            info=lambda *args: harness.infos.append(args),
            warning=lambda *args: harness.warnings.append(args),
        ),
    )
