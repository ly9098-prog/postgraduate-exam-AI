"""Real IR/freeze/split inputs with synthetic settings and external-I/O guards.

Use an empty cwd and --confcutdir=tests/pipeline to exclude the root conftest's
early settings import. Application imports here occur after fixture isolation.
"""

import builtins
import io
import os
import socket
import sqlite3
from pathlib import Path
from types import SimpleNamespace

PAGE = 7
OPTIONS = (
    {"A": "red-apple", "B": "blue-sea", "C": "green-tree", "D": "yellow-sun"},
    {"A": "white-swan", "B": "black-stone", "C": "brown-bear", "D": "pink-flower"},
)


def isolate_environment(monkeypatch, directory):
    path = os.environ.get("PATH", "")
    for name in tuple(os.environ):
        monkeypatch.delenv(name)
    values = {
        "PATH": path,
        "HOME": str(directory),
        "TMPDIR": str(directory),
        "APP_ENV": "test",
        "APP_SECRET": "synthetic-ir-freeze-binding-only",
        "DEPLOYMENT_PROFILE": "local_import",
        "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        "REDIS_URL": "",
        "OCR_ENABLED": "false",
        "OCR_EXECUTION_BACKEND": "disabled",
        "VECTOR_ENABLED": "false",
        "SENTRY_DSN": "",
        "STAGING_STORAGE_DIR": str(directory / "staging"),
        "STRUCTURE_FREEZE_MODE": "legacy",
        "DOMAIN_QUALITY_GATE_MODE": "off",
        "OCR_CANARY_ENABLED": "true",
        "IR_FREEZE_CANARY_PERCENT": "100",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(directory)


def install_io_guards(monkeypatch, attempts):
    def deny(*args, **kwargs):
        attempts.append("external connection")
        raise AssertionError("network/database access forbidden")

    def guard_open(original):
        def opening(path, *args, **kwargs):
            if isinstance(path, (str, bytes, os.PathLike)):
                if Path(os.fsdecode(path)).name == ".env":
                    attempts.append("dotenv read")
                    raise AssertionError("reading .env forbidden")
            return original(path, *args, **kwargs)

        return opening

    for target, name in (
        (socket.socket, "connect"),
        (socket.socket, "connect_ex"),
        (socket, "create_connection"),
        (socket, "getaddrinfo"),
        (sqlite3, "connect"),
    ):
        monkeypatch.setattr(target, name, deny)
    monkeypatch.setattr(builtins, "open", guard_open(builtins.open))
    monkeypatch.setattr(io, "open", guard_open(io.open))


def isolated_runtime(monkeypatch, tmp_path):
    attempts = []
    isolate_environment(monkeypatch, tmp_path)
    install_io_guards(monkeypatch, attempts)
    from app.core.config import settings
    from app.features import pipeline_orchestrator
    from app.features.document_ir_builder import blocks_to_document_ir
    from app.features.visual_boundary_detector import filter_book_layout_blocks_from_ir

    yield SimpleNamespace(
        settings=settings,
        pipeline_module=pipeline_orchestrator,
        build=blocks_to_document_ir,
        layout=filter_book_layout_blocks_from_ir,
    )
    assert attempts == [], "external access attempted, even if caught by a stage"


def question_text(number):
    stem = f"{number}. Which result is correct?"
    return "\n".join(
        [stem, *(f"{key}. {value}" for key, value in OPTIONS[number - 1].items())]
    )


def source_blocks(count):
    blocks = []
    for index in range(count):
        text = question_text(index + 1)
        top = 40 + 280 * index
        boxes = [
            {"bbox": [50, top + 25 * i, 550, top + 25 * i + 18], "conf": 0.99}
            for i, _ in enumerate(text.splitlines())
        ]
        blocks.append(
            {
                "page": PAGE,
                "block_index": 17 + 6 * index,
                "normalized_text": text,
                "text": text,
                "boxes": boxes,
                "page_width": 600,
                "page_height": 800,
            }
        )
    return blocks


def build_case(runtime, shape):
    count = 1 if shape == "single" else 2
    blocks = source_blocks(count)
    originals = tuple(block["normalized_text"] for block in blocks)
    doc = runtime.build(
        blocks, pipeline_id="ir-freeze-binding", source_bytes=b"synthetic-binding"
    )
    assert doc is not None
    assert len(doc.pages) == 1
    assert len(doc.pages[0].regions) == count
    assert tuple(region.text for region in doc.pages[0].regions) == originals
    if shape == "layout_page":
        blocks, diagnostics = runtime.layout(doc)
        assert diagnostics["enabled"] is True
        assert len(blocks) == 1
        assert blocks[0]["normalized_text"] == "\n".join(originals)
    else:
        assert [block["block_index"] for block in blocks] == [17, 23][:count]
    blocks[0]["_document_ir"] = doc
    return blocks, originals


def run_real_stages(runtime, monkeypatch, mode, shape):
    monkeypatch.setattr(runtime.settings, "STRUCTURE_FREEZE_MODE", mode)
    blocks, originals = build_case(runtime, shape)
    pipeline = runtime.pipeline_module.ImportPipeline(options={})
    frozen = pipeline._run_structure_freeze(blocks)
    if mode == "ir" or (mode == "ir_canary" and shape != "layout_page"):
        assert frozen["freeze_mode"] == mode
        assert len(frozen["frozen_option_registry_ir"]) == len(originals)
    if mode == "ir_canary" and shape != "layout_page":
        assert frozen["freeze_canary_fallback"] is False
    split = pipeline._run_split(blocks, import_mode="exam", source_type="pdf", **frozen)
    questions = split["raw_questions"]
    assert split["split_count"] == len(originals)
    assert split["split_diagnostics"]["failure_reason"] is None
    assert [q["number"] for q in questions] == list(range(1, len(originals) + 1))
    for index, question in enumerate(questions):
        assert question["page_start"] == question["page_end"] == PAGE
        assert question["has_options"] is True
        assert question["option_lines"] == OPTIONS[index]
    return questions, originals


def assert_bound_questions(questions, originals):
    for index, question in enumerate(questions):
        assert question["is_frozen"] is True
        assert question["_original_raw_text"] == originals[index]
        assert question["raw_question_text"] == originals[index].splitlines()[0]
        assert not question.get("has_grouped_options")
        assert "frozen_options_unmatched" not in question["risk_flags"]


def assert_unbound_questions(questions, originals):
    for index, question in enumerate(questions):
        assert question["is_frozen"] is False
        assert question["_original_raw_text"] is None
        assert question["raw_question_text"] == originals[index]
