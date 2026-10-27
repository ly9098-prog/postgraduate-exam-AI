"""Synthetic v2 handler ports with real fencing ContextVar operations."""

import importlib
import io
import sys
from contextlib import asynccontextmanager
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

from app.features import pipeline_checkpoint as checkpoint
from app.services import task_queue_worker as worker
from app.services.task_queue_contract import Task

FENCED = (
    "import_pipeline",
    "image_pipeline",
    "excel_pipeline",
    "resume_pipeline",
    "admin_resume",
    "batch_image",
)


class OwnedRecord:
    pass


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


class WorkerHarness:
    def __init__(self, monkeypatch):
        self.monkeypatch = monkeypatch
        self.events = []
        self.calls = []
        self.contexts = []
        self.faults = {}
        self.paths = {}
        self.result = {"synthetic": True}
        self.checkpoint = {"stage": "split"}
        self.cards = [object(), object()]
        self.fence_ok = True
        self.logger = Mock()
        self.original_set = checkpoint.set_fencing_context
        self.original_clear = checkpoint.clear_fencing_context
        self.db = SimpleNamespace(
            execute=self.execute, commit=self.commit, rollback=self.rollback
        )
        ports = {
            "_check_worker_version_compatibility": self.version,
            "_init_fencing_for_task": self.initialize,
            "_verify_fencing_or_cancel": self.verify,
            "_resolve_staging_path": self.resolve,
            "async_cleanup_work_copy": self.cleanup,
            "_process_answer_projection_task": self.handler("answer_projection"),
            "_process_error_diagnosis_task": self.handler("error_diagnosis"),
            "logger": self.logger,
            "open": self.open_file,
        }
        for name, value in ports.items():
            monkeypatch.setattr(worker, name, value, raising=False)
        monkeypatch.setattr(checkpoint, "set_fencing_context", self.set_context)
        monkeypatch.setattr(checkpoint, "clear_fencing_context", self.clear_context)
        self.install_handlers()

    def record(self, name, *args, **kwargs):
        self.events.append(name)
        self.calls.append((name, args, kwargs))
        if name in self.faults:
            raise self.faults[name]

    def install(self, name, **values):
        module = ModuleType(name)
        module.__dict__.update(values)
        self.monkeypatch.setitem(sys.modules, name, module)
        parent, _, attribute = name.rpartition(".")
        self.monkeypatch.setattr(
            importlib.import_module(parent), attribute, module, raising=False
        )
        return module

    def install_handlers(self):
        self.install(
            "app.services.import_pipeline_service",
            _run_pipeline_with_db=self.handler("import_pipeline"),
            _run_image_pipeline_with_db=self.handler("image_pipeline"),
            run_resume_background=self.handler("resume_pipeline"),
        )
        self.pipeline = self.install(
            "app.features.pipeline_orchestrator",
            run_excel_pipeline_background=self.handler("excel_pipeline"),
            _get_stage_checkpoint=self.get_checkpoint,
            _set_pipeline_store=self.store,
        )
        self.writer = self.install(
            "app.features.question_import_writer", import_excel=object()
        )
        self.install(
            "app.features.pipeline_coordinator_entry",
            run_pipeline=self.handler("admin_resume"),
        )
        self.install(
            "app.services.formula_graph_batch_runner",
            process_batch=self.handler("formula_batch"),
        )
        self.batch = self.install(
            "app.features.batch_image_import_service",
            BatchImageSource=lambda **kwargs: SimpleNamespace(**kwargs),
            run_batch_job=self.handler("batch_image"),
        )
        from app.core import database
        from app.services import db_fencing

        self.monkeypatch.setattr(database, "async_session", self.session)
        self.monkeypatch.setattr(
            db_fencing, "FENCING_TABLES", {kind: (OwnedRecord, "id") for kind in FENCED}
        )
        self.monkeypatch.setattr(
            db_fencing, "conditional_update_with_fencing", self.post_fence
        )

    def handler(self, kind):
        async def run(*args, **kwargs):
            self.record(f"handler.{kind}", *args, **kwargs)
            self.contexts.append(checkpoint._fencing_ctx.get())
            return self.result

        return run

    async def version(self, task):
        self.record("version", task)

    async def initialize(self, *args):
        self.record("initialize", *args)

    async def verify(self, *args):
        self.record("verify", *args)

    async def resolve(self, identity, owner, generation):
        self.record("resolve", identity, owner, generation)
        return self.paths.get(identity, f"/synthetic/{identity}.work")

    async def cleanup(self, path):
        self.record("cleanup", path)

    def set_context(self, **kwargs):
        self.record("set_context", **kwargs)
        return self.original_set(**kwargs)

    def clear_context(self, token):
        self.record("clear_context", token)
        self.original_clear(token)

    def open_file(self, path, mode):
        self.record("open", path, mode)
        return io.BytesIO(b"synthetic-excel")

    @asynccontextmanager
    async def session(self):
        self.record("db.enter")
        try:
            yield self.db
        finally:
            self.record("db.exit")

    async def execute(self, query):
        self.record("execute", query)
        return Rows(self.cards)

    async def commit(self):
        self.record("commit")

    async def rollback(self):
        self.record("rollback")

    async def post_fence(self, **kwargs):
        self.record("post", **kwargs)
        return self.fence_ok

    async def get_checkpoint(self, identity):
        self.record("checkpoint", identity)
        return self.checkpoint

    async def store(self, *args):
        self.record("store", *args)

    def task(self, kind="import_pipeline", payload=None):
        return Task(
            task_id="task-test",
            task_type=kind,
            owner_token="owner-test",
            generation=7,
            payload={} if payload is None else payload,
        )

    async def run(self, kind="import_pipeline", payload=None):
        return await worker._process_task_v2(self.task(kind, payload))

    def call(self, name):
        return next(
            (args, kwargs) for event, args, kwargs in self.calls if event == name
        )
