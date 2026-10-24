"""Pure merge and fingerprint helpers for practice question selection.

Extracted from practice_service.py to keep the main service focused on
DB orchestration. These functions operate on plain lists/dicts with no
side effects or DB access.
"""

from __future__ import annotations

import hashlib
import json
import random

from app.services.practice.normalization import normalize_practice_request_id


def round_robin_merge(
    buckets: list[list[object]],
    count: int,
    randomize_order: bool = False,
) -> list[object]:
    """Round-robin merge multiple buckets for balanced output.

    Each bucket is already ordered; output interleaves across buckets.
    Deduplicates by item id (or object identity).
    """
    if count <= 0 or not buckets:
        return []

    non_empty = [b for b in buckets if b]
    if not non_empty:
        return []

    if randomize_order:
        random.shuffle(non_empty)

    result: list[object] = []
    seen: set[int] = set()
    max_len = max(len(b) for b in non_empty)

    for i in range(max_len):
        for bucket in non_empty:
            if i < len(bucket):
                item = bucket[i]
                item_id = id(item)
                if hasattr(item, "id"):
                    item_id = item.id
                if item_id not in seen:
                    result.append(item)
                    seen.add(item_id)
                    if len(result) >= count:
                        return result
    return result


def round_robin_merge_with_metadata(
    buckets: list[list[tuple[object, dict]]],
    count: int,
    randomize_order: bool = False,
) -> tuple[list[object], dict[int, dict]]:
    """Round-robin merge with per-item metadata (smart mode).

    Each bucket element is (question, metadata_dict).
    Returns (merged_questions, {question_id: metadata_dict}).
    """
    merged: list[object] = []
    metadata: dict[int, dict] = {}

    if count <= 0 or not buckets:
        return merged, metadata

    non_empty = [b for b in buckets if b]
    if not non_empty:
        return merged, metadata

    if randomize_order:
        random.shuffle(non_empty)

    seen_ids: set[int] = set()
    max_len = max(len(b) for b in non_empty)

    for i in range(max_len):
        for bucket in non_empty:
            if i < len(bucket):
                item, meta = bucket[i]
                item_id = item.id if hasattr(item, "id") else id(item)
                if item_id not in seen_ids:
                    merged.append(item)
                    metadata[item_id] = meta
                    seen_ids.add(item_id)
                    if len(merged) >= count:
                        return merged, metadata
    return merged, metadata


def build_fallback_metadata(reason: str, strategy: str) -> dict:
    """Build a random/repeat-window fallback metadata entry."""
    return {
        "recommend_score": None,
        "recommend_reason": reason,
        "strategy": strategy,
        "similarity": None,
    }


def extract_graph_context(graph_context: dict) -> tuple[dict, dict, dict]:
    """Unpack graph context fields with empty defaults."""
    return (
        graph_context.get("blocked_targets", {}),
        graph_context.get("prerequisite_candidates", {}),
        graph_context.get("prerequisites_by_target", {}),
    )


def practice_submission_fingerprint(
    *,
    answers: list[dict],
    skipped_question_ids: list[int],
    session_meta: dict,
    batch_token: str,
) -> str:
    """Hash the exact immutable submission represented by one request_id."""
    normalized_answers = []
    for answer in answers:
        normalized_answers.append(
            {
                "question_id": int(answer.get("question_id")),
                "user_answer": str(
                    answer.get("user_answer", answer.get("answer", "")) or ""
                ).strip(),
                "used_time": (
                    None
                    if answer.get("used_time") is None
                    else int(answer.get("used_time"))
                ),
                "request_id": normalize_practice_request_id(answer.get("request_id")),
            }
        )
    normalized_answers.sort(key=lambda item: item["question_id"])
    payload = {
        "v": 3,
        "answers": normalized_answers,
        "skipped_question_ids": sorted(int(qid) for qid in skipped_question_ids),
        "session": {
            "request_id": normalize_practice_request_id(session_meta.get("request_id")),
            "subject_id": int(session_meta.get("subject_id")),
            "mode": str(session_meta.get("mode") or "random"),
            "started_at": str(session_meta.get("started_at") or ""),
            "finished_at": str(session_meta.get("finished_at") or ""),
            "duration_sec": int(session_meta.get("duration_sec") or 0),
            "question_count": int(session_meta.get("question_count") or 0),
            "answered_count": int(session_meta.get("answered_count") or 0),
        },
        "batch_token": str(batch_token),
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
