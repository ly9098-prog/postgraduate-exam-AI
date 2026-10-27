"""Administrative queue transitions with no real Redis connection."""

from types import SimpleNamespace
from unittest.mock import Mock

from app.services import task_queue_service as svc
from app.services import task_queue_v2_admin_contract as admin
from app.services import task_queue_v2_reaper_contract as reaper


class AdminHarness:
    def __init__(self, monkeypatch, operation):
        self.operation = operation
        self.trace = []
        self.errors = {}
        self.raw = 1
        self.available = True
        self.close_count = 0
        self.close_finished = False
        self.wire = None
        self.metrics = {"reaper_reclaimed": 9, "owner_fencing_rejected": 17}
        self.logger = Mock()
        self.client = SimpleNamespace(aclose=self.close)
        self.queue = svc.DurableTaskQueue("redis://synthetic.invalid:6379/15")
        monkeypatch.setattr(self.queue, "_get_script_client", self.acquire)
        monkeypatch.setattr(self.queue, "_load_scripts", self.load)
        monkeypatch.setattr(self.queue, "_evalsha_or_reload", self.evaluate)
        monkeypatch.setattr(svc, "logger", self.logger)
        monkeypatch.setattr(svc, "queue_metrics", self.metrics)
        monkeypatch.setattr(svc, "_FENCING_TOMBSTONE_TTL", 211)
        monkeypatch.setattr(svc, "_DEAD_HASH_TTL", 212)
        monkeypatch.setattr(
            svc, "settings", SimpleNamespace(TASK_QUEUE_CORRUPT_MAX=123)
        )
        monkeypatch.setattr(svc, "_get_max_ready", lambda task_type: 124)
        self.logger.info.side_effect = lambda *args: self.record("info")
        self.logger.warning.side_effect = lambda *args: self.record("warning")
        for name, function in {
            "v2_mark_corrupt_success": admin.v2_mark_corrupt_success,
            "v2_cancel_reason": admin.v2_cancel_reason,
            "normalize_v2_admin_result": admin.normalize_v2_admin_result,
            "should_log_v2_cancel": admin.should_log_v2_cancel,
            "normalize_v2_reaper_result": reaper.normalize_v2_reaper_result,
            "apply_v2_reaper_result": reaper.apply_v2_reaper_result,
        }.items():
            monkeypatch.setattr(svc, name, self.port(name, function))

    def record(self, stage):
        self.trace.append(stage)
        if stage in self.errors:
            raise self.errors[stage]

    def port(self, name, function):
        def call(*args, **kwargs):
            self.record(name)
            return function(*args, **kwargs)

        return call

    async def acquire(self):
        self.record("get")
        return self.client if self.available else None

    async def load(self, client):
        assert client is self.client
        self.record("load")

    async def evaluate(self, *args):
        self.wire = args
        self.record("eval")
        return self.raw

    async def close(self):
        self.close_count += 1
        self.record("close")
        self.close_finished = True

    async def run(self):
        if self.operation == "corrupt":
            return await self.queue.mark_corrupt_v2("task-1", "demo", "bad-payload")
        if self.operation == "cancel":
            return await self.queue.cancel_v2("task-1", "demo", "x" * 250)
        return await self.queue._reclaim_expired_v2("demo")
