"""Synthetic image/PDF, OCR and candidate ports for the real VL rebuild method."""

import os
import sys
from types import SimpleNamespace

from app.core import deployment_profile
from app.features import (
    ocr_correction_common,
    option_recovery,
    question_type_classifier,
)
from app.features import pipeline_orchestrator as module


def observe(h, name, value=None):
    h.events.append(name)
    h.records.setdefault(name, []).append(value)
    if name in h.hooks:
        return h.hooks[name](value)


def fail_at(h, name, error):
    def fail(_):
        raise error

    h.hooks[name] = fail


def install_image(monkeypatch, h):
    class File:
        def __enter__(self):
            observe(h, "file_enter")
            return self

        def read(self):
            observe(h, "file_read")
            return h.image

        def __exit__(self, kind, error, traceback):
            observe(h, "file_exit", (kind, error))
            return h.suppress_file

    def open_file(path, mode):
        observe(h, "file_open", (path, mode))
        return File()

    original = os.path.isfile

    def isfile(path):
        if isinstance(path, str) and path.startswith("/synthetic/"):
            observe(h, "isfile", path)
            return h.exists
        return original(path)

    monkeypatch.setattr(module, "open", open_file, raising=False)
    monkeypatch.setattr(os.path, "isfile", isfile)


def install_pdf(monkeypatch, h):
    class Page:
        def __init__(self, number):
            self.number = number

        def get_pixmap(self, **kwargs):
            observe(h, "pixmap", (self.number, kwargs))
            return SimpleNamespace(
                width=100 + self.number,
                height=200 + self.number,
                tobytes=lambda fmt: (
                    observe(h, "png", (self.number, fmt)) or h.pngs[self.number - 1]
                ),
            )

    class Document:
        def __len__(self):
            observe(h, "page_count")
            return len(h.pngs)

        def __getitem__(self, number):
            observe(h, "page", number)
            return Page(number + 1)

        def close(self):
            observe(h, "close_pdf")

    def open_pdf(path, **kwargs):
        observe(h, "open_pdf", (path, kwargs))
        return Document()

    monkeypatch.setitem(sys.modules, "fitz", SimpleNamespace(open=open_pdf))


def install_router(monkeypatch, h):
    class Router:
        def __init__(self):
            observe(h, "construct_router")

        def configure(self, config):
            observe(h, "configure", config)

        def fix(self, **kwargs):
            observe(h, "fix", kwargs)
            return kwargs

    def run(call):
        observe(h, "run", call)
        return h.results.get(call["image"])

    def profile():
        observe(h, "profile")
        return (
            deployment_profile.DeploymentProfile.CLOUD_API
            if h.cloud
            else deployment_profile.DeploymentProfile.LOCAL_IMPORT
        )

    def pp(image):
        observe(h, "pp", image)
        return h.pp.get(image, "")

    monkeypatch.setitem(
        sys.modules,
        "app.features.ocr_fix.router",
        SimpleNamespace(OCRFixRouter=Router, STRATEGY_MANUAL="manual-contract"),
    )
    monkeypatch.setitem(
        sys.modules, "app.services.ocr_service", SimpleNamespace(ocr_raw_text=pp)
    )
    monkeypatch.setattr(
        deployment_profile, "detect_deployment_profile", profile, raising=False
    )
    monkeypatch.setattr(module, "_run_coro_in_loop", run)


def install_options(monkeypatch, h):
    def detect(text):
        observe(h, "detect", text)
        return h.detection.get(text, bool(h.options.get(text)))

    def extract(text):
        observe(h, "extract", text)
        return h.options.get(text, {})

    def repair(vl, pp, original):
        observe(h, "repair", (vl, pp, original))
        return h.repaired if h.repaired is not None else vl

    def recover(best, pp, original):
        observe(h, "recover", (best, pp, original))
        return h.recovery

    monkeypatch.setattr(question_type_classifier, "detect_options_from_text", detect)
    monkeypatch.setattr(question_type_classifier, "extract_options_from_text", extract)
    monkeypatch.setattr(ocr_correction_common, "repair_option_structure", repair)
    monkeypatch.setattr(option_recovery, "recover_options_from_sources", recover)
    monkeypatch.setattr(
        module,
        "logger",
        SimpleNamespace(
            info=lambda *args: observe(h, "info", args),
            warning=lambda *args: observe(h, "warning", args),
        ),
    )


def make_harness(monkeypatch):
    layout = [
        {"type": "table", "nested": []},
        {"label": "TABLE_CAPTION"},
        {"type": "table_image"},
        {"type": "text"},
        None,
    ]
    result = SimpleNamespace(
        fixed_text=" VL:A B C ", metadata={"layout_blocks": layout}
    )
    h = SimpleNamespace(
        events=[],
        records={},
        hooks={},
        exists=True,
        suppress_file=False,
        cloud=False,
        image=b"image",
        pngs=[b"one", b"two"],
        pp={b"image": "PP:A B", b"one": "PP:A B", b"two": "PP:A B"},
        results={b"image": result, b"one": result, b"two": result},
        detection={},
        options={
            "PP:A B": {"A": "pA", "B": "pB"},
            "VL:A B C": {"A": "vA", "B": "vB", "C": "vC"},
        },
        repaired=None,
        recovery=SimpleNamespace(
            options={}, text="recovered", repaired_keys=[], mirror_repairs=0
        ),
        result=result,
        layout=layout,
    )
    h.arguments = {
        "file_path": "/synthetic/input.png",
        "original_blocks": [{"page": 1, "page_width": 801, "page_height": 1201}],
        "vl_config": {
            "api_key": "synthetic-token",
            "api_base_url": "synthetic-base",
            "model_name": "synthetic-model",
        },
        "original_raw_text": "",
    }
    install_image(monkeypatch, h)
    install_pdf(monkeypatch, h)
    install_router(monkeypatch, h)
    install_options(monkeypatch, h)
    return h


def execute(h, **overrides):
    return module.ImportPipeline._run_vl_rebuild_blocks(
        object(), **{**h.arguments, **overrides}
    )
