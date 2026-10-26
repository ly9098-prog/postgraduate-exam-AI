"""Configuration and input references are prepared before checkpoint/restoration."""

import asyncio

import pytest

from app.features import pipeline_orchestrator as orchestrator
from app.services import model_config_resolver
from tests.pipeline.single_pass_support import execute, make_harness


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resolved", [None, {}, {"api_key": ""}, {"api_key": "synthetic"}]
)
async def test_vision_config_resolved_before_initial_checkpoint_and_preserves_identity(
    monkeypatch,
    resolved,
):
    h = make_harness(monkeypatch)
    events, db = [], object()

    async def resolve(actual, **kwargs):
        assert actual is db and kwargs == {"feature": "vision"}
        events.append("resolve")
        return resolved

    checkpoint = orchestrator._write_stage_checkpoint

    async def write(*args, **kwargs):
        assert events
        events.append("checkpoint")
        return await checkpoint(*args, **kwargs)

    monkeypatch.setattr(model_config_resolver, "resolve_active_model", resolve)
    monkeypatch.setattr(orchestrator, "_write_stage_checkpoint", write)
    await execute(h, db=db)
    assert events[0] == "resolve" and events[1] == "checkpoint"
    assert h.inputs["extract"]["vision_config"] is (
        resolved if resolved and resolved.get("api_key") else None
    )
    assert h.inputs["extract"]["db"] is db


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error", [RuntimeError("vision"), asyncio.CancelledError("vision")]
)
async def test_vision_failure_warns_but_cancellation_prevents_checkpoint(
    monkeypatch, error
):
    h = make_harness(monkeypatch)

    async def resolve(*args, **kwargs):
        raise error

    monkeypatch.setattr(model_config_resolver, "resolve_active_model", resolve)
    if isinstance(error, asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError) as caught:
            await execute(h, db=object())
        assert caught.value is error
        assert h.checkpoints == [] and h.calls == []
    else:
        result = await execute(h, db=object())
        assert result["status"] == "completed"
        assert h.inputs["extract"]["vision_config"] is None


@pytest.mark.asyncio
async def test_unrestricted_options_and_shared_payload_keep_original_references(
    monkeypatch,
):
    h = make_harness(monkeypatch)
    opts, strategy, patterns = {"nested": {}}, {}, []
    images, refs, blocks, seen, hash_index = {}, {}, [], set(), object()
    shared = {
        "import_mode": "book",
        "strategy": strategy,
        "watermark_patterns": patterns,
        "hash_index": hash_index,
    }
    await execute(
        h,
        opts=opts,
        shared=shared,
        page_images=images,
        page_image_refs=refs,
        pre_extracted_blocks=blocks,
        chunk_seen_hashes=seen,
        chunk_logical_end=0,
    )
    actual = h.inputs["extract"]
    for key, value in [
        ("options", opts),
        ("strategy", strategy),
        ("watermark_patterns", patterns),
        ("page_images", images),
        ("page_image_refs", refs),
        ("pre_extracted_blocks", blocks),
        ("_chunk_seen_hashes", seen),
        ("hash_index", hash_index),
    ]:
        assert actual[key] is value
    assert actual["_chunk_logical_end"] == 0
    assert h.checkpoints == []


@pytest.mark.asyncio
@pytest.mark.parametrize("page_start,page_end", [(0, None), (None, 0), (0, 0)])
async def test_zero_page_bounds_still_copy_options_before_checkpoint(
    monkeypatch, page_start, page_end
):
    h = make_harness(monkeypatch)
    opts = {"nested": object()}
    await execute(h, opts=opts, page_start=page_start, page_end=page_end)
    actual = h.inputs["extract"]["options"]
    assert actual is not opts
    assert actual["nested"] is opts["nested"]
    assert actual["page_start"] == page_start and actual["page_end"] == page_end
    assert h.checkpoints[0]["options"]["page_start"] == page_start


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error", [RuntimeError("restore"), asyncio.CancelledError("restore")]
)
async def test_artifact_restore_failure_occurs_after_initial_checkpoint(
    monkeypatch, error
):
    h = make_harness(monkeypatch)

    def restore(*args):
        raise error

    monkeypatch.setattr(orchestrator, "_restore_from_artifacts", restore)
    with pytest.raises(type(error)) as caught:
        await execute(h, resume_from_checkpoint={})
    assert caught.value is error and h.calls == []
    assert len(h.checkpoints) == 1
    assert h.trace == [("checkpoint", "")]
