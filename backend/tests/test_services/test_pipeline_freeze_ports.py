"""Local-import capture and late global/builtin resolution contracts."""

import builtins
import inspect

import pytest

from tests.test_services.pipeline_freeze_support import (
    make_harness,
    module,
    observe,
    ocr_canary,
    run,
    stage,
)


@pytest.fixture
def h(monkeypatch):
    return make_harness(monkeypatch)


def test_entry_stays_synchronous_with_original_signature():
    method = module.ImportPipeline._run_structure_freeze
    assert not inspect.iscoroutinefunction(method)
    parameters = inspect.signature(method).parameters
    assert list(parameters) == ["self", "normalized_blocks", "_kw"]
    assert parameters["_kw"].kind is inspect.Parameter.VAR_KEYWORD
    assert parameters["normalized_blocks"].annotation == "list[dict]"
    assert inspect.signature(method).return_annotation == "dict"


@pytest.mark.parametrize(
    "mode,expected", [("ir", "replacement"), ("ir_canary", "convert")]
)
def test_converter_reimport_in_ir_but_capture_in_canary(h, monkeypatch, mode, expected):
    h.mode = mode
    replacement_value = object()

    def replacement(raw):
        observe(h, "replacement", raw)
        return replacement_value

    def replace(*args):
        monkeypatch.setattr(stage, "freeze_registry_to_block_format", replacement)

    h.hooks["ir"] = replace
    result = run(h)
    assert result["frozen_option_registry"] is h.frozen
    assert h.calls[expected][0][0][0] is h.raw
    assert h.calls["deepfreeze"][0][0][0] is (
        replacement_value if mode == "ir" else h.converted
    )
    assert h.events.count("import:freeze_registry_to_block_format") == (
        2 if mode == "ir" else 1
    )
    assert ("convert" in h.events) is (mode == "ir_canary")
    assert ("replacement" in h.events) is (mode == "ir")


def test_each_invocation_imports_fresh_ir_callable(h, monkeypatch):
    run(h)
    fresh = object()

    def replacement(document):
        assert document is h.document
        return {"frozen_option_registry": h.raw, "freeze_checksum": fresh}

    monkeypatch.setattr(stage, "freeze_from_document_ir", replacement)
    assert run(h)["freeze_checksum"] is fresh
    assert h.events.count("ir") == 1
    assert h.events.count("import:freeze_from_document_ir") == 2


@pytest.mark.parametrize("mode", ["ir", "dual", "ir_canary"])
@pytest.mark.parametrize("action", ["reassign", "delete"])
def test_method_keeps_interpreter_builtins_when_namespace_key_changes(
    h, monkeypatch, mode, action
):
    h.mode = mode
    method = module.ImportPipeline._run_structure_freeze
    bound = method.__builtins__
    assert bound is builtins.__dict__
    if action == "reassign":
        monkeypatch.setitem(module.__dict__, "__builtins__", {})
    else:
        monkeypatch.delitem(module.__dict__, "__builtins__")
    result = run(h)
    assert method.__builtins__ is bound
    assert result["freeze_mode"] == mode
    if mode != "dual":
        assert result["frozen_option_registry"] is h.frozen


@pytest.mark.parametrize(
    "name,mode,trigger",
    [
        ("dict", "dual", "compare"),
        ("list", "ir", "convert"),
        ("bool", "ir_canary", "compare"),
        ("any", "ir_canary", "compare"),
    ],
)
def test_builtin_globals_replaced_by_late_callback(h, monkeypatch, name, mode, trigger):
    h.mode = mode
    original = getattr(builtins, name)
    seen = []

    def replacement(*args, **kwargs):
        seen.append((args, kwargs))
        return original(*args, **kwargs)

    def replace(*args):
        monkeypatch.setattr(module, name, replacement, raising=False)

    h.hooks[trigger] = replace
    result = run(h)
    assert seen
    assert result["freeze_mode"] == mode
    if name == "dict":
        assert seen[0][0][0] is h.legacy
    if name == "list":
        assert seen[0][0][0] is not h.legacy_warnings
    if name == "bool":
        assert seen[0][0][0] is h.raw
        assert seen[1][0][0] is h.legacy_registry
        assert seen[2][0] == (False,)
    if name == "any":
        assert len(seen) == 1


