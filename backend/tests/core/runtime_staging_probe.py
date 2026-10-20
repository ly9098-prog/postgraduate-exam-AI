"""Resolve the startup sweep through each actual runtime consumer."""


def staging_startup_operation(entrypoint):
    if entrypoint == "http":
        from app.main import sweep_staging_on_startup
    else:
        from app.core.bootstrap import sweep_staging_on_startup
    return sweep_staging_on_startup
