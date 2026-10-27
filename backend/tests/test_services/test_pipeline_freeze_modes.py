"""Mode, fallthrough, ordering and alias contracts for the original entry."""

import pytest

from tests.test_services.pipeline_freeze_support import (
    assert_compare,
    assert_ir_payload_preserved,
    assert_ir_result,
    fail_at,
    make_harness,
    run,
    snapshot_ir_payload,
)


@pytest.fixture
def h(monkeypatch):
    return make_harness(monkeypatch)


def test_legacy_returns_original_after_registry_get(h):
    h.mode = "legacy"
    result = run(h, ignored=object())
    assert result is h.legacy
    assert h.events == ["mode", "legacy", "legacy.get:frozen_option_registry"]
    assert h.calls["legacy"][0][0][0] is h.blocks
    assert h.calls["legacy"][0][1] == {}


@pytest.mark.parametrize("mode", ["ir", "ir_canary"])
def test_ir_success_reference_and_call_contract(h, mode):
    h.mode = mode
    snapshot = snapshot_ir_payload(h)
    result = run(h)
    assert_ir_result(h, result)
    assert_ir_payload_preserved(result, snapshot)
    assert result["freeze_mode"] == mode
    assert h.calls["document"] == [((h.blocks,), {})]
    assert h.calls["document"][0][0][0] is h.blocks
    assert h.calls["ir"] == [((h.document,), {})]
    assert h.calls["ir"][0][0][0] is h.document
    assert h.events.index("legacy.get:frozen_option_registry") < h.events.index(
        "document"
    )
    assert h.events.index("convert") < h.events.index("deepfreeze")
    if mode == "ir_canary":
        assert_compare(h)
        assert result["freeze_dual_diagnostics"] is h.diagnostics
        assert result["freeze_canary_fallback"] is False
        assert h.calls["failover"] == [
            (
                (),
                {
                    "doc_ir_available": True,
                    "ir_registry_nonempty": True,
                    "legacy_registry_nonempty": True,
                    "option_key_match": True,
                    "binding_lost_count": 4,
                    "exception_occurred": False,
                },
            )
        ]
    else:
        assert "compare" not in h.events
        assert "global_switch" not in h.events


def test_dual_shallow_copy_and_ten_diff_log_limit(h):
    h.mode = "dual"
    result = run(h)
    assert_compare(h)
    assert result is not h.legacy
    for key in ("frozen_option_registry", "frozen_structures", "warnings", "extra"):
        assert result[key] is h.legacy[key]
    assert result["freeze_dual_diagnostics"] is h.diagnostics
    assert result["freeze_ir_warnings"] is h.ir_warnings
    assert result["freeze_mode"] == "dual"
    logs = h.calls["info"]
    assert len(logs) == 11
    assert logs[0][0][1:] == (2, 3, True, False, 4, 12)
    for i, (args, kwargs) in enumerate(logs[1:]):
        assert args[1:] == (f"diff-{i}", f"key-{i}", f"old-{i}", f"new-{i}")
        assert kwargs == {}
    assert "convert" not in h.events
    assert "deepfreeze" not in h.events


@pytest.mark.parametrize("count,expected", [(0, 1), (-1, 1), (2, 3)])
def test_dual_diff_count_gates_logging(h, count, expected):
    h.mode = "dual"
    h.diagnostics["differences_count"] = count
    h.diagnostics["differences"] = h.diagnostics["differences"][:2]
    run(h)
    assert len(h.calls["info"]) == expected
    assert_compare(h)


@pytest.mark.parametrize("mode", ["ir", "dual", "ir_canary", "unrecognized"])
def test_missing_document_does_not_import_ir(h, mode):
    h.mode, h.document = mode, None
    result = run(h)
    assert "ir" not in h.events
    assert "import:freeze_from_document_ir" not in h.events
    assert "convert" not in h.events
    if mode == "ir":
        assert result["freeze_ir_empty"] is True
        assert result["warnings"] == [
            "legacy",
            "shared",
            "freeze_ir_empty_fallback_legacy",
        ]
        assert result["freeze_ir_warnings"] == []
    elif mode == "ir_canary":
        assert result["freeze_canary_fallback"] is True
        assert h.calls["failover"][0][1]["doc_ir_available"] is False
        assert h.calls["failover"][0][1]["ir_registry_nonempty"] is False
        assert h.events.count("compare") == 1
    elif mode == "dual":
        assert result["freeze_mode"] == "dual"
        assert result["freeze_ir_warnings"] == []
        assert h.events.count("compare") == 1
    else:
        assert result is h.legacy


