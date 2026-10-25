"""Question/knowledge-state loaders for chapter-scope practice."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.models.question_knowledge_point import QuestionKnowledgePoint
from app.models.user_knowledge_state import UserKnowledgeState


async def load_knowledge_states(
    db: Any,
    user_id: int,
    target_ids: list[int],
) -> dict[int, Any]:
    rows = await db.execute(
        select(UserKnowledgeState).where(
            UserKnowledgeState.user_id == user_id,
            UserKnowledgeState.knowledge_point_id.in_(target_ids),
        )
    )
    return {int(state.knowledge_point_id): state for state in rows.scalars().all()}


async def load_question_knowledge_rows(
    db: Any,
    candidate_ids: list[int],
    target_ids: list[int],
):
    return await db.execute(
        select(
            QuestionKnowledgePoint.question_id,
            QuestionKnowledgePoint.knowledge_point_id,
        ).where(
            QuestionKnowledgePoint.question_id.in_(candidate_ids),
            QuestionKnowledgePoint.knowledge_point_id.in_(target_ids),
        )
    )
