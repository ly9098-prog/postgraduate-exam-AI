"""Compare dual freeze output without changing diagnostic ordering."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.features.pipeline_stages.structure_freeze_stage import FrozenOptionEntry


def compare_freeze_results(
    legacy_result: dict,
    ir_result: dict,
    legacy_registry: dict[str, dict[str, str]],
    ir_registry: dict[str, list[FrozenOptionEntry]],
    *,
    ports,
) -> dict:
    legacy_opts: set[tuple[str, str]] = ports("set")()
    for _key, opts in legacy_registry.items():
        for k, v in opts.items():
            legacy_opts.add((k, ports("str")(v).strip()))
    ir_opts: set[tuple[str, str]] = ports("set")()
    for _rid, entries in ir_registry.items():
        for entry in entries:
            ir_opts.add((entry.option_key, entry.original_text.strip()))
    common = legacy_opts & ir_opts
    only_legacy = legacy_opts - ir_opts
    only_ir = ir_opts - legacy_opts
    differences, text_mismatches = _freeze_differences(
        legacy_opts, ir_opts, only_legacy, only_ir, ports
    )
    option_key_match = ports("len")(only_legacy) == 0 and ports("len")(only_ir) == 0
    option_text_match = text_mismatches == 0
    binding_lost_count = 0
    for _rid, entries in ir_registry.items():
        for entry in entries:
            if entry.binding_status == "binding_lost":
                binding_lost_count += 1
    return {
        "freeze_mode": "dual",
        "legacy_option_count": ports("len")(legacy_opts),
        "ir_option_count": ports("len")(ir_opts),
        "common_option_count": ports("len")(common),
        "option_key_match": option_key_match,
        "option_text_match": option_text_match,
        "binding_lost_count": binding_lost_count,
        "differences_count": ports("len")(differences),
        "differences": differences[:50],
        "differences_truncated": ports("max")(0, ports("len")(differences) - 50),
    }


def _freeze_differences(legacy_opts, ir_opts, only_legacy, only_ir, ports):
    differences: list[dict] = []
    for key, text in ports("sorted")(only_legacy):
        differences.append(
            {
                "type": "only_in_legacy",
                "option_key": key,
                "legacy_text": text,
                "ir_text": "",
            }
        )
    for key, text in ports("sorted")(only_ir):
        differences.append(
            {
                "type": "only_in_ir",
                "option_key": key,
                "ir_text": text,
                "legacy_text": "",
            }
        )
    legacy_by_key: dict[str, str] = {}
    for k, v in legacy_opts:
        legacy_by_key.setdefault(k, v)
    ir_by_key: dict[str, str] = {}
    for k, v in ir_opts:
        ir_by_key.setdefault(k, v)
    text_mismatches = 0
    for k in ports("sorted")(
        ports("set")(legacy_by_key.keys()) & ports("set")(ir_by_key.keys())
    ):
        lt = legacy_by_key[k].strip()
        it = ir_by_key[k].strip()
        if lt != it:
            text_mismatches += 1
            differences.append(
                {
                    "type": "text_mismatch",
                    "option_key": k,
                    "legacy_text": lt,
                    "ir_text": it,
                }
            )
    return (differences, text_mismatches)
