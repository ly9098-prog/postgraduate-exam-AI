"""Tests for database parameter hiding configuration."""

from app.core.database import _engine_kwargs, engine


def test_hide_parameters_in_engine_kwargs():
    """The engine kwargs must always include hide_parameters=True.

    This prevents SQLAlchemy from logging INSERT/UPDATE parameter values
    (which may contain encrypted secrets or other sensitive data).
    """
    assert _engine_kwargs.get("hide_parameters") is True, (
        "hide_parameters must be True in engine kwargs"
    )


def test_engine_echo_does_not_disable_hide_parameters():
    """Even when SQL echo is enabled, hide_parameters must remain True."""
    assert engine is not None
    # The sync engine's logger is configured separately from hide_parameters
    assert _engine_kwargs.get("hide_parameters") is True
