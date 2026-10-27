"""Script-client doubles which never construct Redis connections."""

from types import SimpleNamespace
from unittest.mock import Mock

from app.services import task_queue_service as svc
from app.services import task_queue_v2_heartbeat_contract as contract
from app.services.task_queue_contract import Task


class HeartbeatHarness:
    def __init__(self, monkeypatch):
        self.trace = []
        self.raw = 1
        self.available = True
        self.close_count = 0
        self.close_finished = False
        self.errors = {}
        self.wire = None
        self.metrics = {"owner_fencing_rejected": 9, "other": 17}
        self.logger = Mock()
        self.client = SimpleNamespace(aclose=self.close)
        self.queue = svc.DurableTaskQueue("redis://synthetic.invalid:6379/15")
        self.task = Task(
            task_id="heartbeat-test",
            task_type="demo",
            payload={"opaque": "kept"},
            owner_token="owner-1",
            generation=3,
            lease_expires_at=20,
        )
        monkeypatch.setattr(svc, "queue_metrics", self.metrics)
        monkeypatch.setattr(svc, "logger", self.logger)
        monkeypatch.setattr(contract, "time", SimpleNamespace(time=lambda: 100.0))
        monkeypatch.setattr(svc, "v2_heartbeat_mismatch", self.mismatch)
        monkeypatch.setattr(svc, "apply_v2_heartbeat_result", self.apply)
        monkeypatch.setattr(self.queue, "_get_script_client", self.acquire)
        monkeypatch.setattr(self.queue, "_load_scripts", self.load)
        monkeypatch.setattr(self.queue, "_evalsha_or_reload", self.evaluate)
        self.logger.warning.side_effect = self.warning

    def check(self, stage):
        if stage in self.errors:
            raise self.errors[stage]

    async def acquire(self):
        self.trace.append("get")
        self.check("get")
        return self.client if self.available else None

    async def load(self, client):
        assert client is self.client
        self.trace.append("load")
        self.check("load")

    async def evaluate(self, *args):
        self.wire = args
        self.trace.append("eval")
        self.check("eval")
        return self.raw

    async def close(self):
        self.trace.append("close")
        self.close_count += 1
        self.check("close")
        self.close_finished = True

    def mismatch(self, result):
        self.trace.append(("mismatch", result))
        self.check("mismatch")
        return contract.v2_heartbeat_mismatch(result)

    def warning(self, *args):
        self.trace.append("warning")
        self.check("warning")

    def apply(self, task, *, result, lease_sec):
        self.trace.append(("apply", result, lease_sec))
        assert task is self.task or isinstance(task, tuple)
        self.check("apply")
        return contract.apply_v2_heartbeat_result(
            task,
            result=result,
            lease_sec=lease_sec,
        )

    async def run(self, **kwargs):
        return await self.queue.heartbeat_v2(self.task, **kwargs)
