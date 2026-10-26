"""Deterministic sessions and ports for the real chunked orchestration method."""

from types import SimpleNamespace

from app.features import global_hash_index, pipeline_checkpoint
from app.features import pipeline_orchestrator as module


def observe(h, name, payload=None):
    h.events.append(name)
    h.records.setdefault(name, []).append(payload)
    if name in h.hooks:
        return h.hooks[name](payload)


def fail_at(h, name, error):
    def fail(_):
        raise error

    h.hooks[name] = fail


def install_sessions(monkeypatch, h):
    class Session:
        def __init__(self):
            self.number = len(h.sessions)
            h.sessions.append(self)

        async def __aenter__(self):
            assert not h.active
            observe(h, f"enter:{self.number}", self)
            h.active.append(self)
            return self

        async def __aexit__(self, kind, error, traceback):
            assert h.active.pop() is self
            observe(h, f"exit:{self.number}", (kind, error))
            return h.suppress.get(self.number, False)

    def derive(db):
        observe(h, "derive", db)
        return Session

    monkeypatch.setattr(module, "_derive_session_factory", derive)


def install_checkpoints(monkeypatch, h):
    async def parent(db, **kwargs):
        observe(h, "parent", (db, kwargs))

    async def chunks(db, pipeline_id, ranges):
        observe(h, "chunks", (db, pipeline_id, ranges))

    async def final(db, pipeline_id, **kwargs):
        observe(h, "final", (db, pipeline_id, kwargs))

    async def invalidate(pipeline_id):
        observe(h, "invalidate", pipeline_id)

    monkeypatch.setattr(pipeline_checkpoint, "ensure_pipeline_record", parent)
    monkeypatch.setattr(pipeline_checkpoint, "ensure_chunk_records", chunks)
    monkeypatch.setattr(pipeline_checkpoint, "update_pipeline_status", final)
    monkeypatch.setattr(pipeline_checkpoint, "invalidate_progress_cache", invalidate)


def install_index(monkeypatch, h):
    class IndexMap(dict):
        def __init__(self, label):
            super().__init__({"seed": 1})
            self.label = label

        def clear(self):
            observe(h, self.label)
            super().clear()

    class Index:
        def __init__(self):
            observe(h, "construct_index")
            h.index = self
            self._question_index = IndexMap("clear_questions")
            self._import_index = IndexMap("clear_imports")

        async def load(self, db):
            observe(h, "load", db)
            if h.load_wait:
                await h.load_wait()

        @property
        def stats(self):
            observe(h, "index_stats")
            return h.index_stats

    monkeypatch.setattr(global_hash_index, "GlobalHashIndex", Index)


def install_observations(monkeypatch, h):
    def size():
        observe(h, "size")
        return 2

    def overlap():
        observe(h, "overlap")
        return 1

    def watermark(patterns):
        observe(h, "watermark", patterns)
        return h.watermark

    def get_logger(name):
        observe(h, "get_logger", name)
        return h.run_logger

    def clock():
        observe(h, "clock")
        return next(h.clocks)

    monkeypatch.setattr(module, "_resolve_chunk_size", size)
    monkeypatch.setattr(module, "_resolve_chunk_overlap", overlap)
    monkeypatch.setattr(module, "_serialize_watermark_patterns", watermark)
    monkeypatch.setattr(module, "logging", SimpleNamespace(getLogger=get_logger))
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=clock))
    monkeypatch.setattr(
        module, "logger",
        SimpleNamespace(exception=lambda text: observe(h, "load_fallback", text)),
    )
    monkeypatch.setattr(module, "utcnow", lambda: observe(h, "utc") or h.stamp)
    monkeypatch.setattr(
        module, "serialize_utc_datetime",
        lambda stamp: observe(h, "serialize", stamp) or "finished",
    )


def install_execution(monkeypatch, h):
    async def chunk(**kwargs):
        index = kwargs["chunk_index"]
        observe(h, f"chunk:{index}", kwargs)
        h.chunk_calls.append(kwargs)
        if h.chunk_wait:
            await h.chunk_wait(index, kwargs)
        kwargs["seen_hashes"].add(f"seen:{index}")
        return h.outcomes[index]

    def log(logger, event, **kwargs):
        observe(h, event, (logger, kwargs))

    def merge(results):
        observe(h, "merge", results)
        return h.risk

    h.pipeline._execute_chunk = chunk
    monkeypatch.setattr(module, "log_event", log)
    monkeypatch.setattr(module, "_merge_risk_flag_counts", merge)


def make_harness(monkeypatch):
    h = SimpleNamespace(
        events=[], records={}, hooks={}, sessions=[], active=[], suppress={},
        index=None, index_stats={"queries": 9}, chunk_calls=[],
        clocks=iter([10.0, 10.125]), run_logger=object(), stamp=object(),
        risk={"synthetic": 2}, watermark=[{"pattern": "watermark"}],
        load_wait=None, chunk_wait=None,
        outcomes=[
            {"status": "completed", "batch_id": "first", "question_count": 3},
            {"status": "completed", "batch_id": "second", "question_count": 4},
        ],
        pipeline=SimpleNamespace(
            pipeline_id="chunked-contract", created_by="admin", source_sha256="sha"
        ),
    )
    h.arguments = {
        "file_content": b"pdf", "file_path": "/synthetic/input.pdf",
        "source_type": "pdf", "source_file": "input.pdf",
        "subject": "math", "subject_id": 7, "opts": {"mode": "synthetic"},
        "db": object(), "shared": {"watermark_patterns": ["pattern"], "nested": []},
        "progress_callback": object(), "chunk_ranges": [(1, 2), (3, 4)],
        "started_at": "started", "page_images": {1: b"image"},
        "page_image_refs": {1: "ref"},
    }
    install_sessions(monkeypatch, h)
    install_checkpoints(monkeypatch, h)
    install_index(monkeypatch, h)
    install_observations(monkeypatch, h)
    install_execution(monkeypatch, h)
    return h


async def execute(h, **overrides):
    arguments = {**h.arguments, **overrides}
    return await module.ImportPipeline._run_chunked(h.pipeline, **arguments)
