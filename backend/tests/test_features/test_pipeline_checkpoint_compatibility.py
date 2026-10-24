"""Real compatibility baseline for pipeline stage checkpoint lifecycle.

Exercises ``_write_stage_checkpoint`` / ``_get_stage_checkpoint`` /
``_clear_stage_checkpoint`` against the in-process store (no Redis needed).
Verifies the write→read→clear contract, lightweight field stripping, and
prune eviction.  This is in-process evidence only; Redis-backed checkpoint
persistence requires a live Redis instance.
"""

from __future__ import annotations

import pytest

from app.features.pipeline_orchestrator import (
    _MAX_STAGE_CKPT_SIZE,
    _clear_stage_checkpoint,
    _get_stage_checkpoint,
    _pipeline_stage_checkpoints,
    _prune_stage_checkpoints,
    _write_stage_checkpoint,
)


@pytest.mark.asyncio
async def test_write_then_read_roundtrip():
    """Checkpoint written → read returns same completed_stages and current_stage."""
    pid = "test-ckpt-roundtrip"
    try:
        await _write_stage_checkpoint(
            pid,
            completed_stages=["extract", "normalize_text"],
            current_stage="ocr_correction",
            stage_statuses={
                "extract": {"status": "completed", "duration_ms": 100, "error": None},
                "normalize_text": {"status": "completed", "duration_ms": 50, "error": None},
            },
            source_type="pdf",
            source_file="test.pdf",
            subject="ds",
            options={"enable_ai_repair": True},
        )
        ckpt = await _get_stage_checkpoint(pid)
        assert ckpt is not None
        assert ckpt["completed_stages"] == ["extract", "normalize_text"]
        assert ckpt["current_stage"] == "ocr_correction"
        assert ckpt["source_type"] == "pdf"
        assert ckpt["options"]["enable_ai_repair"] is True
    finally:
        await _clear_stage_checkpoint(pid)


@pytest.mark.asyncio
async def test_clear_removes_checkpoint():
    """Clear after write → read returns None."""
    pid = "test-ckpt-clear"
    await _write_stage_checkpoint(
        pid,
        completed_stages=["extract"],
        current_stage="extract",
        stage_statuses={},
    )
    assert await _get_stage_checkpoint(pid) is not None
    await _clear_stage_checkpoint(pid)
    assert await _get_stage_checkpoint(pid) is None


@pytest.mark.asyncio
async def test_missing_checkpoint_returns_none():
    """Non-existent pipeline_id → None, no exception."""
    result = await _get_stage_checkpoint("nonexistent-pipeline-id")
    assert result is None


@pytest.mark.asyncio
async def test_checkpoint_strips_large_stage_fields():
    """stage_statuses keeps only status/duration_ms/error — no large data leaks."""
    pid = "test-ckpt-strip"
    try:
        await _write_stage_checkpoint(
            pid,
            completed_stages=["extract"],
            current_stage="extract",
            stage_statuses={
                "extract": {
                    "status": "completed",
                    "duration_ms": 200,
                    "error": None,
                    "huge_field": "x" * 10000,
                    "big_list": list(range(1000)),
                },
            },
        )
        ckpt = await _get_stage_checkpoint(pid)
        entry = ckpt["stage_statuses"]["extract"]
        assert set(entry.keys()) == {"status", "duration_ms", "error"}
        assert "huge_field" not in entry
        assert "big_list" not in entry
    finally:
        await _clear_stage_checkpoint(pid)


@pytest.mark.asyncio
async def test_failure_checkpoint_records_error():
    """Failed stage → checkpoint has failed_stage and error."""
    pid = "test-ckpt-failure"
    try:
        await _write_stage_checkpoint(
            pid,
            completed_stages=["extract"],
            current_stage="normalize_text",
            stage_statuses={"extract": {"status": "completed", "duration_ms": 100}},
            failed_stage="normalize_text",
            error="UnicodeDecodeError: invalid utf-8",
        )
        ckpt = await _get_stage_checkpoint(pid)
        assert ckpt["failed_stage"] == "normalize_text"
        assert "UnicodeDecodeError" in ckpt["error"]
    finally:
        await _clear_stage_checkpoint(pid)


def test_prune_evicts_oldest_when_over_limit():
    """In-process store evicts oldest entries beyond _MAX_STAGE_CKPT_SIZE."""
    # Fill beyond limit
    for i in range(_MAX_STAGE_CKPT_SIZE + 10):
        _pipeline_stage_checkpoints[f"prune-test-{i}"] = {"completed_stages": []}
    _prune_stage_checkpoints()
    assert len(_pipeline_stage_checkpoints) <= _MAX_STAGE_CKPT_SIZE
    # Oldest entries should be evicted
    assert "prune-test-0" not in _pipeline_stage_checkpoints
    # Newest should survive
    assert f"prune-test-{_MAX_STAGE_CKPT_SIZE + 9}" in _pipeline_stage_checkpoints
    # Cleanup
    for key in list(_pipeline_stage_checkpoints.keys()):
        if key.startswith("prune-test-"):
            _pipeline_stage_checkpoints.pop(key, None)
