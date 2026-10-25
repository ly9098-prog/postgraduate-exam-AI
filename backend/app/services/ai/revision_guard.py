"""Revision-drift guard for wrong-question AI analysis.

The guard compares the immutable wrong-attempt revision with the current
question projection. If answer semantics changed, the analysis must not
reinterpret an old answer key against new content/options.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.answer_grounding import (
    build_answer_grounding,
    build_revision_drift_analysis,
    grounding_fact_signature,
)
from app.models.admin import QuestionVersion

__all__ = ["check_analysis_revision_drift"]


async def check_analysis_revision_drift(
    db: AsyncSession,
    *,
    wrong_question: Any,
    question: Any,
) -> dict | None:
    """Return a guarded response when revision semantics drifted, else ``None``."""
    import logging

    logger = logging.getLogger(__name__)

    current_grounding = build_answer_grounding(
        question_type=getattr(question, "question_type", None),
        content=question.content,
        options=question.options,
        correct_answer=question.answer,
        user_answer=wrong_question.wrong_answer,
    )
    current_version_id = int(getattr(question, "current_version_id", 0) or 0)
    wrong_version_id = int(getattr(wrong_question, "question_version_id", 0) or 0)
    if not (current_version_id and wrong_version_id and current_version_id != wrong_version_id):
        return None

    revision = await db.scalar(
        select(QuestionVersion).where(
            QuestionVersion.id == wrong_version_id,
            QuestionVersion.question_id == wrong_question.question_id,
        )
    )
    revision_semantics_match = False
    if revision is not None:
        historical_grounding = build_answer_grounding(
            question_type=getattr(revision, "question_type", None)
            or getattr(question, "question_type", None),
            content=revision.content,
            options=revision.options,
            correct_answer=revision.answer,
            user_answer=wrong_question.wrong_answer,
        )
        revision_semantics_match = (
            grounding_fact_signature(current_grounding)
            == grounding_fact_signature(historical_grounding)
        )
    if revision_semantics_match:
        return None

    logger.warning(
        "ai.error_analysis.revision_guard wq_id=%s question_id=%s "
        "wrong_version_id=%s current_version_id=%s revision_found=%s",
        wrong_question.id,
        question.id,
        wrong_version_id,
        current_version_id,
        revision is not None,
    )
    return {
        "content": build_revision_drift_analysis(),
        "from_cache": False,
        "from_fallback": False,
        "tokens_used": 0,
        "model": "revision_guard",
        "duration_ms": 0,
        "force_regenerated": False,
        "visual_input_count": 0,
        "input_mode": "text",
        "generated_at": datetime.now(UTC).isoformat(),
        "revision_guarded": True,
    }
