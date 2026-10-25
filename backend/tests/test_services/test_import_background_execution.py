"""Contracts for the generic import background success execution block."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.import_background_execution import (
    ImportBackgroundExecutionRequest,
    execute_import_background,
)


def harness():
    db = SimpleNamespace()
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=db)
    session.__aexit__ = AsyncMock(return_value=False)
    run_background = AsyncMock()
    request = ImportBackgroundExecutionRequest(
        pipeline_id="pipe-1",
        file_path="/tmp/source.pdf",
        source_type="pdf",
        source_file="source.pdf",
        subject="DS",
        subject_id=3,
        options={"_trace_id": "trace-1"},
        created_by="admin",
        source_sha256="digest",
        async_session=lambda: session,
        run_background=run_background,
        logger=SimpleNamespace(),
    )
    return SimpleNamespace(
        request=request, session=session, db=db, run_background=run_background
    )


@pytest.mark.asyncio
async def test_execution_uses_one_session_and_passes_all_worker_fields():
    item = harness()
    await execute_import_background(item.request)
    item.run_background.assert_awaited_once_with(
        pipeline_id="pipe-1",
        file_path="/tmp/source.pdf",
        source_type="pdf",
        source_file="source.pdf",
        subject="DS",
        subject_id=3,
        options={"_trace_id": "trace-1"},
        db=item.db,
        created_by="admin",
        source_sha256="digest",
    )


@pytest.mark.asyncio
async def test_provided_digest_is_passed_through_without_file_read():
    item = harness()
    item.request.file_path = "/missing/source.pdf"
    await execute_import_background(item.request)
    item.run_background.assert_awaited_once()
    assert item.run_background.call_args.kwargs["source_sha256"] == "digest"
