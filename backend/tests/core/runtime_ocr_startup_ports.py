"""Original OCR startup through isolated configuration and resource ports."""

import builtins
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import runtime_ocr_startup


@pytest.fixture
def ports(monkeypatch):
    events, imports, failures = [], [], {}
    logger = Mock()
    client, worker, gateway = object(), object(), object()
    cfg = SimpleNamespace(
        enabled=True, remote_connect_timeout_sec=3, remote_read_timeout_sec=17,
        remote_max_concurrency=4, execution_backend="synthetic-remote",
        profile="cloud_api", environment="production",
    )
    state = SimpleNamespace(
        events=events, imports=imports, failures=failures, logger=logger,
        client=client, worker=worker, gateway=gateway, cfg=cfg,
        resources=runtime_ocr_startup.HttpOcrResources(),
    )

    def call(name, result):
        def operation(*args, **kwargs):
            events.append((name, args, kwargs))
            if name in failures:
                raise failures[name]
            return result
        return operation

    modules = {
        "httpx": SimpleNamespace(
            AsyncClient=call("client", client),
            Timeout=call("timeout", "synthetic-timeout"), Limits=call("limits", "synthetic-limits"),
        ),
        "app.core.ocr_runtime_config": SimpleNamespace(get_runtime_config=call("config", cfg)),
        "app.features.ocr_gateway": SimpleNamespace(OCRGateway=call("gateway", gateway)),
        "app.services.ocr_worker_client": SimpleNamespace(create_ocr_worker_client=call("worker", worker)),
        "app.core.deployment_profile": SimpleNamespace(detect_deployment_profile=call("profile", "synthetic-profile")),
        "app.services.ocr_service": SimpleNamespace(set_gateway=call("publish", None)),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name in modules:
            imports.append(name)
            if name in failures:
                raise failures[name]
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    monkeypatch.setattr(runtime_ocr_startup, "logger", logger)
    state.initialize = runtime_ocr_startup.initialize_http_ocr_gateway
    return state
