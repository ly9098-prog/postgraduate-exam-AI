"""Resolve HTTP diagnostics and directories through their actual owners."""

from types import SimpleNamespace

from app.core import runtime_resource_startup
from app.services import runtime_http_startup_diagnostics


def http_startup_operations():
    return SimpleNamespace(
        diagnostics=runtime_http_startup_diagnostics.log_http_startup,
        export=runtime_http_startup_diagnostics.log_http_export_startup,
        directories=runtime_resource_startup.ensure_http_runtime_directories,
        directory_owner=runtime_resource_startup,
    )
