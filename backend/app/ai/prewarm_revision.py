"""Shared revision identity for AI prewarm producers and analysis validation."""

from __future__ import annotations

import hashlib

from app.ai.prompts import AI_ANALYSIS_PROMPT_VERSION


def build_prewarm_revision(
    *, review_count: int | None, wrong_answer: str | None
) -> str:
    """Stable, non-sensitive revision for one wrong-question state.

    The durable queue keeps idempotency keys for seven days. A fixed task id such
    as ``prewarm:{wq_id}`` therefore suppresses legitimate regeneration when the
    same question is answered incorrectly again within that window. Include the
    wrong-question revision in the task id while hashing the answer so no user
    content is exposed in Redis keys/logs.
    """
    raw = f"{AI_ANALYSIS_PROMPT_VERSION}|{int(review_count or 0)}|{wrong_answer or ''}"
    state_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:14]
    return f"r{int(review_count or 0)}:{state_hash}"
