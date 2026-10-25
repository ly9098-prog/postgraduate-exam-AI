"""Pure helpers for knowledge-hierarchy chapter practice selection."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable


BUCKET_RANK = {"weak": 0, "unobserved": 1, "developing": 2, "stable": 3}
BUCKET_ORDER = ("weak", "unobserved", "developing", "stable")


def knowledge_bucket(state) -> str:
    """Map a user knowledge state to the chapter-practice priority bucket."""
    if state is None or int(state.attempt_count or 0) <= 0:
        return "unobserved"
    confidence = float(state.confidence or 0.0)
    if confidence < 0.30:
        return "unobserved"
    mastery = float(state.mastery_score if state.mastery_score is not None else 50.0)
    if mastery < 40.0:
        return "weak"
    if mastery < 85.0:
        return "developing"
    return "stable"


def bucket_targets(count: int) -> dict[str, int]:
    """Target roughly 40/30/20/10 weak/unobserved/developing/stable."""
    count = max(0, int(count))
    order = ("weak", "unobserved", "developing", "stable")
    ratios = {"weak": 0.40, "unobserved": 0.30, "developing": 0.20, "stable": 0.10}
    targets = {name: int(count * ratios[name]) for name in order}
    remainder = count - sum(targets.values())
    for name in order:
        if remainder <= 0:
            break
        targets[name] += 1
        remainder -= 1
    return targets


def build_question_buckets(
    questions: Iterable[object],
    q_to_kps: dict[int, list[int]],
    states: dict[int, object],
) -> dict[str, list[object]]:
    """Assign each question once to its highest-priority knowledge bucket."""
    buckets: dict[str, list[object]] = {name: [] for name in BUCKET_RANK}
    for question in questions:
        kp_ids = q_to_kps.get(int(question.id), [])
        labels = [knowledge_bucket(states.get(kp_id)) for kp_id in kp_ids]
        bucket = (
            min(labels, key=lambda name: BUCKET_RANK[name]) if labels else "unobserved"
        )
        buckets[bucket].append(question)
    return buckets


def select_bucket_questions(
    buckets: dict[str, list[object]],
    count: int,
) -> list[object]:
    """Take the target mix first, then fill sparse buckets in priority order."""
    targets = bucket_targets(count)
    selected: list[object] = []
    selected_ids: set[int] = set()
    for bucket in BUCKET_ORDER:
        for question in buckets[bucket][: targets[bucket]]:
            _append_unique(selected, selected_ids, question)

    if len(selected) < count:
        for bucket in BUCKET_ORDER:
            for question in buckets[bucket]:
                _append_unique(selected, selected_ids, question)
                if len(selected) >= count:
                    break
            if len(selected) >= count:
                break
    return selected[:count]


def question_knowledge_mapping(rows: Iterable[object]) -> dict[int, list[int]]:
    mapping: dict[int, list[int]] = defaultdict(list)
    for question_id, kp_id in rows:
        mapping[int(question_id)].append(int(kp_id))
    return mapping


def _append_unique(
    selected: list[object], selected_ids: set[int], question: object
) -> None:
    question_id = int(question.id)
    if question_id in selected_ids:
        return
    selected.append(question)
    selected_ids.add(question_id)
