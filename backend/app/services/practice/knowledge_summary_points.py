"""Pure baseline decoding, per-point evidence counts and ranked projection."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any


def _state_status(state: Any) -> str:
    if state is None or int(state.attempt_count or 0) <= 0:
        return "no_data"
    confidence = float(state.confidence or 0.0)
    if confidence < 0.25 or state.mastery_score is None:
        return "insufficient"
    mastery = float(state.mastery_score)
    if mastery < 60:
        return "weak"
    if mastery < 80:
        return "developing"
    if mastery < 90:
        return "good"
    return "mastered"


def record_revision_ids(records: list) -> list[int]:
    return [
        int(record.question_version_id)
        for record in records
        if record.question_version_id
    ]


def add_revision_points(rows: list, revision_points: dict, names: dict) -> None:
    for revision_id, kp_id, name in rows:
        revision_points[int(revision_id)].add(int(kp_id))
        names[int(kp_id)] = str(name)


def response_record_ids(response: dict) -> list[int]:
    ids = []
    for item in response.get("results") or []:
        if not isinstance(item, dict):
            continue
        record_id = int(item.get("record_id") or 0)
        if record_id > 0:
            ids.append(record_id)
    return list(dict.fromkeys(ids))


def session_baselines(knowledge_session: dict) -> tuple[dict, dict]:
    baseline = (
        knowledge_session.get("_baseline")
        if isinstance(knowledge_session.get("_baseline"), dict)
        else {}
    )
    return baseline, point_baselines(baseline)


def point_baselines(baseline: dict) -> dict:
    points = {}
    for item in baseline.get("points") or []:
        if not isinstance(item, list) or len(item) < 4:
            continue
        kp_id = int(item[0] or 0)
        if kp_id > 0:
            points[kp_id] = {
                "mastery": item[1],
                "confidence": item[2],
                "attempt_count": int(item[3] or 0),
            }
    return points


def point_statistics(records: list, revision_points: dict) -> dict:
    stats = defaultdict(
        lambda: {"question_count": 0, "correct_count": 0, "wrong_count": 0}
    )
    for record in records:
        for kp_id in revision_points.get(int(record.question_version_id), set()):
            stats[kp_id]["question_count"] += 1
            if bool(record.is_correct):
                stats[kp_id]["correct_count"] += 1
            else:
                stats[kp_id]["wrong_count"] += 1
    return stats


def project_points(
    touched_ids: list[int],
    states: dict,
    baselines: dict,
    names: dict,
    stats: dict,
    *,
    number: Callable,
    delta: Callable,
    status: Callable,
) -> list[dict]:
    points = []
    for kp_id in touched_ids:
        current = states.get(kp_id)
        before = baselines.get(kp_id) or {}
        after_mastery = (
            round(float(current.mastery_score), 1)
            if current is not None
            and int(current.attempt_count or 0) > 0
            and current.mastery_score is not None
            else None
        )
        before_mastery = number(before.get("mastery"))
        point_stats = stats[kp_id]
        points.append(
            {
                "knowledge_point_id": kp_id,
                "name": names.get(kp_id) or f"知识点 {kp_id}",
                **point_stats,
                "mastery_before": before_mastery,
                "mastery_after": after_mastery,
                "mastery_delta": delta(before_mastery, after_mastery),
                "confidence_after": round(float(current.confidence or 0.0), 3)
                if current is not None
                else 0.0,
                "status_after": status(current),
            }
        )
    return points


def rank_points(points: list[dict], limit: int) -> list[dict]:
    status_rank = {
        "weak": 0,
        "insufficient": 1,
        "no_data": 2,
        "developing": 3,
        "good": 4,
        "mastered": 5,
    }
    points.sort(
        key=lambda item: (
            status_rank.get(str(item.get("status_after")), 9),
            -(int(item.get("wrong_count") or 0)),
            -abs(float(item.get("mastery_delta") or 0.0)),
            int(item["knowledge_point_id"]),
        )
    )
    return points[:limit]
