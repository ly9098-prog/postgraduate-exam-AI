"""Capture region origins at construction; publish only verifiable input views."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def block_snapshot(block: dict) -> dict | None:
    page, index = block.get("page", 1), block.get("block_index", 0)
    text = block.get("normalized_text", "")
    if (
        type(page) is not int
        or type(index) is not int
        or page < 1
        or index < 0
        or not isinstance(text, str)
    ):
        return None
    return {
        "page": page,
        "block_index": index,
        "text_digest": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def begin_source_capture(document: Any, blocks: list[dict]) -> None:
    """Keep transient identity lookup out of DocumentIR's serialized schema."""
    sources = [block_snapshot(block) for block in blocks]
    coordinates = [
        (source["page"], source["block_index"]) for source in sources if source is not None
    ]
    document._freeze_source_capture = {
        "generation": document.document_id,
        "sources": sources,
        "indices": {id(block): index for index, block in enumerate(blocks)},
        "regions": [],
        "valid": (
            all(source is not None for source in sources)
            and len(set(coordinates)) == len(blocks)
            and len({id(block) for block in blocks}) == len(blocks)
        ),
    }


def _region_snapshot(page_index: int, region: Any) -> dict:
    return {
        "page_index": page_index,
        "region_id": region.region_id,
        "revision": region.revision,
        "text_digest": hashlib.sha256(
            "\n".join(line.text for line in region.lines).encode("utf-8")
        ).hexdigest(),
    }


def record_region_source(document: Any, block: dict, page_index: int, region: Any) -> None:
    capture = document._freeze_source_capture
    capture["regions"].append(
        {
            "source_index": capture["indices"][id(block)],
            "region": _region_snapshot(page_index, region),
        }
    )


def finish_source_capture(document: Any) -> None:
    """Object identities are only needed while the builder holds the input list."""
    document._freeze_source_capture.pop("indices")


def _option_snapshots(registry: Mapping, region_ids: list[str]) -> dict | None:
    known_regions = set(region_ids)
    if not isinstance(registry, Mapping) or any(key not in known_regions for key in registry):
        return None
    snapshots = {}
    for region, options in registry.items():
        if not isinstance(options, Mapping) or not all(
            key in {"A", "B", "C", "D"} and isinstance(value, str) and bool(value)
            for key, value in options.items()
        ):
            return None
        snapshots[region] = dict(options)
    return snapshots


def binding_checksum(plan: dict) -> str:
    payload = {key: value for key, value in plan.items() if key != "checksum"}
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def source_binding_fields(document: Any, registry: Mapping) -> dict:
    """Return a JSON-safe plan; restored or transformed IR needs a new capture."""
    capture = getattr(document, "_freeze_source_capture", None)
    if not isinstance(capture, dict) or not capture.get("valid"):
        return {}
    regions = capture["regions"]
    current = [
        _region_snapshot(page.page_index, region)
        for page in document.pages
        for region in page.regions
    ]
    recorded = [item["region"] for item in regions]
    ids = [item["region_id"] for item in current]
    if (
        current != recorded
        or len(set(ids)) != len(ids)
        or len(regions) != len(capture["sources"])
        or document.document_id != capture["generation"]
    ):
        return {}
    options = _option_snapshots(registry, ids)
    if options is None:
        return {}
    plan = {
        "version": 1,
        "generation": capture["generation"],
        "sources": [dict(source) for source in capture["sources"]],
        "regions": [
            {
                "region_id": item["region"]["region_id"],
                "source_index": item["source_index"],
                "options": options.get(item["region"]["region_id"], {}),
            }
            for item in regions
        ],
    }
    plan["checksum"] = binding_checksum(plan)
    return {"freeze_block_binding": plan}


def legacy_source_binding_fields(document: Any, registry: Mapping) -> dict:
    """Bind a selected legacy fallback only through recorded source coordinates."""
    capture = getattr(document, "_freeze_source_capture", None)
    if not isinstance(capture, dict) or not capture.get("valid"):
        return {}
    coordinates = {}
    for item in capture["regions"]:
        source = capture["sources"][item["source_index"]]
        coordinates[f"{source['page']}:{source['block_index']}"] = item["region"]["region_id"]
    if not isinstance(registry, Mapping) or any(key not in coordinates for key in registry):
        return {}
    by_region = {coordinates[key]: value for key, value in registry.items()}
    return source_binding_fields(document, by_region)


def bind_legacy_result(document: Any, result: dict) -> dict:
    if getattr(document, "_freeze_source_capture", None) is None:
        return result
    fields = legacy_source_binding_fields(document, result.get("frozen_option_registry", {}))
    if fields:
        result.update(fields)
    return result
