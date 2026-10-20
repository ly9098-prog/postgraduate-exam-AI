"""External service ports for the complete standalone role lifecycle."""

import asyncio
import socket
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest_asyncio

from app.core import bootstrap


class RolePorts:
    def __init__(self):
        self.events = []
        self.failures = {}
        self.registries = []
        self.auto_stop = True
        self.signal_ready = asyncio.Event()
        self.stop_event = None
        self.cloud = False
        self.ocr_enabled = False
        self.gateway = None
        self.enqueue = None
        self.network = []
        self.logger = Mock()

    def sync(self, name, result=None):
        def call(*args, **kwargs):
            self.events.append(name)
            if name in self.failures:
                raise self.failures[name]
            return result
        return call

    def asynchronous(self, name, result=None):
        async def call(*args, **kwargs):
            return self.sync(name, result)(*args, **kwargs)
        return call

    async def loop(self, label):
        self.events.append(f"run:{label}")
        try:
            await asyncio.Future()
        finally:
            self.events.append(f"end:{label}")

    def signal(self, event):
        self.sync("signals.install")()
        self.stop_event = event
        self.signal_ready.set()
        if self.auto_stop:
            asyncio.get_running_loop().call_soon(event.set)

    def forbid_network(self, *args, **kwargs):
        self.network.append("connect")
        raise AssertionError("standalone lifecycle must not connect externally")

    def make_gateway(self, *args, **kwargs):
        self.sync("ocr.gateway.create")()
        return SimpleNamespace(shutdown=self.asynchronous("ocr.gateway.stop"))

    def publish_gateway(self, gateway):
        self.gateway = gateway
        self.sync("ocr.gateway.publish")()

    def outbox(self, callback):
        self.enqueue = callback
        return self.loop("outbox")


@pytest_asyncio.fixture
async def role_runtime(monkeypatch, tmp_path):
    state = RolePorts()
    registry_type = bootstrap.TaskRegistry

    def registry():
        instance = registry_type()
        state.registries.append(instance)
        return instance

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bootstrap, "logger", state.logger)
    monkeypatch.setattr(bootstrap, "TaskRegistry", registry)
    monkeypatch.setattr(bootstrap, "_install_signal_handlers", state.signal)
    monkeypatch.setattr(socket.socket, "connect", state.forbid_network)
    monkeypatch.setattr(socket.socket, "connect_ex", state.forbid_network)
    for name, value in {
        "APP_ENV": "test", "PROCESS_ROLE": "worker", "WORKER_CONCURRENCY": 2,
        "WORKER_SHUTDOWN_GRACE_SEC": 1, "WORKER_SCRATCH_DIR": str(tmp_path / "scratch"),
        "STAGING_STORAGE_DIR": str(tmp_path / "staging"),
    }.items():
        monkeypatch.setattr(bootstrap.settings, name, value)
    for name, label in [
        ("run_token_cleanup", "token"), ("run_staging_cleanup", "staging"),
        ("run_export_processor_loop", "export"), ("run_export_cleanup", "export_cleanup"),
    ]:
        monkeypatch.setattr(bootstrap, name, lambda *args, label=label: state.loop(label))
    install_common_ports(monkeypatch, state)
    install_worker_ports(monkeypatch, state)
    install_scheduler_ports(monkeypatch, state)
    try:
        yield state
    finally:
        for instance in state.registries:
            await instance.wait_all(timeout=1)
            assert all(item._task.done() for item in instance._tasks)
        assert not state.network, "a runtime boundary swallowed a connection attempt"


