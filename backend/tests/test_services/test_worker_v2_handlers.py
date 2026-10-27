"""Characterize all v2 handler branches before extracting their dispatch."""

import pytest
from sqlalchemy.dialects import sqlite

from app.features import pipeline_checkpoint as checkpoint
from app.services.worker_task_types import DISPATCHER_TASK_TYPES
from tests.worker_v2_support import WorkerHarness


@pytest.fixture
def harness(monkeypatch):
    token = checkpoint._fencing_ctx.set(None)
    try:
        yield WorkerHarness(monkeypatch)
    finally:
        checkpoint._fencing_ctx.reset(token)


def payload_for(full):
    payload = {
        "staging_object_id": "stage1",
        "staging_object_ids": [None, "stage1", "", "stage3"],
    }
    if full:
        payload.update(
            pipeline_id="pipeline-test",
            job_id="job-test",
            source_type="docx",
            source_file="synthetic.docx",
            subject="ds",
            subject_id=8,
            options={"split": False},
            created_by=9,
            source_sha256="synthetic-hash",
            concurrency=3,
            card_ids=[1, 3],
            admin_id=9,
        )
    return payload


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", DISPATCHER_TASK_TYPES)
@pytest.mark.parametrize("full", [False, True])
async def test_handler_parameters_and_owned_resource_order(harness, kind, full):
    payload = payload_for(full)
    assert await harness.run(kind, payload) is None
    args, kwargs = harness.call(f"handler.{kind}")
    assert_wire_arguments(harness, kind, payload, args, kwargs)
    record_id = (
        payload.get("job_id", "")
        if kind == "batch_image"
        else payload.get("pipeline_id", "task-test")
    )
    fenced = kind in {
        "import_pipeline",
        "image_pipeline",
        "excel_pipeline",
        "resume_pipeline",
        "admin_resume",
        "batch_image",
    } and bool(record_id)
    assert harness.events[0] == "version"
    assert ("initialize" in harness.events) == fenced
    assert ("set_context" in harness.events) == fenced
    assert ("clear_context" in harness.events) == fenced
    assert ("post" in harness.events) == fenced
    assert checkpoint._fencing_ctx.get() is None
    if fenced:
        assert harness.contexts == [
            {"task_id": "task-test", "owner_token": "owner-test", "generation": 7}
        ]
        post = harness.call("post")[1]
        assert (
            post["record_id"] == record_id and post["execution_status"] == "completed"
        )
        assert post["expected_owner_token"] == "owner-test"
        assert (
            post["expected_generation"] == 7 and post["expected_task_id"] == "task-test"
        )
        assert harness.events.index("clear_context") < harness.events.index("post")
        assert harness.events.index("post") < harness.events.index("commit")
    else:
        assert harness.contexts == [None]
    assert_staging_order(harness, kind, fenced)


def assert_staging_order(state, kind, fenced):
    paths = [args[0] for event, args, _ in state.calls if event == "cleanup"]
    if kind == "batch_image":
        assert paths == ["/synthetic/stage1.work", "/synthetic/stage3.work"]
    elif kind in {
        "import_pipeline",
        "image_pipeline",
        "excel_pipeline",
        "resume_pipeline",
        "admin_resume",
    }:
        assert paths == ["/synthetic/stage1.work"]
    else:
        assert paths == []
    if paths and fenced:
        assert state.events.index("cleanup") < state.events.index("clear_context")
        if kind in {"import_pipeline", "batch_image"}:
            assert state.events.index("verify") < state.events.index("resolve")
        else:
            assert state.events.index("resolve") < state.events.index("verify")
        if kind == "excel_pipeline":
            assert state.events.index("open") < state.events.index("verify")


def assert_wire_arguments(state, kind, payload, args, kwargs):
    if kind in {"answer_projection", "error_diagnosis"}:
        assert len(args) == 1 and args[0].task_type == kind and not kwargs
    elif kind == "formula_batch":
        assert (
            args == (payload.get("job_id", ""), state.cards, payload.get("admin_id", 0))
            and not kwargs
        )
        sql = str(
            state.call("execute")[0][0].compile(
                dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        assert "formula_cards.id IN" in sql
    elif kind == "batch_image":
        assert_batch_arguments(state, payload, kwargs)
    else:
        assert_pipeline_arguments(state, kind, payload, kwargs)


def assert_pipeline_arguments(state, kind, payload, kwargs):
    expected = dict(pipeline_id=payload.get("pipeline_id", "task-test"))
    if kind == "excel_pipeline":
        expected.update(
            file_content=b"synthetic-excel",
            source_file=payload.get("source_file", ""),
            import_excel_fn=state.writer.import_excel,
            created_by=payload.get("created_by"),
        )
    else:
        path_key = "image_path" if kind == "image_pipeline" else "file_path"
        expected.update(
            {
                path_key: "/synthetic/stage1.work",
                "subject": payload.get("subject"),
                "subject_id": payload.get("subject_id"),
                "options": payload.get("options", {}),
            }
        )
        if kind != "resume_pipeline":
            expected["source_file"] = payload.get("source_file", "")
        if kind in {"import_pipeline", "admin_resume"}:
            expected["source_type"] = payload.get("source_type", "pdf")
        if kind in {"import_pipeline", "image_pipeline"}:
            expected["created_by"] = payload.get("created_by")
        if kind == "import_pipeline":
            expected["source_sha256"] = payload.get("source_sha256")
        if kind == "admin_resume":
            expected.update(db=state.db, resume_from_checkpoint=state.checkpoint)
            assert state.call("store")[0] == (expected["pipeline_id"], state.result)
    assert kwargs == expected


def assert_batch_arguments(state, payload, kwargs):
    sources = kwargs["sources"]
    assert [(s.seq, s.source_file, s.temp_path) for s in sources] == [
        (2, "image_2.png", "/synthetic/stage1.work"),
        (4, "image_4.png", "/synthetic/stage3.work"),
    ]
    assert {key: value for key, value in kwargs.items() if key != "sources"} == dict(
        job_id=payload.get("job_id", ""),
        subject=payload.get("subject"),
        subject_id=payload.get("subject_id"),
        options=payload.get("options", {}),
        concurrency=payload.get("concurrency", 2),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind", ["import_pipeline", "excel_pipeline", "resume_pipeline", "admin_resume"]
)
async def test_missing_staging_remains_empty_input_for_optional_handlers(harness, kind):
    await harness.run(kind, {})
    kwargs = harness.call(f"handler.{kind}")[1]
    assert kwargs.get("file_path", kwargs.get("file_content")) in ("", b"")
    assert "resolve" not in harness.events and "cleanup" not in harness.events
    assert "open" not in harness.events


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["image_pipeline", "batch_image"])
async def test_missing_required_staging_fails_before_handler_and_post_fence(
    harness, kind
):
    with pytest.raises(FileNotFoundError):
        await harness.run(kind, {"job_id": "job-test"})
    assert f"handler.{kind}" not in harness.events and "post" not in harness.events
    assert checkpoint._fencing_ctx.get() is None


@pytest.mark.asyncio
async def test_unknown_type_is_dead_lettered_without_handler(harness):
    task = harness.task("unknown")
    from app.services import task_queue_worker as worker

    with pytest.raises(ValueError, match="unknown_task_type: unknown"):
        await worker._process_task_v2(task)
    assert task.max_retries == 0 and harness.events == ["version"]
    assert harness.logger.warning.call_count == 1
