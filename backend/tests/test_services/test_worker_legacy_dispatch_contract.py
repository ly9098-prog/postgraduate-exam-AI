"""Contracts for the legacy task-queue worker dispatch branches."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.services import task_queue_worker as worker


class Harness:
    def __init__(self, monkeypatch):
        self.monkeypatch = monkeypatch
        self.events = []
        self.paths = {}

        async def resolve(staging_id):
            self.events.append(("resolve", staging_id))
            return self.paths.get(staging_id, f"/work/{staging_id}")

        async def cleanup(path):
            self.events.append(("cleanup", path))

        monkeypatch.setattr(worker, "_resolve_staging_path", resolve)
        monkeypatch.setattr(worker, "async_cleanup_work_copy", cleanup)
        monkeypatch.setattr(
            worker,
            "logger",
            SimpleNamespace(
                info=lambda *args, **kwargs: self.events.append(("info", args)),
                warning=lambda *args, **kwargs: self.events.append(("warning", args)),
                debug=lambda *args, **kwargs: self.events.append(("debug", args)),
            ),
        )

    def task(self, task_type, **payload):
        return SimpleNamespace(
            task_type=task_type,
            task_id=payload.pop("_task_id", "task-1"),
            payload=payload,
        )


@pytest.fixture
def harness(monkeypatch):
    return Harness(monkeypatch)


@pytest.mark.asyncio
async def test_import_branch_preserves_kwargs_and_cleanup(harness, monkeypatch):
    from app.services import import_pipeline_service

    captured = []

    async def run(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(import_pipeline_service, "_run_pipeline_with_db", run)
    task = harness.task(
        worker.TASK_TYPE_IMPORT_PIPELINE,
        pipeline_id="pipeline-1",
        staging_object_id="staging-1",
        source_type="docx",
        source_file="a.docx",
        subject="数据结构",
        subject_id=3,
        options={"force": True},
        created_by=8,
        source_sha256="abc",
    )
    await worker._process_task(task)

    assert captured == [
        {
            "pipeline_id": "pipeline-1",
            "file_path": "/work/staging-1",
            "source_type": "docx",
            "source_file": "a.docx",
            "subject": "数据结构",
            "subject_id": 3,
            "options": {"force": True},
            "created_by": 8,
            "source_sha256": "abc",
        }
    ]
    assert harness.events[-1] == ("cleanup", "/work/staging-1")


@pytest.mark.asyncio
async def test_image_branch_rejects_empty_resolution_and_cleans_it(harness):
    harness.paths["staging-1"] = ""
    task = harness.task(
        worker.TASK_TYPE_IMAGE_PIPELINE,
        staging_object_id="staging-1",
    )
    with pytest.raises(FileNotFoundError, match="Staging object staging-1 not found"):
        await worker._process_task(task)
    assert harness.events[-1] == ("cleanup", "")


@pytest.mark.asyncio
async def test_excel_branch_reads_bytes_then_imports_writer(
    harness, monkeypatch, tmp_path
):
    from app.features import pipeline_orchestrator, question_import_writer

    source = tmp_path / "source.xlsx"
    source.write_bytes(b"excel-bytes")
    harness.paths["staging-1"] = str(source)
    captured = []
    import_excel = object()

    async def run(**kwargs):
        captured.append((kwargs, question_import_writer.import_excel))

    monkeypatch.setattr(pipeline_orchestrator, "run_excel_pipeline_background", run)
    monkeypatch.setattr(question_import_writer, "import_excel", import_excel)
    task = harness.task(
        worker.TASK_TYPE_EXCEL_PIPELINE,
        pipeline_id="pipeline-1",
        staging_object_id="staging-1",
        source_file="source.xlsx",
        created_by=8,
    )
    await worker._process_task(task)

    assert captured[0][0]["file_content"] == b"excel-bytes"
    assert captured[0][0]["import_excel_fn"] is import_excel
    assert captured[0][0]["pipeline_id"] == "pipeline-1"
    assert harness.events[-1] == ("cleanup", str(source))


@pytest.mark.asyncio
async def test_excel_branch_honors_worker_namespace_open_override(harness, monkeypatch):
    from app.features import pipeline_orchestrator, question_import_writer

    captured = []
    opened = []

    class FakeHandle:
        def __enter__(self):
            return SimpleNamespace(read=lambda: b"namespaced-bytes")

        def __exit__(self, *exc_info):
            return False

    def fake_open(path, mode):
        opened.append((path, mode))
        return FakeHandle()

    async def run(**kwargs):
        captured.append(kwargs)

    # Path intentionally does not exist: only the namespaced open can read it.
    harness.paths["staging-1"] = "/missing/source.xlsx"
    monkeypatch.setattr(pipeline_orchestrator, "run_excel_pipeline_background", run)
    monkeypatch.setattr(question_import_writer, "import_excel", object())
    monkeypatch.setattr(worker, "open", fake_open, raising=False)
    await worker._process_task(
        harness.task(
            worker.TASK_TYPE_EXCEL_PIPELINE,
            pipeline_id="pipeline-1",
            staging_object_id="staging-1",
            source_file="source.xlsx",
        )
    )

    assert opened == [("/missing/source.xlsx", "rb")]
    assert captured[0]["file_content"] == b"namespaced-bytes"
    assert harness.events[-1] == ("cleanup", "/missing/source.xlsx")


@pytest.mark.asyncio
async def test_resume_and_admin_checkpoint_order(harness, monkeypatch):
    from app.core import database
    from app.features import pipeline_coordinator_entry, pipeline_orchestrator
    from app.services import import_pipeline_service

    calls = []
    db = object()

    @asynccontextmanager
    async def session():
        calls.append("session")
        yield db

    async def resume(**kwargs):
        calls.append(("resume", kwargs))

    async def checkpoint(pipeline_id):
        calls.append(("checkpoint", pipeline_id))
        return {"stage": "ocr"}

    async def run_pipeline(**kwargs):
        calls.append(("run", kwargs))
        return {"status": "done"}

    async def store(pipeline_id, result):
        calls.append(("store", pipeline_id, result))

    monkeypatch.setattr(database, "async_session", session)
    monkeypatch.setattr(import_pipeline_service, "run_resume_background", resume)
    monkeypatch.setattr(pipeline_orchestrator, "_get_stage_checkpoint", checkpoint)
    monkeypatch.setattr(pipeline_orchestrator, "_set_pipeline_store", store)
    monkeypatch.setattr(pipeline_coordinator_entry, "run_pipeline", run_pipeline)

    await worker._process_task(
        harness.task(
            worker.TASK_TYPE_RESUME_PIPELINE,
            pipeline_id="resume-1",
            staging_object_id="s1",
            options={"x": 1},
        )
    )
    await worker._process_task(
        harness.task(
            worker.TASK_TYPE_ADMIN_RESUME,
            pipeline_id="admin-1",
            staging_object_id="s2",
            source_type="pdf",
            source_file="a.pdf",
            subject="OS",
            subject_id=4,
            options={"y": 2},
        )
    )

    assert calls[0][0] == "resume"
    assert calls[0][1]["file_path"] == "/work/s1"
    assert calls[1] == ("checkpoint", "admin-1")
    assert calls[2] == "session"
    assert calls[3][0] == "run"
    assert calls[3][1]["db"] is db
    assert calls[3][1]["resume_from_checkpoint"] == {"stage": "ocr"}
    assert calls[4] == ("store", "admin-1", {"status": "done"})
    assert (
        sum(
            event[0] == "cleanup"
            for event in harness.events
            if isinstance(event, tuple)
        )
        == 2
    )


@pytest.mark.asyncio
async def test_admin_resume_reads_payload_before_checkpoint_and_session(
    harness, monkeypatch
):
    from app.core import database
    from app.features import pipeline_coordinator_entry, pipeline_orchestrator

    class LoggingPayload(dict):
        def get(self, key, default=None):
            harness.events.append(("payload-get", key))
            return super().get(key, default)

    captured = []

    @asynccontextmanager
    async def session():
        harness.events.append("session")
        yield object()

    async def checkpoint(pipeline_id):
        harness.events.append(("checkpoint", pipeline_id))
        return None

    async def run(**kwargs):
        captured.append(kwargs)
        return {"status": "done"}

    async def store(pipeline_id, result):
        harness.events.append(("store", pipeline_id))

    monkeypatch.setattr(database, "async_session", session)
    monkeypatch.setattr(pipeline_orchestrator, "_get_stage_checkpoint", checkpoint)
    monkeypatch.setattr(pipeline_orchestrator, "_set_pipeline_store", store)
    monkeypatch.setattr(pipeline_coordinator_entry, "run_pipeline", run)

    payload = LoggingPayload(
        pipeline_id="admin-1",
        staging_object_id="s1",
        source_type="docx",
        source_file="b.docx",
        subject="OS",
        subject_id=4,
        options={"y": 2},
    )
    await worker._process_task(
        SimpleNamespace(
            task_type=worker.TASK_TYPE_ADMIN_RESUME, task_id="t1", payload=payload
        )
    )

    kinds = [
        event[0] if isinstance(event, tuple) else event for event in harness.events
    ]
    last_get = max(index for index, kind in enumerate(kinds) if kind == "payload-get")
    assert kinds.index("checkpoint") > last_get
    assert kinds.index("session") > last_get
    assert captured[0]["source_type"] == "docx"
    assert captured[0]["source_file"] == "b.docx"
    assert captured[0]["subject"] == "OS"
    assert captured[0]["subject_id"] == 4
    assert captured[0]["options"] == {"y": 2}
    assert captured[0]["resume_from_checkpoint"] is None
    assert harness.events[-1] == ("cleanup", "/work/s1")


@pytest.mark.asyncio
async def test_empty_staging_id_skips_resolution_and_cleanup(harness, monkeypatch):
    from app.services import import_pipeline_service

    captured = []

    async def run(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(import_pipeline_service, "_run_pipeline_with_db", run)
    await worker._process_task(
        harness.task(
            worker.TASK_TYPE_IMPORT_PIPELINE,
            pipeline_id="pipeline-1",
            staging_object_id="",
        )
    )

    assert captured[0]["file_path"] == ""
    assert [event for event in harness.events if event[0] != "info"] == []


@pytest.mark.asyncio
async def test_answer_and_error_branches_use_live_worker_ports(harness, monkeypatch):
    calls = []

    async def answer(task):
        calls.append(("answer", task))

    async def error(task):
        calls.append(("error", task))

    monkeypatch.setattr(worker, "_process_answer_projection_task", answer)
    monkeypatch.setattr(worker, "_process_error_diagnosis_task", error)
    answer_task = harness.task(worker.TASK_TYPE_ANSWER_PROJECTION, value=1)
    error_task = harness.task(worker.TASK_TYPE_ERROR_DIAGNOSIS, value=2)
    await worker._process_task(answer_task)
    await worker._process_task(error_task)

    assert calls == [("answer", answer_task), ("error", error_task)]


@pytest.mark.asyncio
async def test_formula_branch_queries_before_processing(harness, monkeypatch):
    from app.core import database
    from app.services import formula_graph_batch_runner

    cards = [object(), object()]
    calls = []

    class Result:
        def scalars(self):
            return SimpleNamespace(all=lambda: cards)

    class Db:
        async def execute(self, statement):
            calls.append(("query", statement))
            return Result()

    @asynccontextmanager
    async def session():
        calls.append("session-open")
        yield Db()
        calls.append("session-close")

    async def process(job_id, values, admin_id):
        calls.append(("process", job_id, values, admin_id))

    monkeypatch.setattr(database, "async_session", session)
    monkeypatch.setattr(formula_graph_batch_runner, "process_batch", process)
    await worker._process_task(
        harness.task(
            worker.TASK_TYPE_FORMULA_BATCH,
            job_id="job-1",
            card_ids=[1, 2],
            admin_id=9,
        )
    )
    assert [item[0] if isinstance(item, tuple) else item for item in calls] == [
        "session-open",
        "query",
        "session-close",
        "process",
    ]
    assert calls[-1][2] == cards


@pytest.mark.asyncio
async def test_batch_image_preserves_original_sequence_and_cleanup(
    harness, monkeypatch
):
    from app.features import batch_image_import_service as batch

    captured = []

    class Source:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    async def run(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(batch, "BatchImageSource", Source)
    monkeypatch.setattr(batch, "run_batch_job", run)
    task = harness.task(
        worker.TASK_TYPE_BATCH_IMAGE,
        job_id="job-1",
        staging_object_ids=["", "one", "two"],
        subject="DS",
        subject_id=2,
        options={"x": 1},
        concurrency=3,
    )
    await worker._process_task(task)

    assert [source.kwargs["seq"] for source in captured[0]["sources"]] == [2, 3]
    assert [source.kwargs["temp_path"] for source in captured[0]["sources"]] == [
        "/work/one",
        "/work/two",
    ]
    assert harness.events[-2:] == [
        ("cleanup", "/work/one"),
        ("cleanup", "/work/two"),
    ]


@pytest.mark.asyncio
async def test_batch_image_requires_at_least_one_valid_source(harness, monkeypatch):
    from app.features import batch_image_import_service as batch

    async def run(**kwargs):
        raise AssertionError("run_batch_job must not run without sources")

    monkeypatch.setattr(batch, "BatchImageSource", lambda **kwargs: kwargs)
    monkeypatch.setattr(batch, "run_batch_job", run)
    with pytest.raises(
        FileNotFoundError,
        match="No valid staging sources for batch image job job-1",
    ):
        await worker._process_task(
            harness.task(
                worker.TASK_TYPE_BATCH_IMAGE,
                job_id="job-1",
                staging_object_ids=["", ""],
            )
        )

    warnings = [event for event in harness.events if event[0] == "warning"]
    assert warnings == [
        (
            "warning",
            ("Empty staging_object_id for batch image seq=%d job=%s", 1, "job-1"),
        ),
        (
            "warning",
            ("Empty staging_object_id for batch image seq=%d job=%s", 2, "job-1"),
        ),
    ]


@pytest.mark.asyncio
async def test_unknown_branch_and_cleanup_port_are_observable(harness, monkeypatch):
    with pytest.raises(ValueError, match="unknown_task_type: unknown"):
        await worker._process_task(harness.task("unknown", staging_object_id="one"))
    assert harness.events[-1] == (
        "info",
        (
            "Worker processing task: type=%s task_id=%s pipeline_id=%s",
            "unknown",
            "task-1",
            "task-1",
        ),
    )

    first = []
    second = []
    from app.features import batch_image_import_service as batch

    class Source:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    async def run(**kwargs):
        return None

    monkeypatch.setattr(batch, "BatchImageSource", Source)
    monkeypatch.setattr(batch, "run_batch_job", run)

    async def changing(path):
        first.append(path)

        async def later(later_path):
            second.append(later_path)

        monkeypatch.setattr(worker, "async_cleanup_work_copy", later)

    monkeypatch.setattr(worker, "async_cleanup_work_copy", changing)
    await worker._process_task(
        harness.task(
            worker.TASK_TYPE_BATCH_IMAGE,
            job_id="job",
            staging_object_ids=["one", "two"],
        )
    )
    assert first == ["/work/one"]
    assert second == ["/work/two"]
