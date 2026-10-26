"""Synthetic extraction ports; no file, OCR engine, or provider is contacted."""

from __future__ import annotations

from types import SimpleNamespace

from app.core.config import settings
from app.features import exercise_region_detector
from app.features import pipeline_orchestrator as orchestrator


class ObservedMapping(dict):
    """Record repeated reads and allow a read to replace a live patch port."""

    def __init__(self, values, events, hook=lambda _key: None):
        super().__init__(values)
        self.events = events
        self.hook = hook

    def get(self, key, default=None):
        self.events.append(key)
        self.hook(key)
        return super().get(key, default)


def make_extract_harness(monkeypatch):
    harness = SimpleNamespace(
        trace=[],
        warnings=[],
        infos=[],
        pdf_blocks=[{"text": "text"}],
        ocr_blocks=[{"page": 1, "text": "OCR"}],
        regions=[],
        text_blocks=[{"text": "decoded"}],
        ocr_error=None,
        detect_error=None,
    )
    for key, value in {
        "OCR_ENABLED": True,
        "EXERCISE_DETECTION_ENABLED": True,
        "EXERCISE_DETECTION_MAX_EMPTY_PAGES": 2,
        "EXERCISE_DETECTION_MIN_CONFIDENCE": 0.8,
    }.items():
        monkeypatch.setattr(settings, key, value)

    def pdf(source, **kwargs):
        harness.trace.append(("pdf", source, kwargs))
        return harness.pdf_blocks

    def ocr(source, **kwargs):
        harness.trace.append(("ocr", source, kwargs))
        if harness.ocr_error is not None:
            raise harness.ocr_error
        return harness.ocr_blocks

    def page_texts(blocks):
        harness.trace.append(("page_texts", blocks is harness.ocr_blocks))
        return {1: "synthetic OCR text"}

    def detect(texts, **kwargs):
        harness.trace.append(("detect", texts, kwargs))
        if harness.detect_error is not None:
            raise harness.detect_error
        return harness.regions

    def text(source):
        harness.trace.append(("text", source))
        return harness.text_blocks

    monkeypatch.setattr(orchestrator, "_extract_pdf_blocks", pdf)
    monkeypatch.setattr(orchestrator, "_ocr_scanned_pdf", ocr)
    monkeypatch.setattr(orchestrator, "_extract_page_texts_from_blocks", page_texts)
    monkeypatch.setattr(orchestrator, "_extract_text_blocks", text)
    monkeypatch.setattr(exercise_region_detector, "detect_exercise_regions", detect)
    monkeypatch.setattr(
        orchestrator,
        "logger",
        SimpleNamespace(
            info=lambda *args: harness.infos.append(args),
            warning=lambda *args: harness.warnings.append(args),
        ),
    )
    harness.pipeline = orchestrator.ImportPipeline()
    harness.pipeline.pipeline_id = "extract-contract"
    return harness
