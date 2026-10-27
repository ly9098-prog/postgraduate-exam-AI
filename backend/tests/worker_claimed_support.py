"""Real asyncio children and synthetic queue transitions for claimed workers."""

import asyncio
from unittest.mock import Mock

from app.core import log_context
from app.services import task_queue_worker as worker
from app.services.task_queue_contract import Task

CREATE_TASK = asyncio.create_task
WAIT_FOR = asyncio.wait_for


class ClaimedHarness:
    def __init__(self, monkeypatch):
        self.events = []
        self.calls = []
        self.children = []
        self.coroutines = []
        self.faults = {}
        self.mode = "success"
        self.owner_event = None
        self.started = asyncio.Event()
        self.complete_started = asyncio.Event()
        self.fail_started = asyncio.Event()
        self.code = 1
        self.fail_spawn = None
        self.spawn_error = RuntimeError("synthetic task factory failure")
        self.original_bind = log_context.bind_log_context
        self.original_reset = log_context.reset_log_context
        self.sem = Slot(self)
        self.logger = Mock()
        self.metrics = {"owner_fencing_rejected": 0, "hard_deadline_exceeded": 0}
        self.install(monkeypatch)

    def install(self, monkeypatch):
        for name, port in {
            "_process_task_v2": self.process,
            "_v2_heartbeat_loop_with_lease_window": self.heartbeat,
            "_complete_with_retry_v2": self.complete,
            "_fail_with_retry_v2": self.fail,
            "logger": self.logger,
            "queue_metrics": self.metrics,
            "_PROCESS_HARD_DEADLINE_SEC": 5,
        }.items():
            monkeypatch.setattr(worker, name, port)
        for name, port in {
            "bind_log_context": self.bind,
            "reset_log_context": self.reset,
            "generate_trace_id": self.trace_id,
            "generate_request_id": self.request_id,
        }.items():
            monkeypatch.setattr(log_context, name, port)
        monkeypatch.setattr(asyncio, "create_task", self.spawn)

    def record(self, name, *args, **kwargs):
        self.events.append(name)
        self.calls.append((name, args, kwargs))
        if name in self.faults:
            raise self.faults[name]

    def trace_id(self, prefix):
        self.record("trace_id", prefix)
        return f"made-{prefix}"

    def request_id(self, prefix):
        self.record("request_id", prefix)
        return f"made-{prefix}"

    def bind(self, **kwargs):
        self.record("bind", **kwargs)
        return self.original_bind(**kwargs)

    def reset(self, tokens):
        self.record("reset", tokens)
        self.original_reset(tokens)

    def spawn(self, coroutine, **kwargs):
        number = len(self.coroutines) + 1
        self.record(f"spawn.{number}")
        self.coroutines.append(coroutine)
        if number == self.fail_spawn:
            raise self.spawn_error
        task = CREATE_TASK(coroutine, **kwargs)
        self.children.append(task)
        return task

    async def heartbeat(self, task, lease_sec, owner_lost):
        self.owner_event = owner_lost
        self.record("heartbeat", task, lease_sec, owner_lost)
        if self.mode == "owner-lost":
            owner_lost.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.record("heartbeat.stop")

    async def process(self, task):
        self.record("process", task, context=log_context.get_log_context())
        self.started.set()
        if self.mode in {"owner-lost", "blocked", "deadline"}:
            try:
                await asyncio.Event().wait()
            finally:
                self.record("process.stop")
        if self.mode == "finish-and-lose":
            self.owner_event.set()
        if "process.result" in self.faults:
            if self.mode == "error-and-lose":
                self.owner_event.set()
            raise self.faults["process.result"]

    async def complete(self, task):
        self.record("complete", task, heartbeat_alive=not self.children[0].done())
        self.complete_started.set()
        if self.mode == "complete-blocked":
            await asyncio.Event().wait()
        return self.code

    async def fail(self, task, message):
        self.record("fail", task, message, heartbeat_alive=not self.children[0].done())
        self.fail_started.set()
        if self.mode == "fail-blocked":
            await asyncio.Event().wait()
        return 1

    def task(self, payload=None):
        return Task(
            task_id="claimed-task",
            task_type="answer_projection",
            payload={} if payload is None else payload,
            owner_token="claimed-owner",
            generation=8,
        )

    async def run(self, task=None):
        return await worker._process_claimed_task_v2(
            task if task is not None else self.task(), 60, self.sem
        )

    async def dispose(self):
        for task in self.children:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.children, return_exceptions=True)
        for coroutine in self.coroutines:
            if coroutine.cr_frame is not None:
                coroutine.close()

    def call(self, name):
        return next(
            (args, kwargs) for event, args, kwargs in self.calls if event == name
        )


class Slot:
    def __init__(self, state):
        self.state = state
        self.slot = asyncio.Semaphore(0)
        self.releases = 0

    def release(self):
        self.releases += 1
        self.state.record("release")
        self.slot.release()