def install_common_ports(monkeypatch, state):
    from app.core import deployment_profile

    monkeypatch.setattr(deployment_profile, "detect_deployment_profile", lambda: (
        deployment_profile.DeploymentProfile.CLOUD_API if state.cloud
        else deployment_profile.DeploymentProfile.LOCAL_IMPORT
    ))
    registry = {"file_io": SimpleNamespace(name="synthetic-file-io")}
    modules = {
        "app.core.logging_config": SimpleNamespace(setup_logging=state.sync("logging.setup")),
        "app.services.production_config_validator": SimpleNamespace(
            validate_production_config=state.sync("config.sync"),
            validate_production_config_async=state.asynchronous("config.async"),
        ),
        "app.services.staging_storage": SimpleNamespace(async_sweep_temp_files=state.asynchronous("staging.sweep", 0)),
        "app.core.executors": SimpleNamespace(
            init_executors_for_role=state.sync("executors.init", registry),
            shutdown_executors=state.asynchronous("executors.stop"),
        ),
        "app.core.executor_registry": SimpleNamespace(
            init_executor_registry=state.sync("executors.register"),
            get_all_executors=lambda: registry, clear_executor_registry=state.sync("executors.clear"),
        ),
        "app.services.formula_graph_spec_renderer": SimpleNamespace(shutdown_formula_render_pool=state.sync("formula.stop")),
        "app.services.pdf_renderer_service": SimpleNamespace(pdf_renderer=SimpleNamespace(shutdown=state.asynchronous("pdf.stop"))),
        "app.core.database": SimpleNamespace(engine=SimpleNamespace(dispose=state.asynchronous("db.dispose"))),
        "app.core.resource_guard": SimpleNamespace(resource_guard=SimpleNamespace(
            start_orphan_reconciler=state.asynchronous("orphans.start"),
            stop_orphan_reconciler=state.asynchronous("orphans.stop"),
        )),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)


def install_worker_ports(monkeypatch, state):
    cfg = SimpleNamespace(enabled=False, execution_backend="synthetic-remote", profile="synthetic")

    def config():
        cfg.enabled = state.ocr_enabled
        return cfg

    modules = {
        "app.core.ocr_runtime_config": SimpleNamespace(get_runtime_config=config),
        "app.features.ocr_gateway": SimpleNamespace(OCRGateway=state.make_gateway),
        "app.services.ocr_worker_client": SimpleNamespace(create_ocr_worker_client=state.sync("ocr.worker.create", object())),
        "app.services.ocr_service": SimpleNamespace(set_gateway=state.publish_gateway, get_gateway=lambda: state.gateway),
        "app.services.ocr_executor_service": SimpleNamespace(ocr_executor=SimpleNamespace(shutdown=state.asynchronous("ocr.executor.stop"))),
        "app.services.task_queue_worker": SimpleNamespace(
            run_dispatcher_v2=lambda: state.loop("dispatcher"), run_reaper_loop_v2=lambda: state.loop("reaper"),
            graceful_shutdown_v2=state.asynchronous("queue.drain"),
            stop_reaper_v2=state.asynchronous("reaper.signal"),
            set_draining_v2=state.asynchronous("queue.draining"),
        ),
        "app.services.ai_prewarm_worker": SimpleNamespace(
            start_worker=state.asynchronous("prewarm.start"), stop_worker=state.asynchronous("prewarm.stop"),
        ),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)


def install_scheduler_ports(monkeypatch, state):
    modules = {
        "app.services.system_task_service": SimpleNamespace(run_scheduler_heartbeat=lambda: state.loop("heartbeat")),
        "app.services.audit_cleanup_scheduler": SimpleNamespace(audit_log_cleanup_scheduler=SimpleNamespace(
            start=state.asynchronous("audit.start"), stop=state.asynchronous("audit.stop"),
        )),
        "app.services.recommendation_metrics_scheduler": SimpleNamespace(recommendation_metrics_scheduler=SimpleNamespace(
            start=state.asynchronous("metrics.start"), stop=state.asynchronous("metrics.stop"),
        )),
        "app.services.export.processor": SimpleNamespace(stop_processor=state.asynchronous("export.signal")),
        "app.services.outbox_service": SimpleNamespace(run_outbox_dispatcher=state.outbox, run_outbox_reconciler=lambda: state.loop("outbox_reconcile")),
        "app.services.task_queue_service": SimpleNamespace(task_queue=SimpleNamespace(
            close=state.asynchronous("queue.close"), enqueue_v2=state.asynchronous("queue.enqueue", "synthetic-task"),
        )),
        "app.services.practice.projection_reconciliation_service": SimpleNamespace(run_answer_projection_reconciler=lambda: state.loop("answer_projection")),
        "app.services.task_observability_service": SimpleNamespace(run_task_health_monitor=lambda: state.loop("task_health")),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
