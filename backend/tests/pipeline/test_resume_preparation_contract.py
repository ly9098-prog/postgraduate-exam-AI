"""Resume input recovery and frozen watermark precedence, before extraction."""

import asyncio

import pytest
from sqlalchemy.sql import operators

from app.features import pipeline_orchestrator as module
from app.models.import_pipeline import ImportPipeline, ImportPipelineChunk
from tests.pipeline.resume_run_support import execute, fail_at, make_harness


@pytest.mark.asyncio
async def test_session_order_and_input_copy(monkeypatch):
    h = make_harness(monkeypatch)
    assert await execute(h) is None
    assert (
        h.events
        == """
        derive query_pipeline checkpoint pending query_chunks overlap strategy deserialize
        construct_index enter:0 load exit:0 enter:1 seen exit:1 enter:2 status:running exit:2
        invalidate construct_pipeline utc serialize enter:3 chunk:0 exit:3 enter:4 chunk:1
        exit:4 clear_questions clear_imports enter:5 progress status:completed exit:5 invalidate
    """.split()
    )
    opts = h.records["construct_pipeline"][0]["options"]
    assert opts == h.arguments["options"] and opts is not h.arguments["options"]
    assert opts["nested"] is h.arguments["options"]["nested"]
    assert h.records["load"] == [(h.sessions[0], {"batch_ids": ["old"]})]
    assert h.records["seen"] == [(h.sessions[1], "resume-contract")]
    assert h.records["derive"] == [h.db]
    assert str(h.queries[1]).endswith("ORDER BY import_pipeline_chunks.chunk_index")
    assert h.pipeline.pipeline_id == "resume-contract" and not h.active


@pytest.mark.asyncio
async def test_complete_chunk_payload_retains_shared_references(monkeypatch):
    h = make_harness(monkeypatch)
    patterns_ref, patterns_before = h.patterns, list(h.patterns)
    await execute(h)
    opts = h.records["construct_pipeline"][0]["options"]
    expected = {
        "chunk_index": 8,
        "page_start": 81,
        "logical_end": 90,
        "total_pages": 95,
        "is_last_chunk": True,
        "chunk_overlap": 3,
        "file_content": None,
        "file_path": "/synthetic/resume.pdf",
        "source_type": "pdf",
        "source_file": "original.pdf",
        "subject": "math",
        "subject_id": 7,
        "opts": opts,
        "db": h.sessions[3],
        "shared": {
            "import_mode": module.ImportMode.AUTO,
            "strategy": h.strategy,
            "watermark_patterns": patterns_before,
            "hash_index": h.index,
        },
        "progress_callback": None,
        "started_at": "started",
        "seen_hashes": h.seen,
        "hash_index": h.index,
        "page_image_refs": None,
    }
    for number, call in enumerate(h.calls):
        expected.update(
            chunk_index=(8, 4)[number],
            page_start=(81, 41)[number],
            logical_end=(90, 50)[number],
            is_last_chunk=number == 0,
            db=h.sessions[3 + number],
        )
        assert call == expected
        assert call["shared"] is h.calls[0]["shared"]
        assert call["shared"]["watermark_patterns"] is patterns_ref
        assert call["opts"] is opts and call["seen_hashes"] is h.seen
    assert h.patterns == patterns_before and h.seen == {"old-hash", "new:1", "new:2"}


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing", "no_pending", "no_chunks"])
async def test_early_returns_keep_caller_session_and_do_not_load_index(
    monkeypatch, case
):
    h = make_harness(monkeypatch)
    if case == "missing":
        h.row = None
    elif case == "no_pending":
        h.pending = []
    else:
        h.chunks = []
    await execute(h)
    assert not h.sessions and not h.calls
    if case == "no_pending":
        assert h.records["status:completed"] == [
            (
                h.db,
                "resume-contract",
                {
                    "status": "completed",
                    "finished": True,
                },
            )
        ]
        assert h.events[-1] == "invalidate" and "query_chunks" not in h.events
    else:
        assert h.events[-1] == "warning" and "invalidate" not in h.events


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "subject,subject_id,want",
    [
        (None, None, ("math", 7)),
        ("given", None, ("given", 7)),
        ("", 0, ("", 0)),
        (None, 2, (None, 2)),
    ],
)
async def test_subject_recovery_only_when_id_is_none(
    monkeypatch, subject, subject_id, want
):
    h = make_harness(monkeypatch)
    await execute(h, subject=subject, subject_id=subject_id)
    assert (h.calls[0]["subject"], h.calls[0]["subject_id"]) == want
    assert ("checkpoint" in h.events) == (subject_id is None)


