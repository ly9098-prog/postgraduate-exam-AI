"""Catch extent, typed matching, and synchronous cancellation propagation."""

import asyncio
from builtins import UnboundLocalError as _UnboundLocalError

import pytest

from tests.test_services.pipeline_freeze_support import (
    fail_at,
    force_unbound_converter_path,
    make_harness,
    module,
    run,
)


@pytest.fixture
def h(monkeypatch):
    return make_harness(monkeypatch)


@pytest.mark.parametrize(
    "mode,event",
    [
        ("legacy", "mode"),
        ("legacy", "legacy"),
        ("legacy", "legacy.get:frozen_option_registry"),
        ("ir", "document"),
        ("dual", "compare"),
        ("dual", "info"),
        ("ir", "convert"),
        ("ir", "deepfreeze"),
        ("ir", "ir.get:frozen_structures"),
        ("ir", "ir.get:freeze_checksum"),
        ("ir", "ir.get:warnings"),
        ("ir_canary", "global_switch"),
        ("ir_canary", "ir_switch"),
        ("ir_canary", "compare"),
        ("ir_canary", "failover"),
        ("ir_canary", "convert"),
        ("ir_canary", "deepfreeze"),
        ("ir_canary", "ir.get:warnings"),
        ("unrecognized", "warning"),
    ],
)
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
def test_errors_outside_initial_ir_try_propagate_identity(h, mode, event, error_type):
    h.mode = mode
    error = error_type(f"synthetic-{event}")
    fail_at(h, event, error)
    with pytest.raises(error_type) as caught:
        run(h)
    assert caught.value is error
    assert h.events[-1] == event
    assert caught.value.__cause__ is None


@pytest.mark.parametrize(
    "event",
    [
        "import:freeze_from_document_ir",
        "import:freeze_registry_to_block_format",
        "ir",
        "ir.get:frozen_option_registry",
    ],
)
def test_cancel_in_initial_ir_try_is_not_caught(h, event):
    error = asyncio.CancelledError("synthetic-cancel")
    fail_at(h, event, error)
    with pytest.raises(asyncio.CancelledError) as caught:
        run(h)
    assert caught.value is error
    assert "warning" not in h.events
    assert "convert" not in h.events


@pytest.mark.parametrize(
    "event",
    [
        "import:freeze_from_document_ir",
        "import:freeze_registry_to_block_format",
        "ir.get:frozen_option_registry",
    ],
)
def test_initial_import_or_registry_get_error_is_fallback(h, event):
    error = ValueError("synthetic-initial")
    fail_at(h, event, error)
    result = run(h)
    assert result["freeze_ir_empty"] is True
    assert result["freeze_ir_warnings"] == ["ir_freeze_error: synthetic-initial"]
    assert h.calls["warning"][0][0][1] is error


@pytest.mark.parametrize("event", ["warning", "ir.get:warnings"])
def test_fallback_errors_do_not_get_caught_again(h, event):
    h.raw.clear()
    error = RuntimeError("synthetic-fallback")
    fail_at(h, event, error)
    with pytest.raises(RuntimeError) as caught:
        run(h)
    assert caught.value is error
    assert h.events[-1] == event


def test_error_in_catch_logger_retains_exception_context(h):
    original, logging_error = ValueError("ir"), RuntimeError("logger")
    fail_at(h, "ir", original)
    fail_at(h, "warning", logging_error)
    with pytest.raises(RuntimeError) as caught:
        run(h)
    assert caught.value is logging_error
    assert caught.value.__context__ is original
    assert caught.value.__cause__ is None


@pytest.mark.parametrize(
    "error_type,caught",
    [
        (ValueError, True),
        (RuntimeError, False),
        (asyncio.CancelledError, False),
    ],
)
def test_global_exception_type_controls_only_initial_catch(
    h, monkeypatch, error_type, caught
):
    monkeypatch.setattr(module, "Exception", ValueError, raising=False)
    error = error_type("typed")
    fail_at(h, "ir", error)
    if caught:
        assert run(h)["freeze_ir_empty"] is True
        assert h.calls["warning"][0][0][1] is error
    else:
        with pytest.raises(error_type) as raised:
            run(h)
        assert raised.value is error
        assert "warning" not in h.events


def test_exception_binding_is_read_when_exception_is_matched(h, monkeypatch):
    error = RuntimeError("late-type")

    def replace_then_raise(*args):
        monkeypatch.setattr(module, "Exception", ValueError, raising=False)
        raise error

    h.hooks["ir"] = replace_then_raise
    with pytest.raises(RuntimeError) as caught:
        run(h)
    assert caught.value is error
    assert "warning" not in h.events


