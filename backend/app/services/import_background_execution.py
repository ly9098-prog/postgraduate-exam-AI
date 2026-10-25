"""Success-path execution for the generic import background wrapper."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.core.log_context import log_event
from app.services.import_source_digest import (
    SourceDigestRequest,
    default_open_file,
    resolve_source_digest,
)


@dataclass(slots=True)
class ImportBackgroundExecutionRequest:
    pipeline_id: str
    file_path: str
    source_type: str
    source_file: str
    subject: str | None
    subject_id: int | None
    options: dict
    created_by: str | None
    source_sha256: str | None
    async_session: Callable[[], Any]
    run_background: Callable[..., Awaitable[None]]
    logger: logging.Logger


async def execute_import_background(
    request: ImportBackgroundExecutionRequest,
) -> None:
    event_logger = logging.getLogger("postgraduate-ai")
    log_event(
        event_logger,
        "import.background.start",
        pipeline_id=request.pipeline_id,
        source_type=request.source_type,
        source_file=request.source_file,
    )
    source_sha256 = resolve_source_digest(
        SourceDigestRequest(
            pipeline_id=request.pipeline_id,
            file_path=request.file_path,
            provided_sha256=request.source_sha256,
            open_file=default_open_file,
            logger=request.logger,
        )
    )
    async with request.async_session() as db:
        await request.run_background(
            pipeline_id=request.pipeline_id,
            file_path=request.file_path,
            source_type=request.source_type,
            source_file=request.source_file,
            subject=request.subject,
            subject_id=request.subject_id,
            options=request.options,
            db=db,
            created_by=request.created_by,
            source_sha256=source_sha256,
        )
    log_event(
        event_logger,
        "import.background.finish",
        pipeline_id=request.pipeline_id,
        source_type=request.source_type,
        source_file=request.source_file,
    )
