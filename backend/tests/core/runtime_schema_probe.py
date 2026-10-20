"""Bind real startup schema services to isolated persistence and logging ports."""

from types import SimpleNamespace

from app.services import runtime_schema_diagnostics
from app.services.export import schema_compatibility


def schema_operations(monkeypatch, logger, session_factory):
    monkeypatch.setattr(schema_compatibility, "logger", logger)
    monkeypatch.setattr(runtime_schema_diagnostics, "logger", logger)

    async def repair():
        await schema_compatibility.repair_export_idempotency_schema(session_factory)

    async def diagnose():
        await runtime_schema_diagnostics.log_runtime_schema_divergence(session_factory)

    return SimpleNamespace(repair=repair, diagnose=diagnose)