@pytest.mark.parametrize("mode", ["ir", "ir_canary"])
def test_late_deepfreeze_import_error_propagates(h, mode):
    h.mode = mode
    error = ImportError("synthetic-deepfreeze")
    fail_at(h, "import:_freeze_deep_freeze", error)
    with pytest.raises(ImportError) as caught:
        run(h)
    assert caught.value is error
    assert "warning" not in h.events
    assert "convert" not in h.events


def test_second_converter_import_error_is_outside_catch(h):
    error = ImportError("second-converter")
    count = []

    def fail_second():
        count.append(True)
        if len(count) == 2:
            raise error

    h.hooks["import:freeze_registry_to_block_format"] = fail_second
    with pytest.raises(ImportError) as caught:
        run(h)
    assert caught.value is error
    assert len(count) == 2
    assert "warning" not in h.events


def test_dual_log_diff_access_failure_propagates(h):
    h.mode = "dual"
    h.diagnostics["differences"] = [{}]
    with pytest.raises(KeyError, match="type"):
        run(h)
    assert len(h.calls["info"]) == 1


def test_warning_prefix_failure_is_outside_initial_catch(h):
    h.mode = "ir_canary"
    h.ir["warnings"] = [object()]
    with pytest.raises(AttributeError, match="startswith"):
        run(h)
    assert "failover" not in h.events
    assert "warning" not in h.events


@pytest.mark.parametrize("mode", ["ir", "ir_canary"])
def test_unhashable_warning_dedup_error_propagates(h, mode):
    h.mode = mode
    h.legacy["warnings"] = [[]]
    with pytest.raises(TypeError, match="unhashable"):
        run(h)
    assert h.events.count("ir") == 1
    assert "warning" not in h.events


@pytest.mark.parametrize("mode", ["dual", "ir_canary"])
def test_canary_import_failure_propagates_only_when_selected(h, mode):
    h.mode = mode
    error = ImportError("synthetic-canary")
    fail_at(h, "import:check_ir_canary_failover", error)
    if mode == "dual":
        assert run(h)["freeze_mode"] == "dual"
    else:
        with pytest.raises(ImportError) as caught:
            run(h)
        assert caught.value is error
        assert "global_switch" not in h.events


@pytest.mark.parametrize("disabled,event", [(True, "info"), (False, "warning")])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
def test_canary_return_logging_errors_propagate(h, disabled, event, error_type):
    h.mode, h.global_disabled = "ir_canary", disabled
    h.failover = (True, h.reasons)
    error = error_type("canary-return-log")
    fail_at(h, event, error)
    with pytest.raises(error_type) as caught:
        run(h)
    assert caught.value is error
    assert h.events[-1] == event
    assert "convert" not in h.events


def test_exception_shadow_deleted_during_error_falls_back_to_builtin(h, monkeypatch):
    error = RuntimeError("deleted-exception")
    monkeypatch.setattr(module, "Exception", ValueError, raising=False)

    def delete_then_raise(*args):
        monkeypatch.delattr(module, "Exception")
        raise error

    h.hooks["ir"] = delete_then_raise
    assert run(h)["freeze_ir_empty"] is True
    assert h.calls["warning"][0][0][1] is error


@pytest.mark.parametrize("shadow_error", [False, True])
@pytest.mark.parametrize(
    "source",
    [
        "missing_document",
        "freeze_from_document_ir",
        "freeze_registry_to_block_format",
    ],
)
def test_canary_unbound_converter_preserves_original_exception(
    h, monkeypatch, source, shadow_error
):
    values = force_unbound_converter_path(monkeypatch, h, source)
    if shadow_error:
        monkeypatch.setattr(module, "UnboundLocalError", RuntimeError, raising=False)
    with pytest.raises(_UnboundLocalError) as caught:
        run(h)
    error = caught.value
    assert type(error) is _UnboundLocalError
    assert str(error) == (
        "cannot access local variable '_ir_to_legacy' where it is not associated with a value"
    )
    assert error.name is None
    assert error.__context__ is None
    assert error.__cause__ is None
    assert error.__suppress_context__ is False
    assert len(values) == 3
    assert values[0] == {"callback_populated": True}
    assert h.calls["compare"][0][0][3] is values[0]
    assert values[1] is h.legacy_registry
    assert values[2] is (source != "missing_document")
    assert h.events[-3:] == ["builtin_bool", "failover", "import:_freeze_deep_freeze"]
    assert h.events.count("compare") == 1
    assert h.events.count("warning") == (source != "missing_document")
    assert "ir" not in h.events
    assert "convert" not in h.events
    assert "deepfreeze" not in h.events