@pytest.mark.parametrize("mode", ["ir", "ir_canary"])
def test_empty_ir_registry_fallback_keeps_shallow_aliases(h, mode):
    h.mode = mode
    h.raw.clear()
    result = run(h)
    assert result is not h.legacy
    for key in ("extra", "frozen_option_registry", "frozen_structures"):
        assert result[key] is h.legacy[key]
    assert result["freeze_ir_warnings"] is h.ir_warnings
    marker = (
        "freeze_ir_empty_fallback_legacy"
        if mode == "ir"
        else "freeze_ir_canary_fallback_legacy"
    )
    assert result["warnings"] == ["legacy", "shared", "ir", marker]
    assert h.legacy_warnings == ["legacy", "shared", "legacy"]
    assert h.ir_warnings == ["shared", "ir", "ir"]
    assert "convert" not in h.events
    if mode == "ir_canary":
        assert result["freeze_canary_fallback_reasons"] is h.reasons


@pytest.mark.parametrize(
    "global_disabled,ir_disabled", [(True, True), (True, False), (False, True)]
)
def test_kill_switches_after_ir_and_short_circuit(h, global_disabled, ir_disabled):
    h.mode = "ir_canary"
    h.global_disabled, h.ir_disabled = global_disabled, ir_disabled
    result = run(h)
    assert result is h.legacy
    assert h.events.index("ir.get:frozen_option_registry") < h.events.index(
        "global_switch"
    )
    assert h.events.count("ir_switch") == (0 if global_disabled else 1)
    assert "compare" not in h.events
    assert "failover" not in h.events
    assert "convert" not in h.events


def test_canary_failover_retains_reasons_and_warning_identity(h):
    h.mode = "ir_canary"
    h.failover = (True, h.reasons)
    result = run(h)
    assert_compare(h)
    assert result["freeze_canary_fallback_reasons"] is h.reasons
    assert result["freeze_ir_warnings"] is h.ir_warnings
    assert result["warnings"] == [
        "legacy",
        "shared",
        "ir",
        "freeze_ir_canary_fallback_legacy",
    ]
    assert result["extra"] is h.extra
    assert result["frozen_option_registry"] is h.legacy_registry
    assert "convert" not in h.events


def test_unknown_mode_still_attempts_ir_before_warning(h):
    h.mode = "unrecognized"
    result = run(h)
    assert result is h.legacy
    assert h.events.index("ir") < h.events.index("warning")
    assert h.calls["warning"][0][0][1] == "unrecognized"
    assert "compare" not in h.events


@pytest.mark.parametrize("mode", ["dual", "ir", "ir_canary", "unrecognized"])
def test_initial_ordinary_ir_error_is_caught_then_mode_continues(h, mode):
    h.mode = mode
    error = RuntimeError("synthetic-ir")
    fail_at(h, "ir", error)
    result = run(h)
    assert h.calls["warning"][0][0][1] is error
    assert h.events.index("warning") > h.events.index("ir")
    if mode == "unrecognized":
        assert result is h.legacy
    else:
        assert result["freeze_ir_warnings"] == ["ir_freeze_error: synthetic-ir"]
    if mode == "ir_canary":
        assert h.calls["failover"][0][1]["exception_occurred"] is True
        assert h.calls["failover"][0][1]["ir_registry_nonempty"] is False


def test_dual_diff_missing_optional_fields_use_defaults(h):
    h.mode = "dual"
    h.diagnostics["differences"] = [{"type": "only-type"}]
    run(h)
    assert h.calls["info"][1][0][1:] == ("only-type", "?", "", "")


def test_ir_missing_optional_fields_use_defaults(h):
    for key in ("warnings", "frozen_structures", "freeze_checksum"):
        del h.ir[key]
    result = run(h)
    assert result["freeze_ir_warnings"] == []
    assert result["frozen_structures"] == []
    assert result["freeze_checksum"] == ""
    assert result["warnings"] == ["legacy", "shared"]


@pytest.mark.parametrize("mode", ["ir", "ir_canary"])
def test_empty_fallback_copies_before_reading_legacy_warnings(h, mode):
    h.mode = mode
    h.raw.clear()
    fail_at(h, "legacy.get:warnings", AssertionError("must read copy"))
    result = run(h)
    assert result["warnings"][:3] == ["legacy", "shared", "ir"]
    assert "legacy.get:warnings" not in h.events


def test_falsey_document_is_still_passed_to_ir(h):
    h.document = {}
    run(h)
    assert h.calls["ir"][0][0][0] is h.document


def test_canary_comparison_defaults_and_missing_legacy_registry(h):
    h.mode = "ir_canary"
    h.diagnostics.clear()
    del h.legacy["frozen_option_registry"]
    result = run(h)
    assert h.calls["compare"][0][0][2] == {}
    assert h.calls["failover"] == [
        (
            (),
            {
                "doc_ir_available": True,
                "ir_registry_nonempty": True,
                "legacy_registry_nonempty": False,
                "option_key_match": False,
                "binding_lost_count": 0,
                "exception_occurred": False,
            },
        )
    ]
    assert h.events.count("compare") == 1
    assert result["freeze_dual_diagnostics"] is h.diagnostics


@pytest.mark.parametrize("mode", ["legacy", "unrecognized"])
def test_missing_legacy_registry_does_not_add_key_on_identity_return(h, mode):
    h.mode = mode
    del h.legacy["frozen_option_registry"]
    result = run(h)
    assert result is h.legacy
    assert "frozen_option_registry" not in result
