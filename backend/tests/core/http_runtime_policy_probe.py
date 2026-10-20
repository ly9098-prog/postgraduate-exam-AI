"""Bind the real HTTP runtime policies to explicit test configuration and probes."""

from types import SimpleNamespace

from app.core import http_runtime_policy as runtime_policy
from app.core.config import resolve_effective_process_role


def http_runtime_policy(monkeypatch, logger, config):
    monkeypatch.setattr(runtime_policy, "logger", logger)

    def role():
        return runtime_policy.prepare_http_runtime_role(config, resolve_effective_process_role)

    return SimpleNamespace(
        role=role, isolate=runtime_policy.assert_http_ocr_isolation,
        report=runtime_policy.report_http_startup_failure,
    )
