"""Pure canonical/alias resolution policy for knowledge points.

This module deliberately has no database/ORM imports so the matching policy can be
unit-tested without bootstrapping the application database driver.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

_FULLWIDTH_MAP = {
    "（": "(",
    "）": ")",
    "【": "[",
    "】": "]",
    "｛": "{",
    "｝": "}",
    "，": ",",
    "。": ".",
    "；": ";",
    "：": ":",
    "！": "!",
    "？": "?",
    "＋": "+",
    "－": "-",
    "＊": "*",
    "／": "/",
    "＝": "=",
    "＜": "<",
    "＞": ">",
    "０": "0",
    "１": "1",
    "２": "2",
    "３": "3",
    "４": "4",
    "５": "5",
    "６": "6",
    "７": "7",
    "８": "8",
    "９": "9",
}


class KnowledgePointResolutionError(ValueError):
    """Raised when a term is ambiguous or would recreate retired knowledge data."""


def normalize_knowledge_name(name: str) -> str:
    """Normalize display/alias text for exact canonical matching."""
    if not name:
        return ""
    text = "".join(_FULLWIDTH_MAP.get(ch, ch) for ch in str(name))
    text = unicodedata.normalize("NFKC", text).strip()
    text = re.sub(r"\s+", " ", text)
    return text.lower()


def normalize_kp_input(kp_names) -> list[tuple[str, str]]:
    """Trim/normalize/deduplicate raw input while preserving first occurrence."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in kp_names or []:
        if raw is None:
            continue
        display = str(raw).strip()
        if not display:
            continue
        normalized = normalize_knowledge_name(display)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append((display, normalized))
    return out


def alias_values(point) -> list[str]:
    """Return aliases from JSON/list legacy representations defensively."""
    raw = getattr(point, "aliases", None)
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            decoded = [raw]
        raw = decoded
    if not isinstance(raw, (list, tuple, set)):
        return []
    out: list[str] = []
    for value in raw:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            out.append(text)
    return out


def build_resolution_indexes(
    points,
) -> tuple[dict[str, object], dict[str, list[object]], set[str]]:
    """Build canonical-name, active-alias and inactive-tombstone indexes.

    A subject may legitimately contain several active nodes sharing one
    ``normalized_name``: the 408 syllabus reuses a title for a chapter/section and
    its child (e.g. ``第4章 指令系统`` and ``4.1 指令系统`` both display as ``指令系统``).
    Node identity is the id, so rather than rejecting such a catalog we pick one
    canonical per name deterministically — the node that also lists the term among
    its own aliases wins, otherwise the lowest id.
    """
    active_name_candidates: dict[str, list[tuple[Any, set[str]]]] = defaultdict(list)
    active_aliases: dict[str, list[object]] = defaultdict(list)
    inactive_terms: set[str] = set()

    for point in points:
        name_norm = normalize_knowledge_name(
            getattr(point, "normalized_name", None) or getattr(point, "name", "")
        )
        aliases: set[str] = set()
        for alias in alias_values(point):
            alias_norm = normalize_knowledge_name(alias)
            if alias_norm:
                aliases.add(alias_norm)

        if bool(getattr(point, "is_active", False)):
            if name_norm:
                active_name_candidates[name_norm].append((point, aliases))
            for alias_norm in aliases:
                bucket = active_aliases[alias_norm]
                if all(int(item.id) != int(point.id) for item in bucket):
                    bucket.append(point)
        else:
            if name_norm:
                inactive_terms.add(name_norm)
            inactive_terms.update(aliases)

    active_names: dict[str, object] = {}
    for name_norm, candidates in active_name_candidates.items():
        if len(candidates) == 1:
            active_names[name_norm] = candidates[0][0]
            continue
        winner = min(
            candidates,
            key=lambda item: (name_norm not in item[1], int(item[0].id)),
        )[0]
        active_names[name_norm] = winner
        logger.warning(
            "重复 active normalized_name=%r: ids=%s，解析选用 id=%s",
            name_norm,
            sorted(int(p.id) for p, _aliases in candidates),
            int(winner.id),
        )

    return active_names, dict(active_aliases), inactive_terms


def resolve_from_indexes(
    normalized: str,
    active_names: dict[str, object],
    active_aliases: dict[str, list[object]],
    inactive_terms: set[str],
    *,
    block_inactive: bool,
):
    """Resolve one normalized term; active canonical name always outranks alias."""
    exact = active_names.get(normalized)
    if exact is not None:
        return exact

    alias_matches = active_aliases.get(normalized, [])
    if len(alias_matches) == 1:
        return alias_matches[0]
    if len(alias_matches) > 1:
        ids = sorted(int(item.id) for item in alias_matches)
        raise KnowledgePointResolutionError(
            f"知识点 alias={normalized!r} 同时命中多个 active canonical: {ids}"
        )

    if block_inactive and normalized in inactive_terms:
        raise KnowledgePointResolutionError(
            f"知识点 {normalized!r} 命中 inactive 历史节点，但未找到唯一 active canonical；"
            "请先完成 alias/canonical 治理，禁止重新创建重复知识点"
        )
    return None
