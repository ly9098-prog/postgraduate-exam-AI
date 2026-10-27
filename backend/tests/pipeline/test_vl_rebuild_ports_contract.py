"""Live global ports, captured local imports and error/cancellation scopes."""

import asyncio
from types import SimpleNamespace

import pytest

from app.features import option_recovery, question_type_classifier
from app.features import pipeline_orchestrator as module
from tests.pipeline.vl_rebuild_support import execute, fail_at, make_harness, observe


@pytest.mark.parametrize("point", ["warning"])
def test_preflight_warning_error_is_outside_outer_fallback(monkeypatch, point):
    h = make_harness(monkeypatch)
    error = RuntimeError(point)
    fail_at(h, point, error)
    with pytest.raises(RuntimeError) as caught:
        execute(h, vl_config=None)
    assert caught.value is error and h.events == ["warning"]


def test_file_type_resolution_error_is_outside_outer_fallback(monkeypatch):
    h = make_harness(monkeypatch)
    error = RuntimeError("lower")

    class Path:
        def lower(self):
            raise error

    with pytest.raises(RuntimeError) as caught:
        execute(h, file_path=Path())
    assert caught.value is error and h.events == []


@pytest.mark.parametrize(
    "point",
    [
        "construct_router",
        "configure",
        "file_read",
        "profile",
        "pp",
        "fix",
        "run",
        "repair",
        "recover",
    ],
)
def test_cancellation_propagates_without_ordinary_error_fallback(monkeypatch, point):
    h = make_harness(monkeypatch)
    error = asyncio.CancelledError(point)
    fail_at(h, point, error)
    with pytest.raises(asyncio.CancelledError) as caught:
        execute(h)
    assert caught.value is error and "warning" not in h.events


def test_classifier_functions_are_captured_before_profile_callback(monkeypatch):
    h = make_harness(monkeypatch)

    def replace(_):
        monkeypatch.setattr(
            question_type_classifier,
            "detect_options_from_text",
            lambda _: pytest.fail("late classifier"),
        )
        monkeypatch.setattr(
            question_type_classifier,
            "extract_options_from_text",
            lambda _: pytest.fail("late extractor"),
        )

    h.hooks["profile"] = replace
    assert execute(h)[0]["text"] == "VL:A B C"
    assert h.records["detect"] == ["PP:A B", "VL:A B C"]


def test_recovery_function_is_imported_for_each_accepted_page(monkeypatch):
    h = make_harness(monkeypatch)

    def new_recover(best, pp, raw):
        observe(h, "new_recover", (best, pp, raw))
        return h.recovery

    h.hooks["recover"] = lambda _: monkeypatch.setattr(
        option_recovery, "recover_options_from_sources", new_recover
    )
    output = execute(h, file_path="/synthetic/input.pdf")
    assert (
        len(output) == 2
        and len(h.records["recover"]) == len(h.records["new_recover"]) == 1
    )
    assert h.events.index("recover") < h.events.index("new_recover")


def test_run_coro_callable_is_bound_before_router_fix_argument(monkeypatch):
    h = make_harness(monkeypatch)
    h.hooks["fix"] = lambda _: monkeypatch.setattr(
        module, "_run_coro_in_loop", lambda _: pytest.fail("late run")
    )
    assert execute(h)[0]["text"] == "VL:A B C"
    assert len(h.records["run"]) == 1


def test_logger_remains_live_after_ocr_callback(monkeypatch):
    h = make_harness(monkeypatch)

    def replace(_):
        monkeypatch.setattr(
            module,
            "logger",
            SimpleNamespace(
                info=lambda *args: observe(h, "new_info", args),
                warning=lambda *args: observe(h, "new_warning", args),
            ),
        )

    h.hooks["pp"] = replace
    execute(h)
    assert "info" not in h.events and len(h.records["new_info"]) == 3


def test_global_builtin_override_is_read_at_its_expression_site(monkeypatch):
    h = make_harness(monkeypatch)
    monkeypatch.setattr(module, "len", lambda value: len(value) + 10, raising=False)
    output = execute(h)
    assert output[0]["text"] == "PP:A B" and output[0]["block_index"] == 10
    assert "fix" not in h.events and h.records["info"][-1][1] == 11


def test_pdf_close_error_overrides_render_error_with_original_context(monkeypatch):
    h = make_harness(monkeypatch)
    original, replacement = RuntimeError("render"), RuntimeError("close")
    fail_at(h, "png", original)
    fail_at(h, "close_pdf", replacement)
    assert execute(h, file_path="/synthetic/input.pdf") is None
    assert h.records["warning"][-1] == ("VL_REBUILD failed: %s", replacement)
    assert replacement.__context__ is original
