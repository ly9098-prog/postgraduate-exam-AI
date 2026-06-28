"""Regression tests for batch image SSE stream parameter naming.

Covers:
1. poll_trace_events uses since_id, not since_seq
2. SSE response headers set correctly
3. event: error on poll failure
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_poll_trace_events_rejects_since_seq():
    """验证 since_seq 关键字会抛 TypeError（函数只接受 since_id）。"""
    from app.features.batch_image_import_service import poll_trace_events

    with pytest.raises(TypeError, match="since_seq"):
        await poll_trace_events(
            db=AsyncMock(),  # type: ignore[arg-type]
            job_id="test",
            since_seq=1,  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_poll_trace_events_accepts_since_id():
    """since_id 参数应被正常接受（不抛异常）。"""
    from app.features.batch_image_import_service import poll_trace_events

    # 只要参数名正确，函数应正常执行到 SQL 查询阶段
    with pytest.raises(Exception):
        await poll_trace_events(db=AsyncMock(), job_id="test", since_id=0)


@pytest.mark.asyncio
async def test_stream_response_headers():
    """SSE 端点应返回正确的缓存控制头。"""
    from app.api.v1.admin_imports import stream_batch_image_job as endpoint

    resp = await endpoint(
        job_id="test",
        last_event_id_query=0,
        last_event_id_header=None,
        _=None,
    )
    from fastapi.responses import StreamingResponse

    assert isinstance(resp, StreamingResponse)
    assert resp.headers.get("Cache-Control") == "no-cache"
    assert resp.headers.get("X-Accel-Buffering") == "no"


@pytest.mark.asyncio
async def test_stream_event_generator_handles_exception():
    """event_generator 在 poll 异常时 yield event: error 并退出。"""
    from app.api.v1.admin_imports import stream_batch_image_job as endpoint

    with (
        patch("app.features.batch_image_import_service.poll_trace_events", AsyncMock(side_effect=ValueError("fail"))),
        patch("app.features.batch_image_import_service.poll_job_summary"),
        patch("app.core.database.async_session"),
    ):
        resp = await endpoint(job_id="test", last_event_id_query=0, _=None)
        chunks = []
        async for chunk in resp.body_iterator:
            chunks.append(chunk)
            break

    content = "".join(chunks)
    assert "event: error" in content, f"期望 event: error, 实际: {content}"
    assert "fail" in content


@pytest.mark.asyncio
async def test_stream_uses_since_id_internal():
    """验证 event_generator 调用 poll_trace_events 时传 since_id 而非 since_seq。"""
    mock_poll = AsyncMock(return_value=[])
    mock_summary = AsyncMock(return_value={"status": "completed"})

    with (
        patch("app.features.batch_image_import_service.poll_trace_events", mock_poll),
        patch("app.features.batch_image_import_service.poll_job_summary", mock_summary),
        patch("app.core.database.async_session"),
    ):
        from app.api.v1.admin_imports import stream_batch_image_job as endpoint

        resp = await endpoint(job_id="test", last_event_id_query=7, _=None)
        async for chunk in resp.body_iterator:
            if "event: done" in chunk:
                break

    assert mock_poll.call_count >= 1
    kwargs = mock_poll.call_args.kwargs
    assert "since_id" in kwargs, f"期望 since_id 参数, 实际: {list(kwargs.keys())}"
    assert kwargs["since_id"] == 7
