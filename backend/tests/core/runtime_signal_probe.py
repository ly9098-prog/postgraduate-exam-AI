"""Bind the actual signal installer to the caller's logger port."""

from app.core.runtime_signals import install_role_signal_handlers


def signal_installer(monkeypatch, logger):
    return lambda event: install_role_signal_handlers(event, logger)
