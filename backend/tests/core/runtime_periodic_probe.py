"""Bind shared periodic functions through each real runtime entry."""

from types import SimpleNamespace

from app.services import runtime_periodic_tasks


def periodic_operations(entry):
    module = __import__("app.main" if entry == "http" else "app.core.bootstrap", fromlist=["logger"])
    return SimpleNamespace(
        _periodic_token_cleanup=runtime_periodic_tasks.run_token_cleanup,
        _periodic_staging_cleanup=runtime_periodic_tasks.run_staging_cleanup,
        _periodic_export_cleanup=runtime_periodic_tasks.run_export_cleanup,
        _periodic_export_processor=lambda: runtime_periodic_tasks.run_export_processor_loop(module.logger),
    )