@pytest.mark.asyncio
async def test_checkpoint_ordinary_failure_is_best_effort(monkeypatch):
    h = make_harness(monkeypatch)
    fail_at(h, "checkpoint", RuntimeError("checkpoint"))
    await execute(h)
    assert h.calls[0]["subject_id"] is None and h.calls[0]["subject"] is None
    assert "debug" in h.events


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "snapshot,patterns,live,warning,defaults",
    [
        ([1], ["frozen"], ["live"], False, False),
        ([1], [], ["live"], True, False),
        (None, [], ["live"], True, False),
        ([], [], [], True, True),
    ],
)
async def test_snapshot_live_default_precedence(
    monkeypatch, snapshot, patterns, live, warning, defaults
):
    h = make_harness(monkeypatch)
    h.row.watermark_snapshot, h.patterns, h.live_patterns = snapshot, patterns, live
    frozen, live_before, default_before = list(patterns), list(live), list(h.defaults)
    await execute(h)
    actual = h.calls[0]["shared"]["watermark_patterns"]
    assert actual is (h.defaults if defaults else patterns if patterns else live)
    assert actual == (
        default_before if defaults else frozen if patterns else live_before
    )
    assert ("warning" in h.events) == warning
    assert ("deserialize" in h.events) == bool(snapshot)
    assert ("live" in h.events) == (not patterns or not snapshot)
    assert ("defaults" in h.events) == defaults
    if "live" in h.events:
        assert h.records["live"] == [h.db]


@pytest.mark.asyncio
async def test_live_rule_error_uses_defaults(monkeypatch):
    h = make_harness(monkeypatch)
    h.row.watermark_snapshot = None
    fail_at(h, "live", RuntimeError("rules"))
    await execute(h)
    assert h.calls[0]["shared"]["watermark_patterns"] is h.defaults
    assert len(h.records["warning"]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,expected", [("invalid", "auto"), ("auto", "auto")])
async def test_import_mode_falls_back_only_on_value_error(monkeypatch, mode, expected):
    h = make_harness(monkeypatch)
    await execute(h, options={"import_mode": mode})
    assert h.records["strategy"] == [module.ImportMode(expected)]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [RuntimeError, TypeError, asyncio.CancelledError])
async def test_other_import_mode_errors_propagate_before_context_initialization(
    monkeypatch, kind
):
    h = make_harness(monkeypatch)
    error = kind("mode")

    def mode(_):
        raise error

    monkeypatch.setattr(module, "ImportMode", mode)
    with pytest.raises(kind) as caught:
        await execute(h)
    assert caught.value is error and not h.sessions
    assert "strategy" not in h.events and "construct_index" not in h.events


@pytest.mark.asyncio
@pytest.mark.parametrize("point", ["checkpoint", "deserialize", "live", "defaults"])
async def test_watermark_and_recovery_cancellation_propagate(monkeypatch, point):
    h = make_harness(monkeypatch)
    if point in {"live", "defaults"}:
        h.row.watermark_snapshot = None
        h.live_patterns = []
    error = asyncio.CancelledError(point)
    fail_at(h, point, error)
    with pytest.raises(asyncio.CancelledError) as caught:
        await execute(h)
    assert caught.value is error and not h.sessions


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "number,model", [(0, ImportPipeline), (1, ImportPipelineChunk)]
)
async def test_queries_select_only_the_requested_pipeline(monkeypatch, number, model):
    h = make_harness(monkeypatch)
    await execute(h)
    query = h.queries[number]
    assert [column["entity"] for column in query.column_descriptions] == [model]
    assert query.whereclause.operator is operators.eq
    assert query.whereclause.left.compare(model.pipeline_id.expression)
    assert query.whereclause.right.value == "resume-contract"
    assert query.compile().params == {"pipeline_id_1": "resume-contract"}
    ordering = list(query._order_by_clauses)
    if number:
        assert len(ordering) == 1 and ordering[0].compare(model.chunk_index.expression)
    else:
        assert ordering == []
