"""Signal registration order, callback idempotency and error contracts."""

import asyncio
import signal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.core.runtime_signal_probe import signal_installer


@pytest.fixture
def ports(monkeypatch):
    logger, registrations = Mock(), []
    state = SimpleNamespace(
        logger=logger, registrations=registrations, failures={},
        event=asyncio.Event(), installer=signal_installer(monkeypatch, logger),
    )

    def register(sig, callback):
        registrations.append((sig, callback))
        if sig in state.failures:
            raise state.failures[sig]

    monkeypatch.setattr(asyncio, "get_running_loop", lambda: SimpleNamespace(add_signal_handler=register))
    return state


def test_installs_sigterm_then_sigint_with_one_callback_and_sets_event_once(ports):
    assert ports.installer(ports.event) is None
    assert [sig for sig, _ in ports.registrations] == [signal.SIGTERM, signal.SIGINT]
    first, second = [callback for _, callback in ports.registrations]
    assert first is second
    assert not ports.event.is_set()
    first()
    assert ports.event.is_set()
    second()
    ports.logger.info.assert_called_once_with("Received shutdown signal, initiating graceful shutdown")
    ports.logger.warning.assert_not_called()


@pytest.mark.parametrize("failed", [signal.SIGTERM, signal.SIGINT])
@pytest.mark.parametrize("error_type", [NotImplementedError, RuntimeError, asyncio.CancelledError])
def test_registration_error_policy_and_continuation_are_original(ports, failed, error_type):
    error = error_type("synthetic signal registration error")
    ports.failures[failed] = error
    if error_type is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError) as caught:
            ports.installer(ports.event)
        assert caught.value is error
        assert [sig for sig, _ in ports.registrations] == (
            [signal.SIGTERM] if failed == signal.SIGTERM else [signal.SIGTERM, signal.SIGINT]
        )
    else:
        ports.installer(ports.event)
        assert [sig for sig, _ in ports.registrations] == [signal.SIGTERM, signal.SIGINT]
    if error_type is RuntimeError:
        ports.logger.warning.assert_called_once_with("Could not install signal handler for %s", failed)
    else:
        ports.logger.warning.assert_not_called()
    assert not ports.event.is_set()


def test_existing_stop_request_ignores_callback_without_logging(ports):
    ports.event.set()
    ports.installer(ports.event)
    ports.registrations[0][1]()
    ports.logger.info.assert_not_called()


def test_callback_logger_failure_precedes_stop_event_write(ports):
    ports.installer(ports.event)
    error = RuntimeError("synthetic shutdown signal log failure")
    ports.logger.info.side_effect = error
    with pytest.raises(RuntimeError) as caught:
        ports.registrations[0][1]()
    assert caught.value is error
    assert not ports.event.is_set()


def test_get_running_loop_error_propagates_before_registration(ports, monkeypatch):
    error = RuntimeError("synthetic no running loop")
    monkeypatch.setattr(asyncio, "get_running_loop", Mock(side_effect=error))
    with pytest.raises(RuntimeError) as caught:
        ports.installer(ports.event)
    assert caught.value is error
    assert not ports.registrations
    ports.logger.warning.assert_not_called()


@pytest.mark.parametrize("failed", [signal.SIGTERM, signal.SIGINT])
def test_registration_warning_error_prevents_later_registration(ports, failed):
    ports.failures[failed] = RuntimeError("synthetic unsupported handler")
    error = RuntimeError("synthetic warning failure")
    ports.logger.warning.side_effect = error
    with pytest.raises(RuntimeError) as caught:
        ports.installer(ports.event)
    assert caught.value is error
    assert [sig for sig, _ in ports.registrations] == (
        [signal.SIGTERM] if failed == signal.SIGTERM else [signal.SIGTERM, signal.SIGINT]
    )


def test_both_unsupported_signals_remain_nonfatal_without_setting_event(ports):
    ports.failures.update({
        signal.SIGTERM: NotImplementedError(), signal.SIGINT: NotImplementedError(),
    })
    ports.installer(ports.event)
    assert [sig for sig, _ in ports.registrations] == [signal.SIGTERM, signal.SIGINT]
    assert not ports.event.is_set()
    ports.logger.warning.assert_not_called()
