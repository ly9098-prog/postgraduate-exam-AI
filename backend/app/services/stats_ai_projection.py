"""Normalize learning-AI provider payloads without provider or database IO."""

from __future__ import annotations

import json


def extract_json_object(content: object) -> dict | None:
    """Extract one JSON object without attempting lossy repair."""
    text_value = str(content or "").strip()
    if not text_value:
        return None
    if text_value.startswith("```"):
        first_newline = text_value.find("\n")
        if first_newline >= 0:
            text_value = text_value[first_newline + 1 :]
        if text_value.endswith("```"):
            text_value = text_value[:-3].rstrip()
    left = text_value.find("{")
    right = text_value.rfind("}")
    if left >= 0 and right > left:
        text_value = text_value[left : right + 1]
    try:
        parsed = json.loads(text_value)
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def normalize_text_list(
    value: object, *, limit: int, max_chars: int = 240
) -> list[str]:
    """Keep only bounded non-empty strings from a provider text array."""
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        text_value = item.strip()
        if not text_value:
            continue
        result.append(text_value[:max_chars])
        if len(result) >= limit:
            break
    return result


def normalize_dashboard_actions(value: object, *, limit: int = 4) -> list[dict]:
    """Keep only bounded, typed action objects for the dashboard UI."""
    action_types = frozenset({"review", "wrong", "practice", "subject"})
    if not isinstance(value, list):
        return []
    result: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        action_type = str(item.get("type") or "").strip().lower()
        if action_type not in action_types:
            continue
        raw_title = item.get("title")
        raw_desc = item.get("desc")
        title = raw_title.strip() if isinstance(raw_title, str) else ""
        desc = raw_desc.strip() if isinstance(raw_desc, str) else ""
        if not title:
            continue
        result.append(
            {
                "type": action_type,
                "title": title[:80],
                "desc": desc[:220],
            }
        )
        if len(result) >= limit:
            break
    return result


def normalize_knowledge_points(value: object, *, limit: int) -> list[dict]:
    """Normalize provider knowledge-point objects and clamp accuracy."""
    if not isinstance(value, list):
        return []
    normalized: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        raw_name = item.get("knowledge_point")
        raw_suggestion = item.get("suggestion")
        if not isinstance(raw_name, str):
            continue
        name = raw_name.strip()
        suggestion = raw_suggestion.strip() if isinstance(raw_suggestion, str) else ""
        if not name:
            continue
        try:
            score = float(item.get("accuracy", 0) or 0)
        except (TypeError, ValueError):
            score = 0.0
        if score > 1:
            score = score / 100.0
        score = max(0.0, min(1.0, score))
        normalized.append(
            {
                "knowledge_point": name[:80],
                "accuracy": round(score, 4),
                "suggestion": suggestion[:240],
            }
        )
        if len(normalized) >= limit:
            break
    return normalized
