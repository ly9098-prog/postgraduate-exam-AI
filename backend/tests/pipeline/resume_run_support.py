"""Synthetic ports for characterization of the public resume entrypoint."""

from types import SimpleNamespace

from app.features import global_hash_index, pipeline_checkpoint
from app.features import pipeline_orchestrator as module
from app.services import watermark_service
from tests.pipeline.chunked_run_support import fail_at, install_sessions, observe

__all__ = ["execute", "fail_at", "make_harness"]


def install_database(h):
    class Database:
        async def execute(self, query):
            name = "query_pipeline" if not h.queries else "query_chunks"
            h.queries.append(query)
            observe(h, name, query)
            if name == "query_pipeline":
                return SimpleNamespace(scalar_one_or_none=lambda: h.row)
            return SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: h.chunks)
            )

    h.db = Database()


def install_checkpoints(monkeypatch, h):
    async def checkpoint(pipeline_id):
        observe(h, "checkpoint", pipeline_id)
        return h.checkpoint

    async def pending(db, pipeline_id):
        observe(h, "pending", (db, pipeline_id))
        return h.pending

    async def status(db, pipeline_id, **kwargs):
        observe(h, "status:" + kwargs["status"], (db, pipeline_id, kwargs))

    async def invalidate(pipeline_id):
        observe(h, "invalidate", pipeline_id)

    async def progress(db, pipeline_id, **kwargs):
        observe(h, "progress", (db, pipeline_id, kwargs))
        return h.progress

    for name, port in {
        "get_stage_checkpoint": checkpoint,
        "get_pending_chunks": pending,
        "update_pipeline_status": status,
        "invalidate_progress_cache": invalidate,
        "get_pipeline_progress": progress,
    }.items():
        monkeypatch.setattr(pipeline_checkpoint, name, port, raising=False)


def install_watermarks(monkeypatch, h):
    def deserialize(snapshot):
        observe(h, "deserialize", snapshot)
        return h.patterns

    async def live(db):
        observe(h, "live", db)
        return h.live_patterns

    def defaults():
        observe(h, "defaults")
        return h.defaults

    monkeypatch.setattr(module, "_deserialize_watermark_patterns", deserialize)
    monkeypatch.setattr(watermark_service, "load_rules", live)
    monkeypatch.setattr(watermark_service, "get_default_patterns", defaults)


def install_hash_index(monkeypatch, h):
    class IndexMap(dict):
        def __init__(self, name):
            super().__init__(seed=1)
            self.name = name

        def clear(self):
            observe(h, self.name)
            super().clear()

    class Index:
        def __init__(self):
            observe(h, "construct_index")
            h.index = self
            self._question_index = IndexMap("clear_questions")
            self._import_index = IndexMap("clear_imports")

        async def load(self, db, **kwargs):
            observe(h, "load", (db, kwargs))

    async def seen(db, pipeline_id):
        observe(h, "seen", (db, pipeline_id))
        return h.seen

    monkeypatch.setattr(global_hash_index, "GlobalHashIndex", Index)
    monkeypatch.setattr(module, "_load_seen_hashes_for_resume", seen)


def install_pipeline(monkeypatch, h):
    async def chunk(**kwargs):
        observe(h, f"chunk:{len(h.calls)}", kwargs)
        h.calls.append(kwargs)
        kwargs["seen_hashes"].add(f"new:{len(h.calls)}")
        return h.outcomes[len(h.calls) - 1]

    def construct(**kwargs):
        observe(h, "construct_pipeline", kwargs)
        return h.pipeline

    def strategy(mode):
        observe(h, "strategy", mode)
        return h.strategy

    h.pipeline = SimpleNamespace(_execute_chunk=chunk)
    monkeypatch.setattr(module, "ImportPipeline", construct)
    monkeypatch.setattr(module, "get_strategy", strategy)
    monkeypatch.setattr(
        module, "_resolve_chunk_overlap", lambda: observe(h, "overlap") or 3
    )
    monkeypatch.setattr(module, "utcnow", lambda: observe(h, "utc") or h.stamp)
    monkeypatch.setattr(
        module,
        "serialize_utc_datetime",
        lambda value: observe(h, "serialize", value) or "started",
    )
    monkeypatch.setattr(
        module,
        "logger",
        SimpleNamespace(
            **{
                level: lambda *args, level=level: observe(h, level, args)
                for level in ("warning", "debug", "exception")
            }
        ),
    )


def make_chunks():
    return [
        SimpleNamespace(
            chunk_index=i,
            page_start=i * 10 + 1,
            page_end=(i + 1) * 10,
            status=status,
            batch_id=batch,
        )
        for i, status, batch in [
            (0, "completed", "old"),
            (4, "pending", None),
            (8, "failed", "failed"),
        ]
    ]


def make_harness(monkeypatch):
    chunks = make_chunks()
    h = SimpleNamespace(
        events=[],
        records={},
        hooks={},
        sessions=[],
        active=[],
        suppress={},
        queries=[],
        row=SimpleNamespace(
            total_pages=95,
            watermark_snapshot=[{"pattern": "frozen"}],
            source_type="pdf",
            source_file="original.pdf",
        ),
        chunks=chunks,
        pending=[chunks[2], chunks[1]],
        checkpoint={"subject_id": 7, "subject": "math"},
        patterns=[object()],
        live_patterns=[object()],
        defaults=[object()],
        index=None,
        seen={"old-hash"},
        calls=[],
        stamp=object(),
        strategy=object(),
        outcomes=[{"status": "completed"}, {"status": "completed"}],
        progress={"failed_chunks": 0},
    )
    install_database(h)
    install_sessions(monkeypatch, h)
    install_checkpoints(monkeypatch, h)
    install_watermarks(monkeypatch, h)
    install_hash_index(monkeypatch, h)
    install_pipeline(monkeypatch, h)
    h.arguments = {
        "pipeline_id": "resume-contract",
        "file_path": "/synthetic/resume.pdf",
        "options": {"import_mode": "auto", "nested": []},
        "db": h.db,
    }
    return h


async def execute(h, **overrides):
    return await module.resume_pipeline_background(**{**h.arguments, **overrides})