@pytest.mark.parametrize(
    "name,mode,trigger",
    [
        ("dict", "dual", "compare"),
        ("list", "ir", "convert"),
        ("bool", "ir_canary", "compare"),
        ("any", "ir_canary", "compare"),
    ],
)
def test_deleted_global_builtin_falls_back_to_bound_interpreter(
    h, monkeypatch, name, mode, trigger
):
    h.mode = mode

    def forbidden(*args, **kwargs):
        pytest.fail("deleted shadow must not be used")

    monkeypatch.setattr(module, name, forbidden, raising=False)
    h.hooks[trigger] = lambda *args: monkeypatch.delattr(module, name)
    assert run(h)["freeze_mode"] == mode


@pytest.mark.parametrize(
    "name,mode", [("logger", "dual"), ("_compare_freeze_results", "dual")]
)
def test_deleting_nonbuiltin_global_after_ir_raises_nameerror(
    h, monkeypatch, name, mode
):
    h.mode = mode
    h.hooks["ir"] = lambda *args: monkeypatch.delattr(module, name)
    with pytest.raises(NameError, match=name):
        run(h)


def test_comparator_and_logger_are_looked_up_after_ir_callback(h, monkeypatch):
    h.mode = "dual"
    original_logger = module.logger
    logs = []

    def comparator(*args):
        observe(h, "late_compare", *args)
        return h.diagnostics

    def replace(*args):
        monkeypatch.setattr(module, "_compare_freeze_results", comparator)
        monkeypatch.setattr(
            module,
            "logger",
            type(
                "Logger",
                (),
                {
                    "info": staticmethod(lambda *args: logs.append(args)),
                    "warning": original_logger.warning,
                },
            )(),
        )

    h.hooks["ir"] = replace
    result = run(h)
    assert result["freeze_dual_diagnostics"] is h.diagnostics
    assert h.calls["late_compare"][0][0][0] is h.legacy
    assert h.calls["late_compare"][0][0][1] is h.ir
    assert len(logs) == 11
    assert "compare" not in h.events
    assert "info" not in h.events


def test_ir_getter_order_and_repeated_warning_reads(h):
    run(h)
    reads = [name for name in h.events if ".get:" in name]
    assert reads == [
        "legacy.get:frozen_option_registry",
        "ir.get:frozen_option_registry",
        "ir.get:frozen_structures",
        "ir.get:freeze_checksum",
        "ir.get:warnings",
        "legacy.get:warnings",
        "ir.get:warnings",
    ]


def test_legacy_registry_captured_before_ir_but_contents_are_live(h):
    h.mode = "dual"
    original_registry = h.legacy_registry
    replacement = {"new": object()}

    def mutate(*args):
        h.legacy["frozen_option_registry"] = replacement
        original_registry["late"] = object()

    h.hooks["ir"] = mutate
    result = run(h)
    assert h.calls["compare"][0][0][2] is original_registry
    assert "late" in original_registry
    assert result["frozen_option_registry"] is replacement


def test_ir_warning_reads_remain_separate_live_lookups(h):
    first, second = ["first"], ["second"]
    seen = []
    h.ir["warnings"] = first

    def replace_on_second(*args):
        seen.append(True)
        if len(seen) == 2:
            h.ir["warnings"] = second

    h.hooks["ir.get:warnings"] = replace_on_second
    result = run(h)
    assert result["freeze_ir_warnings"] is first
    assert result["warnings"] == ["legacy", "shared", "second"]


def test_canary_checker_remains_initial_import_capture(h, monkeypatch):
    h.mode = "ir_canary"
    seen = []

    def replacement(**kwargs):
        seen.append(kwargs)
        return True, ["replacement-checker"]

    h.hooks["compare"] = lambda *args: monkeypatch.setattr(
        ocr_canary, "check_ir_canary_failover", replacement
    )
    result = run(h)
    assert ocr_canary.check_ir_canary_failover is replacement
    assert seen == []
    assert result["freeze_canary_fallback"] is False
    assert h.events.count("failover") == 1
    assert h.events.count("import:check_ir_canary_failover") == 1
    assert h.events.index("import:check_ir_canary_failover") < h.events.index("compare")
    assert h.events.index("compare") < h.events.index("failover")


def test_list_callable_binds_before_warning_getters(h, monkeypatch):
    seen = []

    def replacement(value):
        seen.append(value)
        return ["replacement-list"]

    h.hooks["legacy.get:warnings"] = lambda *args: monkeypatch.setattr(
        module, "list", replacement, raising=False
    )
    result = run(h)
    assert module.list is replacement
    assert result["warnings"] == ["legacy", "shared", "ir"]
    assert seen == []
