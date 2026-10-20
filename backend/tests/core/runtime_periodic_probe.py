"""Bind shared periodic functions through each real runtime entry."""

from types import SimpleNamespace

from app import main
from app.core import bootstrap


def periodic_operations(entry):
    module = main if entry == "http" else bootstrap
    return SimpleNamespace(
        _periodic_token_cleanup=module.run_token_cleanup,
        _periodic_staging_cleanup=module.run_staging_cleanup,
        _periodic_export_cleanup=module.run_export_cleanup,
        _periodic_export_processor=lambda: module.run_export_processor_loop(module.logger),
    )
