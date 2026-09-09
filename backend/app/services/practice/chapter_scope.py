"""Pure helpers for knowledge-hierarchy chapter practice selection."""

from __future__ import annotations


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
