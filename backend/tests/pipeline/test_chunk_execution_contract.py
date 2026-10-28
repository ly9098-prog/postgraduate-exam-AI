"""Contract for one chunk's render, checkpoint, execution and projection order."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.core import config
from app.features import pipeline_checkpoint
from app.features import pipeline_orchestrator as orchestrator
from app.features.pipeline_orchestrator import ImportPipeline
from app.services import pdf_renderer_service


def _install_ports(monkeypatch):
    records = SimpleNamespace(
        events=[],
        pass_calls=[],
        import_hashes=[],
        renders=[],
        closes=[],
        diagnostics=SimpleNamespace(risk_flag_counts={"synthetic": 2}),
        exception_calls=[],
    )
    events = records.events

    monkeypatch.setattr(config.settings, "PDF_RENDER_PAGE_WINDOW", 0, raising=False)
    monkeypatch.setattr(pdf_renderer_service, "pdf_renderer", SimpleNamespace())
    monkeypatch.setattr(
        orchestrator,
        "bind_log_context",
        lambda **kwargs: events.append(("bind", kwargs)),
    )
    monkeypatch.setattr(
        orchestrator,
        "log_event",
        lambda logger, event, **kwargs: events.append((event, kwargs)),
    )
    monkeypatch.setattr(
        orchestrator,
        "_slim_chunk_diagnostics",
        lambda diagnostics: records.diagnostics,
    )
    monkeypatch.setattr(
        orchestrator,
        "logging",
        SimpleNamespace(getLogger=lambda name: SimpleNamespace(name=name)),
    )
    monkeypatch.setattr(
        orchestrator,
        "time",
        SimpleNamespace(monotonic=lambda: 10.25),
    )
    monkeypatch.setattr(
        orchestrator.logger,
        "exception",
        lambda *args: events.append(("unexpected", args)),
    )

    async def mark_running(db, pipeline_id, chunk_index):
        events.append(("mark_running", (db, pipeline_id, chunk_index)))

    async def invalidate(pipeline_id):
        events.append(("invalidate", pipeline_id))

    async def update_chunk(
        db,
        pipeline_id,
        chunk_index,
        *,
        status,
        batch_id,
        question_count,
        error_message,
    ):
        events.append(
            (
                "update_chunk",
                {
                    "db": db,
                    "pipeline_id": pipeline_id,
                    "chunk_index": chunk_index,
                    "status": status,
                    "batch_id": batch_id,
                    "question_count": question_count,
                    "error_message": error_message,
                },
            )
        )

    monkeypatch.setattr(pipeline_checkpoint, "mark_chunk_running", mark_running)
    monkeypatch.setattr(pipeline_checkpoint, "invalidate_progress_cache", invalidate)
    monkeypatch.setattr(pipeline_checkpoint, "update_chunk_status", update_chunk)
    return records


async def _invoke(pipeline, records, **overrides):
    arguments = {
        "chunk_index": 0,
        "page_start": 1,
        "logical_end": 2,
        "total_pages": 4,
        "is_last_chunk": False,
        "chunk_overlap": 1,
        "file_content": b"pdf",
        "file_path": None,
        "source_type": "pdf",
        "source_file": "synthetic.pdf",
        "subject": "math",
        "subject_id": 7,
        "opts": {"synthetic": True},
        "db": object(),
        "shared": {"watermark_patterns": []},
        "progress_callback": None,
        "started_at": "started",
        "seen_hashes": set(),
        "hash_index": None,
    }
    arguments.update(overrides)
    return await pipeline._execute_chunk(**arguments)


@pytest.mark.asyncio
async def test_completed_chunk_preserves_checkpoint_hash_and_log_order(monkeypatch):
    records = _install_ports(monkeypatch)
    pipeline = ImportPipeline()
    pipeline.pipeline_id = "pipeline-1"
    calls = []

    async def run_pass(**kwargs):
        calls.append(kwargs)
        return {
            "status": "completed",
            "stats": {"to_review": 3},
            "batch_id": "batch-1",
            "review_new_hashes": [("math", "hash-1", 9)],
            "diagnostics": {"split": {"layout_filter": 1}},
            "stages": {"review": {"status": "completed"}},
        }

    pipeline._run_single_pass = run_pass
    index = SimpleNamespace(add_import=lambda *args: records.import_hashes.append(args))
    result = await _invoke(pipeline, records, hash_index=index)

    assert calls[0]["page_end"] == 3
    assert calls[0]["chunk_seen_hashes"] is not None
    assert result["status"] == "completed"
    assert result["question_count"] == 3
    assert result["diagnostics"] is records.diagnostics
    assert records.import_hashes == [("math", "hash-1", 9)]
    names = [event[0] for event in records.events]
    assert names.index("mark_running") < names.index("pipeline.chunk.start")
    assert names.index("invalidate") < names.index("pipeline.chunk.start")
    assert names.index("invalidate") < names.index("pipeline.chunk.finish")
    assert records.events[-1][0] == "pipeline.chunk.finish"
    assert records.events[-1][1]["question_count"] == 3


@pytest.mark.asyncio
async def test_failed_chunk_status_and_exception_keep_failure_isolation(monkeypatch):
    records = _install_ports(monkeypatch)
    pipeline = ImportPipeline()
    pipeline.pipeline_id = "pipeline-failed"

    async def failed_pass(**_kwargs):
        return {"status": "failed", "errors": ["synthetic failure"]}

    pipeline._run_single_pass = failed_pass
    failed = await _invoke(pipeline, records)
    assert failed["status"] == "failed"
    assert failed["error_message"] == "synthetic failure"

    async def raised_pass(**_kwargs):
        raise RuntimeError("escaped failure")

    pipeline._run_single_pass = raised_pass
    raised = await _invoke(pipeline, records)
    assert raised["status"] == "failed"
    assert raised["error_message"] == "RuntimeError: escaped failure"
    assert any(event[0] == "unexpected" for event in records.events)


@pytest.mark.asyncio
async def test_render_page_window_streams_and_closes_every_page(monkeypatch):
    records = _install_ports(monkeypatch)
    monkeypatch.setattr(config.settings, "PDF_RENDER_PAGE_WINDOW", 1, raising=False)

    class Page:
        def __init__(self, number, payload):
            self.page_number = number
            self.png_bytes = payload

        async def aclose(self):
            records.closes.append(self.page_number)

    async def iter_pages(**_kwargs):
        yield Page(1, b"one")
        yield Page(2, b"two")

    monkeypatch.setattr(
        pdf_renderer_service,
        "pdf_renderer",
        SimpleNamespace(iter_pages=iter_pages),
    )
    pipeline = ImportPipeline()
    pipeline.pipeline_id = "pipeline-render"

    async def run_pass(**kwargs):
        records.pass_calls.append(kwargs)
        return {"status": "completed"}

    pipeline._run_single_pass = run_pass
    result = await _invoke(pipeline, records)

    assert result["status"] == "completed"
    assert records.pass_calls[0]["page_images"] == {1: b"one", 2: b"two"}
    assert records.closes == [1, 2]


@pytest.mark.asyncio
async def test_cancelled_chunk_propagates_without_terminal_checkpoint(monkeypatch):
    records = _install_ports(monkeypatch)
    pipeline = ImportPipeline()
    pipeline.pipeline_id = "pipeline-cancelled"

    async def cancelled_pass(**_kwargs):
        raise asyncio.CancelledError()

    pipeline._run_single_pass = cancelled_pass
    with pytest.raises(asyncio.CancelledError):
        await _invoke(pipeline, records)

    assert not any(event[0] == "update_chunk" for event in records.events)
    assert not any(event[0] == "pipeline.chunk.finish" for event in records.events)


@pytest.mark.asyncio
async def test_log_event_is_resolved_live_after_mark_running(monkeypatch):
    records = _install_ports(monkeypatch)
    replacement_events = []

    def replacement_log(logger, event, **kwargs):
        replacement_events.append((event, kwargs))

    async def mark_running(_db, _pipeline_id, _chunk_index):
        monkeypatch.setattr(orchestrator, "log_event", replacement_log)

    monkeypatch.setattr(pipeline_checkpoint, "mark_chunk_running", mark_running)
    pipeline = ImportPipeline()
    pipeline.pipeline_id = "pipeline-live-log"

    async def run_pass(**_kwargs):
        return {"status": "completed"}

    pipeline._run_single_pass = run_pass
    await _invoke(pipeline, records)

    assert [event[0] for event in replacement_events] == [
        "pipeline.chunk.start",
        "pipeline.chunk.finish",
    ]
    assert not any(
        event[0] in {"pipeline.chunk.start", "pipeline.chunk.finish"}
        for event in records.events
    )


@pytest.mark.asyncio
async def test_effective_page_end_is_resolved_live_after_mark_running(monkeypatch):
    records = _install_ports(monkeypatch)
    pipeline = ImportPipeline()
    pipeline.pipeline_id = "pipeline-live-min"
    pass_calls = []

    async def mark_running(_db, _pipeline_id, _chunk_index):
        monkeypatch.setattr(
            orchestrator, "min", lambda _left, _right: 99, raising=False
        )

    monkeypatch.setattr(pipeline_checkpoint, "mark_chunk_running", mark_running)

    async def run_pass(**kwargs):
        pass_calls.append(kwargs)
        return {"status": "completed"}

    pipeline._run_single_pass = run_pass
    result = await _invoke(pipeline, records)

    assert result["effective_page_end"] == 99
    assert pass_calls[0]["page_end"] == 99


@pytest.mark.asyncio
async def test_finish_clock_and_projection_ports_are_resolved_live(monkeypatch):
    records = _install_ports(monkeypatch)
    live_diagnostics = SimpleNamespace(risk_flag_counts={"live": 1})
    pipeline = ImportPipeline()
    pipeline.pipeline_id = "pipeline-live-fields"

    async def run_pass(**_kwargs):
        monkeypatch.setattr(
            orchestrator,
            "time",
            SimpleNamespace(monotonic=lambda: 20.25),
        )
        monkeypatch.setattr(
            orchestrator,
            "_slim_chunk_diagnostics",
            lambda _diagnostics: live_diagnostics,
        )
        return {
            "status": "completed",
            "stats": {"to_review": 1},
            "diagnostics": {"split": {"live": True}},
        }

    pipeline._run_single_pass = run_pass
    result = await _invoke(pipeline, records)

    assert result["diagnostics"] is live_diagnostics
    finish = next(
        event for event in records.events if event[0] == "pipeline.chunk.finish"
    )
    assert finish[1]["duration_ms"] == 10_000


@pytest.mark.asyncio
async def test_round_is_resolved_live_during_finish(monkeypatch):
    records = _install_ports(monkeypatch)
    pipeline = ImportPipeline()
    pipeline.pipeline_id = "pipeline-live-round"

    async def run_pass(**_kwargs):
        monkeypatch.setattr(orchestrator, "round", lambda _value: 777, raising=False)
        return {"status": "completed"}

    pipeline._run_single_pass = run_pass
    await _invoke(pipeline, records)

    finish = next(
        event for event in records.events if event[0] == "pipeline.chunk.finish"
    )
    assert finish[1]["duration_ms"] == 777


@pytest.mark.asyncio
async def test_exception_logger_is_resolved_live(monkeypatch):
    records = _install_ports(monkeypatch)
    replacement_calls = []
    pipeline = ImportPipeline()
    pipeline.pipeline_id = "pipeline-live-logger"

    async def raised_pass(**_kwargs):
        monkeypatch.setattr(
            orchestrator.logger,
            "exception",
            lambda *args: replacement_calls.append(args),
        )
        raise RuntimeError("live failure")

    pipeline._run_single_pass = raised_pass
    result = await _invoke(pipeline, records)

    assert result["status"] == "failed"
    assert replacement_calls
    assert not any(event[0] == "unexpected" for event in records.events)


@pytest.mark.asyncio
async def test_exception_and_type_are_resolved_live(monkeypatch):
    records = _install_ports(monkeypatch)
    pipeline = ImportPipeline()
    pipeline.pipeline_id = "pipeline-live-type"

    async def raised_pass(**_kwargs):
        monkeypatch.setattr(orchestrator, "Exception", RuntimeError, raising=False)
        monkeypatch.setattr(
            orchestrator,
            "type",
            lambda _exc: SimpleNamespace(__name__="LiveType"),
            raising=False,
        )
        raise RuntimeError("live failure")

    pipeline._run_single_pass = raised_pass
    result = await _invoke(pipeline, records)

    assert result["status"] == "failed"
    assert result["error_message"] == "LiveType: live failure"
