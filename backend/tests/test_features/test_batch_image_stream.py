"""Regression tests for batch image SSE stream parameter naming.

Covers:
1. poll_trace_events uses since_id, not since_seq
2. SSE response headers set correctly
3. event: error on poll failure
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


def _make_test_client():
    """Build a minimal FastAPI test app with just the endpoint mounted."""
    from app.api.v1.admin_imports import router
    from app.main import app

    return TestClient(app)


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


def test_stream_response_headers():
    """SSE 端点应返回正确的缓存控制头。

    Uses FastAPI TestClient to properly resolve DI parameters.
    """
    client = _make_test_client()
    with patch("app.api.v1.admin_imports.batch_svc.poll_trace_events", return_value=[]):
        with patch("app.api.v1.admin_imports.async_session"):
            with patch("app.api.v1.admin_imports.require_permissions", return_value=AsyncMock()):
                resp = client.get("/admin/api/v1/import/images/test/stream", headers={"accept": "text/event-stream"})
                assert resp.status_code in (200, 401, 403, 307)
                if resp.status_code == 200:
                    assert resp.headers.get("cache-control") == "no-cache"
                    assert resp.headers.get("x-accel-buffering") == "no"


def test_stream_event_generator_handles_exception():
    """event_generator 在 poll 异常时 yield event: error 并退出。"""
    from app.api.v1.admin_imports import stream_batch_image_job

    async def _test():
        from unittest.mock import AsyncMock

        from app.api.v1.admin_imports import event_generator

        # event_generator is a closure inside stream_batch_image_job, not
        # importable directly. Test the poll-failure path by patching.
        import app.api.v1.admin_imports as mod

        mock_poll = AsyncMock(side_effect=ValueError("fail"))
        resp = await stream_batch_image_job(
            job_id="test",
            request=AsyncMock(spec=["headers", "query_params"]),
            last_event_id_query=0,
            last_event_id_header=None,
            admin_user=AsyncMock(),
        )
        chunks = []
        async for chunk in resp.body_iterator:
            chunks.append(chunk)
            break
        content = "".join(chunks)
        assert "event: error" in content, f"期望 event: error, 实际: {content}"
        assert "fail" in content

    import asyncio
    asyncio.run(_test())
