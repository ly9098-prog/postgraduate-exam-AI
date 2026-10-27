"""Resolve captured IR options against the splitter's actual question intervals."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Mapping

from app.features.freeze_source_binding import binding_checksum, block_snapshot


def reject_binding(binding: dict, reason: str) -> dict:
    reasons = binding.setdefault("diagnostics", {}).setdefault("reasons", [])
    if reason not in reasons:
        reasons.append(reason)
    return {}


def _source_options(binding: dict, blocks: list[dict]) -> dict | None:
    plan = binding.get("plan")
    if not isinstance(plan, dict):
        reject_binding(binding, "missing_source_binding")
        return None
    if not _valid_plan_envelope(plan):
        reject_binding(binding, "invalid_source_binding")
        return None
    snapshots = [block_snapshot(block) for block in blocks]
    if None in snapshots or plan.get("sources") != snapshots:
        reject_binding(binding, "input_view_changed")
        return None
    if not isinstance(plan.get("generation"), str) or not plan["generation"]:
        reject_binding(binding, "invalid_source_binding")
        return None
    regions = plan.get("regions")
    if not isinstance(regions, list) or len(regions) != len(blocks):
        reject_binding(binding, "invalid_source_binding")
        return None
    sources = _region_sources(regions, len(blocks))
    if sources is None:
        reject_binding(binding, "invalid_source_binding")
        return None
    result = {}
    for entry in regions:
        options = entry.get("options")
        if not isinstance(options, Mapping) or (options and not _valid_options(options)):
            reject_binding(binding, "invalid_frozen_options")
            return None
        if options:
            result[sources[entry["region_id"]]] = dict(options)
    return result


def _valid_plan_envelope(plan: dict) -> bool:
    if set(plan) != {"version", "generation", "sources", "regions", "checksum"}:
        return False
    if type(plan["version"]) is not int or plan["version"] != 1:
        return False
    try:
        return isinstance(plan["checksum"], str) and plan["checksum"] == binding_checksum(plan)
    except (TypeError, ValueError, OverflowError, RecursionError):
        return False


def _region_sources(regions: list, count: int) -> dict | None:
    result, indices = {}, set()
    for entry in regions:
        if not isinstance(entry, dict):
            return None
        region, index = entry.get("region_id"), entry.get("source_index")
        if (
            not isinstance(region, str)
            or not region
            or region in result
            or type(index) is not int
            or not 0 <= index < count
            or index in indices
        ):
            return None
        result[region] = index
        indices.add(index)
    return result


def _valid_options(options: object) -> bool:
    return (
        isinstance(options, Mapping)
        and bool(options)
        and all(
            key in {"A", "B", "C", "D"} and isinstance(value, str) and bool(value)
            for key, value in options.items()
        )
    )


def _source_spans(blocks: list[dict], page_map: list[tuple]) -> list[tuple] | None:
    by_coordinate = {}
    for index, block in enumerate(blocks):
        coordinate = (block.get("page", 1), block.get("block_index", 0))
        if coordinate in by_coordinate:
            return None
        by_coordinate[coordinate] = (index, block.get("normalized_text", ""))
    spans = []
    for offset, page, block_index in page_map:
        index, text = by_coordinate[(page, block_index)]
        start = offset + len(text) - len(text.lstrip())
        end = offset + len(text.rstrip())
        if start < end:
            spans.append((index, start, end))
    return spans


def _question_sources(spans: list[tuple], boundaries: list[tuple], end: int) -> tuple:
    starts = [position for _, position in boundaries]
    touched = {position: [] for position in starts}
    owners, unsafe = {}, set()
    for source, start, stop in spans:
        first = bisect_right(starts, start) - 1
        owner = starts[first] if first >= 0 else None
        limit = starts[first + 1] if first + 1 < len(starts) else end
        if owner is None or stop > limit:
            owner = None
        owners[source] = owner
        for index in range(max(0, first), bisect_left(starts, stop)):
            question = starts[index]
            touched[question].append(source)
            if owner != question:
                unsafe.add(question)
    return touched, owners, unsafe


def _merge_question_options(sources: list[int], options: dict) -> dict | None:
    merged = {}
    for source in sources:
        for key, value in options.get(source, {}).items():
            if key in merged and merged[key] != value:
                return None
            merged[key] = value
    return merged


def resolve_question_bindings(
    binding: dict,
    blocks: list[dict],
    page_map: list[tuple],
    boundaries: list[tuple],
    full_text: str,
) -> dict:
    if binding.get("input_transformed"):
        return reject_binding(binding, "split_input_transformed")
    options = _source_options(binding, blocks)
    if options is None:
        return {}
    included = {(page, index) for _, page, index in page_map}
    original_text = "\n".join(
        block.get("normalized_text", "")
        for block in blocks
        if (block.get("page", 1), block.get("block_index", 0)) in included
    )
    if original_text != full_text:
        return reject_binding(binding, "split_text_transformed")
    spans = _source_spans(blocks, page_map)
    if spans is None:
        return reject_binding(binding, "duplicate_block_coordinate")
    touched, _, unsafe = _question_sources(spans, boundaries, len(full_text))
    resolved = {}
    for question, sources in touched.items():
        if question in unsafe:
            reject_binding(binding, "source_spans_questions")
            continue
        merged = _merge_question_options(sources, options)
        if merged is None:
            reject_binding(binding, "conflicting_frozen_options")
        elif merged:
            resolved[question] = merged
    return resolved


def question_bound_options(binding: dict, resolved: dict, start: int, *, grouped: bool) -> dict:
    options = resolved.get(start, {})
    if grouped and options:
        return reject_binding(binding, "grouped_options")
    if options:
        diagnostics = binding.setdefault("diagnostics", {})
        diagnostics["accepted_questions"] = diagnostics.get("accepted_questions", 0) + 1
    return dict(options)
