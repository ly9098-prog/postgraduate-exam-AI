"""Durable owner admission against a real SQLite schema."""

from __future__ import annotations

import asyncio
import hashlib
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.import_pipeline import ImportPipeline, ImportPipelineChunk  # noqa: F401
from app.services import import_pipeline_admission
from app.services.import_upload_request import UploadRequest


def test_admit_record_hashes_file_and_persists_owner_before_enqueue(tmp_path, monkeypatch):
    source = tmp_path / "upload.txt"
    content = b"durable admission"
    source.write_bytes(content)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'admission.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _go():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        monkeypatch.setattr(import_pipeline_admission, "async_session", session_factory)
        request = UploadRequest(
            file_path=str(source),
            filename="upload.txt",
            content_type="text/plain",
            created_by="admin-1",
        )
        digest = await import_pipeline_admission.admit_pipeline_record(
            request,
            pipeline_id="pl_admission_001",
            source_type="txt",
            chunk_size=40,
        )
        assert digest == hashlib.sha256(content).hexdigest()

        async with session_factory() as db:
            row = (
                await db.execute(
                    select(ImportPipeline).where(
                        ImportPipeline.pipeline_id == "pl_admission_001"
                    )
                )
            ).scalar_one()
            assert row.status == "queued"
            assert row.created_by == "admin-1"
            assert row.source_sha256 == digest
            assert row.source_file == "upload.txt"
        await engine.dispose()

    asyncio.run(_go())
