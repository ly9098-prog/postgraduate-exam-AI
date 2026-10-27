"""Synthetic PDF/render/engine ports; no file or engine initialization."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.features import pipeline_orchestrator as target


def make_scan(monkeypatch):
    h = SimpleNamespace(events=[], pages=5, boxes={}, fallback={}, clock=0)
    configure_pdf(h)
    h.open = MagicMock(return_value=h.doc)
    h.ir = object()
    h.build = MagicMock(return_value=h.ir)
    h.reset = MagicMock()

    configure_engine(h)
    h.text = MagicMock(side_effect=lambda images: h.fallback)
    h.tags = MagicMock()
    h.progress = {}
    configure_ports(h, monkeypatch)
    h.run = lambda **kwargs: target._ocr_scanned_pdf(
        b"synthetic pdf", pipeline_id="scan", **kwargs
    )
    return h


def configure_pdf(h):
    h.doc = MagicMock()
    h.doc.__len__.side_effect = lambda: h.pages

    def render(index):
        page = MagicMock()

        def pixmap(*, dpi):
            h.events.append(("render", index + 1, dpi))
            pix = SimpleNamespace(width=800 + index, height=600 + index)
            pix.tobytes = lambda fmt: f"png{index + 1}".encode()
            return pix

        page.get_pixmap.side_effect = pixmap
        return page

    h.doc.__getitem__.side_effect = render
    h.doc.close.side_effect = lambda: h.events.append("close")


def configure_engine(h):
    def boxed(images, **kwargs):
        h.events.append(("boxed", images, kwargs))
        if isinstance(h.boxes, BaseException):
            raise h.boxes
        return {
            idx: h.boxes.get(
                idx, SimpleNamespace(failed=False, text=f"text{idx}", boxes=[])
            )
            for idx, _ in images
        }

    h.boxed = MagicMock(side_effect=boxed)


def configure_ports(h, monkeypatch):
    import gc
    import time

    from app.core import deployment_profile, ocr_profile
    from app.core.config import settings
    from app.services import ocr_service

    monkeypatch.setattr(target, "_open_pdf_doc", h.open)
    monkeypatch.setattr(target, "_blocks_to_document_ir", h.build)
    monkeypatch.setattr(target, "_ocr_progress", h.progress)
    monkeypatch.setattr(target, "set_tag", h.tags)
    monkeypatch.setattr(
        deployment_profile,
        "detect_deployment_profile",
        lambda: deployment_profile.DeploymentProfile.LOCAL_IMPORT,
    )
    h.profile = SimpleNamespace(timeout_seconds=0, max_workers=2)
    monkeypatch.setattr(ocr_profile, "get_ocr_profile", lambda: h.profile)
    monkeypatch.setattr(settings, "MAX_OCR_PAGES", 0)
    h.settings = settings
    monkeypatch.setattr(ocr_service, "ocr_pages_with_boxes", h.boxed)
    monkeypatch.setattr(ocr_service, "ocr_pages", h.text)
    monkeypatch.setattr(ocr_service, "reset_ocr_engine", h.reset)
    monkeypatch.setattr(gc, "collect", lambda: h.events.append("collect"))
    monkeypatch.setattr(time, "monotonic", lambda: h.clock)
    monkeypatch.delenv("OCR_RENDER_DPI", raising=False)
