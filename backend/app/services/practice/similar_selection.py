"""Assemble similar recall and its supplement without owning issuance."""

from __future__ import annotations

from typing import Any


async def run_similar_selection(
    db: Any,
    user_id: int,
    source_question_id: int,
    scope_ids: list[int],
    *,
    count: int,
    exclude_answered: bool,
    no_repeat_days: int | None,
    namespace: dict[str, Any],
) -> tuple[list, dict[int, dict]]:
    from app.services import vector_retrieval_service

    vector_questions, metadata = await namespace["load_similar_vector_questions"](
        namespace["SimilarRecallRequest"](
            db=db,
            user_id=user_id,
            source_question_id=source_question_id,
            scope_ids=scope_ids,
            excluded_sub=namespace["_build_excluded_question_subquery"](
                user_id=user_id,
                exclude_answered=exclude_answered,
                no_repeat_days=no_repeat_days,
            ),
            logger=namespace["logger"],
            search_similar=vector_retrieval_service.search_similar_questions,
            revision_condition=namespace["_practice_revision_scope_condition"],
        )
    )
    if len(vector_questions) >= count:
        return vector_questions[:count], metadata
    return await _supplement_similar_questions(
        db,
        user_id,
        source_question_id,
        scope_ids,
        vector_questions,
        metadata,
        count,
        exclude_answered,
        no_repeat_days,
        namespace,
    )


async def _supplement_similar_questions(
    db: Any,
    user_id: int,
    source_question_id: int,
    scope_ids: list[int],
    vector_questions: list,
    metadata: dict[int, dict],
    count: int,
    exclude_answered: bool,
    no_repeat_days: int | None,
    namespace: dict[str, Any],
) -> tuple[list, dict[int, dict]]:
    existing_ids = {q.id for q in vector_questions}
    existing_ids.add(source_question_id)
    subject_cond = namespace["Question"].subject_id.in_(scope_ids)
    conditions = [
        namespace["Question"].is_active,
        subject_cond,
        namespace["_practice_revision_scope_condition"](scope_ids),
        namespace["Question"].id.notin_(existing_ids),
    ]
    excluded_sub = namespace["_build_excluded_question_subquery"](
        user_id=user_id,
        exclude_answered=exclude_answered,
        no_repeat_days=no_repeat_days,
    )
    if excluded_sub is not None:
        conditions.append(namespace["Question"].id.notin_(excluded_sub))
    fill_questions = await namespace["load_similar_fill_questions"](
        db,
        conditions,
        count - len(vector_questions),
        namespace["_random_sample_query"],
    )
    namespace["apply_fill_metadata"](metadata, fill_questions)
    return vector_questions + fill_questions, metadata
