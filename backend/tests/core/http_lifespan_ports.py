"""Isolate lifespan resource ports while retaining real asyncio task ownership."""

import asyncio
import socket
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest_asyncio

from app import main
from app.core import (
    deployment_profile,
    http_runtime_policy,
    runtime_resource_shutdown,
    runtime_resource_startup,
    runtime_role_shutdown,
    runtime_task_shutdown,
)
from app.services import (
    runtime_ocr_startup,
    runtime_schema_diagnostics,
    runtime_startup_checks,
)
from app.services.export import schema_compatibility


@pytest_asyncio.fixture
async def runtime(monkeypatch, tmp_path):
    events = []
    failures = {}
    tasks = []
    network = []
    state = SimpleNamespace(
        events=events, failures=failures, tasks=tasks, ocr_enabled=False,
        client=None, gateway=None, enqueue=None,
    )

    def sync(name, result=None):
        def call(*args, **kwargs):
            events.append(name)
            if name in failures:
                raise failures[name]
            return result
        return call

    def asynchronous(name, result=None):
        async def call(*args, **kwargs):
            return sync(name, result)(*args, **kwargs)
        return call

    async def loop(label):
        events.append(f"run:{label}")
        try:
            await asyncio.Future()
        finally:
            events.append(f"end:{label}")

    @asynccontextmanager
    async def session():
        events.append("session.enter")
        try:
            yield SimpleNamespace(commit=asynchronous("session.commit"))
        finally:
            events.append("session.exit")

    original_create = asyncio.create_task

    def create(coro, **kwargs):
        task = original_create(coro, **kwargs)
        tasks.append(task)
        return task

    def forbid_network(*args, **kwargs):
        network.append("connect")
        raise AssertionError("lifespan contract must not connect to external services")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PROCESS_ROLE", "web")
    monkeypatch.setattr(socket.socket, "connect", forbid_network)
    monkeypatch.setattr(main.asyncio, "create_task", create)
    for name, value in {
        "APP_ENV": "test", "PROCESS_ROLE": "web", "LOCAL_ASYNC_RUNTIME_ENABLED": False,
        "REDIS_URL": "", "EXPORT_DIR": str(tmp_path / "exports"),
    }.items():
        monkeypatch.setattr(main.settings, name, value)
    monkeypatch.setattr(main, "_production_mode", False)
    monkeypatch.setattr(main, "validate_production_config", sync("config.sync"))
    monkeypatch.setattr(main, "validate_production_config_async", asynchronous("config.async"))
    monkeypatch.setattr(main, "init_db", asynchronous("db.init"))
    monkeypatch.setattr(main, "async_session", session)
    monkeypatch.setattr(main, "ensure_dev_super_admin", asynchronous("admin.seed", False))
    monkeypatch.setattr(main, "loaded_local_ocr_modules", lambda: [])
    monkeypatch.setattr(main, "is_restricted_ocr_environment", lambda: False)
    monkeypatch.setattr(
        deployment_profile, "detect_deployment_profile",
        lambda: deployment_profile.DeploymentProfile.LOCAL_IMPORT,
    )
    for attr, label in {
        "monitor_event_loop_lag": "lag", "_periodic_export_processor": "export",
        "_periodic_token_cleanup": "token", "_periodic_staging_cleanup": "staging",
        "_periodic_export_cleanup": "export_cleanup",
    }.items():
        monkeypatch.setattr(main, attr, lambda *args, label=label: loop(label))

    def client(*args, **kwargs):
        state.client = SimpleNamespace(aclose=asynchronous("ocr.client.close"))
        sync("ocr.client.create")()
        return state.client

    def gateway(*args, **kwargs):
        sync("ocr.gateway.create")()
        state.gateway = SimpleNamespace(shutdown=asynchronous("ocr.gateway.stop"))
        return state.gateway

    def outbox(enqueue):
        state.enqueue = enqueue
        return loop("outbox_dispatcher")

    cfg = SimpleNamespace(
        enabled=False, remote_connect_timeout_sec=1, remote_read_timeout_sec=1,
        remote_max_concurrency=1, execution_backend="remote", profile="local_import",
        environment="test",
    )

    def config():
        cfg.enabled = state.ocr_enabled
        return cfg

    registry = {"file_io": SimpleNamespace(name="synthetic-file-io")}
    dialect = SimpleNamespace(name="synthetic")
    engine = SimpleNamespace(
        dialect=dialect, sync_engine=SimpleNamespace(dialect=dialect),
        dispose=asynchronous("db.dispose"),
    )
    from app.core import database

    monkeypatch.setattr(database, "engine", engine)
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", client)
    modules = {
        "app.core.ocr_profile": SimpleNamespace(get_ocr_profile=lambda: SimpleNamespace(
            name="synthetic", use_gpu=False, max_workers=1, max_pdf_pages=1,
        )),
        "app.services.staging_storage": SimpleNamespace(async_sweep_temp_files=asynchronous("staging.sweep", 0)),
        "app.services.export.capability": SimpleNamespace(log_export_config_on_startup=sync("export.config")),
        "app.services.recommendation_seed_service": SimpleNamespace(seed_default_recommendation_strategies=asynchronous("recommendation.seed", {})),
        "app.services.health_check_service": SimpleNamespace(check_ai_model_config=asynchronous("ai.check", SimpleNamespace(
            severity="ok", enabled_count=1, default_count=1, providers=[], features=[],
        ))),
        "app.core.executor_registry": SimpleNamespace(
            init_executor_registry=sync("executors.register"), get_all_executors=lambda: registry,
            clear_executor_registry=sync("executors.clear"),
        ),
        "app.core.executors": SimpleNamespace(
            init_executors_for_role=sync("executors.init", registry),
            shutdown_executors=asynchronous("executors.stop"),
        ),
        "app.core.ocr_runtime_config": SimpleNamespace(get_runtime_config=config),
        "app.services.ocr_worker_client": SimpleNamespace(create_ocr_worker_client=sync("ocr.worker.create", object())),
        "app.features.ocr_gateway": SimpleNamespace(OCRGateway=gateway),
        "app.services.ocr_service": SimpleNamespace(set_gateway=sync("ocr.gateway.publish")),
        "app.services.export.processor": SimpleNamespace(stop_processor=asynchronous("export.signal")),
        "app.services.task_queue_worker": SimpleNamespace(
            run_dispatcher_v2=lambda: loop("dispatcher"), run_reaper_loop_v2=lambda: loop("reaper"),
            graceful_shutdown_v2=asynchronous("queue.drain"), stop_reaper_v2=asynchronous("reaper.signal"),
            set_draining_v2=asynchronous("queue.set_draining"),
        ),
        "app.services.ai_prewarm_worker": SimpleNamespace(start_worker=asynchronous("prewarm.start"), stop_worker=asynchronous("prewarm.stop")),
        "app.services.system_task_service": SimpleNamespace(run_scheduler_heartbeat=lambda: loop("heartbeat")),
        "app.services.audit_cleanup_scheduler": SimpleNamespace(audit_log_cleanup_scheduler=SimpleNamespace(start=asynchronous("audit.start"), stop=asynchronous("audit.stop"))),
        "app.services.recommendation_metrics_scheduler": SimpleNamespace(recommendation_metrics_scheduler=SimpleNamespace(start=asynchronous("metrics.start"), stop=asynchronous("metrics.stop"))),
        "app.services.outbox_service": SimpleNamespace(run_outbox_dispatcher=outbox, run_outbox_reconciler=lambda: loop("outbox_reconciler")),
        "app.services.task_queue_service": SimpleNamespace(task_queue=SimpleNamespace(close=asynchronous("queue.close"), enqueue_v2=asynchronous("queue.enqueue", "synthetic-task"))),
        "app.core.resource_guard": SimpleNamespace(resource_guard=SimpleNamespace(start_orphan_reconciler=asynchronous("orphans.start"), stop_orphan_reconciler=asynchronous("orphans.stop"))),
        "app.services.formula_graph_spec_renderer": SimpleNamespace(shutdown_formula_render_pool=sync("formula.stop")),
        "app.services.ocr_executor_service": SimpleNamespace(ocr_executor=SimpleNamespace(shutdown=asynchronous("ocr.executor.stop"))),
        "app.services.pdf_renderer_service": SimpleNamespace(pdf_renderer=SimpleNamespace(shutdown=asynchronous("pdf.stop"))),
        "app.core.ai_runtime_guard": SimpleNamespace(ai_runtime_guard=SimpleNamespace(close=asynchronous("ai.close"))),
        "app.features.token_budget": SimpleNamespace(close_token_budget=asynchronous("budget.close")),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    logger = SimpleNamespace(info=Mock(), warning=Mock(), critical=Mock(), error=Mock(), debug=Mock(), exception=Mock())
    monkeypatch.setattr(main, "logger", logger)
    for module in [
        runtime_resource_shutdown, runtime_resource_startup, runtime_role_shutdown, runtime_task_shutdown,
        runtime_startup_checks, runtime_schema_diagnostics, schema_compatibility, runtime_ocr_startup,
        http_runtime_policy,
    ]:
        monkeypatch.setattr(module, "logger", logger)
    state.logger = logger
    try:
        yield state
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        assert all(task.done() for task in tasks)
        assert not network, "unexpected network attempts were swallowed by a startup/cleanup boundary"
