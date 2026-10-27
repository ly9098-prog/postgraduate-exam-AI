"""Synthetic ports for the actual synchronous structure-freeze entry.

Run from an empty temporary cwd with synthetic settings to avoid repository .env.
All global, import, and attribute substitutions belong to pytest's monkeypatch.
"""

import builtins
from types import SimpleNamespace

from app.features import ocr_canary
from app.features import pipeline_orchestrator as module
from app.features.pipeline_stages import structure_freeze_stage as stage


def observe(h, name, *args, **kwargs):
    h.events.append(name)
    h.calls.setdefault(name, []).append((args, kwargs))
    if name in h.hooks:
        h.hooks[name](*args, **kwargs)


class ReadMap(dict):
    """Expose get timing without changing dict copying or item identity."""

    def __init__(self, h, label, values):
        super().__init__(values)
        self.h = h
        self.label = label

    def get(self, key, default=None):
        observe(self.h, f"{self.label}.get:{key}", key, default)
        return super().get(key, default)


def fail_at(h, name, error):
    def fail(*args, **kwargs):
        raise error

    h.hooks[name] = fail


def install_ports(monkeypatch, h):
    def port(name, value):
        def call(*args, **kwargs):
            observe(h, name, *args, **kwargs)
            return getattr(h, value)

        return call

    for name, attr, value in (
        ("mode", "_get_structure_freeze_mode", "mode"),
        ("legacy", "run_structure_freeze_stage", "legacy"),
        ("document", "_get_blocks_document_ir", "document"),
        ("compare", "_compare_freeze_results", "diagnostics"),
    ):
        monkeypatch.setattr(module, attr, port(name, value))
    for name, attr, value in (
        ("ir", "freeze_from_document_ir", "ir"),
        ("convert", "freeze_registry_to_block_format", "converted"),
        ("deepfreeze", "_freeze_deep_freeze", "frozen"),
    ):
        monkeypatch.setattr(stage, attr, port(name, value))
    for name, attr, value in (
        ("global_switch", "is_canary_globally_disabled", "global_disabled"),
        ("ir_switch", "is_ir_canary_disabled", "ir_disabled"),
        ("failover", "check_ir_canary_failover", "failover"),
    ):
        monkeypatch.setattr(ocr_canary, attr, port(name, value))
    logger = SimpleNamespace(
        info=port("info", "unused"), warning=port("warning", "unused")
    )
    monkeypatch.setattr(module, "logger", logger)


def install_import_trace(monkeypatch, h):
    original = builtins.__import__

    def importing(name, globals=None, locals=None, fromlist=(), level=0):
        if name in {
            "app.features.pipeline_stages.structure_freeze_stage",
            "app.features.ocr_canary",
        }:
            for item in fromlist:
                observe(h, f"import:{item}")
        return original(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", importing)


def make_harness(monkeypatch, mode="ir"):
    h = SimpleNamespace(
        mode=mode,
        events=[],
        calls={},
        hooks={},
        blocks=[{"text": object()}],
        document=object(),
        converted=object(),
        frozen=object(),
        checksum=object(),
        unused=None,
        global_disabled=False,
        ir_disabled=False,
        reasons=["synthetic-reason"],
        legacy_registry={"legacy": object()},
        raw={"ir": [object()]},
        structures=[object()],
        legacy_structures=[object()],
        ir_warnings=["shared", "ir", "ir"],
        legacy_warnings=["legacy", "shared", "legacy"],
        extra={"nested": object()},
    )
    h.failover = (False, h.reasons)
    make_results(h)
    install_ports(monkeypatch, h)
    install_import_trace(monkeypatch, h)
    return h


def make_results(h):
    h.legacy = ReadMap(
        h,
        "legacy",
        {
            "frozen_option_registry": h.legacy_registry,
            "frozen_structures": h.legacy_structures,
            "warnings": h.legacy_warnings,
            "extra": h.extra,
        },
    )
    h.ir = ReadMap(
        h,
        "ir",
        {
            "frozen_option_registry": h.raw,
            "frozen_structures": h.structures,
            "warnings": h.ir_warnings,
            "freeze_checksum": h.checksum,
        },
    )
    h.diagnostics = {
        "legacy_option_count": 2,
        "ir_option_count": 3,
        "option_key_match": True,
        "option_text_match": False,
        "binding_lost_count": 4,
        "differences_count": 12,
        "differences": [
            {
                "type": f"diff-{i}",
                "option_key": f"key-{i}",
                "legacy_text": f"old-{i}",
                "ir_text": f"new-{i}",
            }
            for i in range(12)
        ],
    }


def run(h, **kwargs):
    return module.ImportPipeline._run_structure_freeze(object(), h.blocks, **kwargs)


def assert_compare(h):
    assert h.events.count("compare") == 1
    args, kwargs = h.calls["compare"][0]
    assert kwargs == {}
    for actual, expected in zip(
        args, (h.legacy, h.ir, h.legacy_registry, h.raw), strict=True
    ):
        assert actual is expected


def assert_ir_result(h, result):
    assert result["frozen_option_registry"] is h.frozen
    assert result["frozen_option_registry_ir"] is h.raw
    assert result["frozen_structures"] is h.structures
    assert result["freeze_checksum"] is h.checksum
    assert result["freeze_ir_warnings"] is h.ir_warnings
    assert result["warnings"] == ["legacy", "shared", "ir"]
    assert result["warnings"] is not h.legacy_warnings
    assert result["warnings"] is not h.ir_warnings
    assert h.calls["convert"] == [((h.raw,), {})]
    assert h.calls["convert"][0][0][0] is h.raw
    assert h.calls["deepfreeze"] == [((h.converted,), {})]
    assert h.calls["deepfreeze"][0][0][0] is h.converted


def force_unbound_converter_path(monkeypatch, h, source):
    h.mode = "ir_canary"
    if source == "missing_document":
        h.document = None
    else:
        fail_at(h, f"import:{source}", ValueError("converter unavailable"))
    values = []

    def populate_registry(value):
        observe(h, "builtin_bool", value)
        values.append(value)
        if isinstance(value, dict) and not value:
            value["callback_populated"] = True
        return bool(value)

    monkeypatch.setattr(module, "bool", populate_registry, raising=False)
    return values


def snapshot_ir_payload(h):
    return SimpleNamespace(
        raw=h.raw,
        keys=tuple(h.raw),
        entries={key: (entries, tuple(entries)) for key, entries in h.raw.items()},
        structures=h.structures,
        structure_items=tuple(h.structures),
    )


def assert_ir_payload_preserved(result, snapshot):
    raw = result["frozen_option_registry_ir"]
    assert raw is snapshot.raw
    assert tuple(raw) == snapshot.keys
    for key, (original_list, original_items) in snapshot.entries.items():
        assert raw[key] is original_list
        assert len(raw[key]) == len(original_items)
        assert all(a is b for a, b in zip(raw[key], original_items, strict=True))
    structures = result["frozen_structures"]
    assert structures is snapshot.structures
    assert len(structures) == len(snapshot.structure_items)
    assert all(
        a is b for a, b in zip(structures, snapshot.structure_items, strict=True)
    )
