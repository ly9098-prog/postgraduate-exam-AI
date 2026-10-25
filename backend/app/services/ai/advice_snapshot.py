"""Build study-advice context and response payloads."""

from __future__ import annotations

from typing import Any

from app.services.knowledge_point_service import load_question_kps


async def build_advice_snapshot(db, wrong_list, load_kps=load_question_kps) -> dict:
    from app.models.question import Question
    from sqlalchemy import select

    question_ids = [int(w.question_id) for w in wrong_list if w.question_id]
    questions = {}
    if question_ids:
        result = await db.execute(
            select(Question).where(Question.id.in_(question_ids))
        )
        questions = {int(q.id): q for q in result.scalars().all()}
    kp_map = await load_kps(db, question_ids)

    weak_points: set[str] = set()
    subject_stats: dict[str, int] = {}
    recent_wrong: list[dict[str, Any]] = []
    for wrong in wrong_list:
        question = questions.get(int(wrong.question_id or 0))
        if not question:
            continue
        weak_points.update(kp_map.get(int(question.id), []))
        label = str(question.subject_id)
        subject_stats[label] = subject_stats.get(label, 0) + 1
        recent_wrong.append(
            {
                "subject_id": question.subject_id,
                "error_type": wrong.error_type,
                "wrong_answer": wrong.wrong_answer,
                "correct_answer": question.answer,
            }
        )
    return {
        "weak_points": list(weak_points),
        "subject_stats": subject_stats,
        "recent_wrong": recent_wrong,
    }


def parse_advice_content(raw: str) -> dict:
    import json

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"overall_assessment": raw}
    return parsed if isinstance(parsed, dict) else {"overall_assessment": raw}


def advice_fallback_response(content: dict) -> dict:
    return {
        "content": content,
        "from_cache": False,
        "from_fallback": True,
        "tokens_used": 0,
        "model": "fallback",
        "duration_ms": 0,
    }


def advice_success_response(parsed: dict, result: dict) -> dict:
    return {
        "content": parsed,
        "from_cache": False,
        "from_fallback": False,
        "tokens_used": result["tokens_used"],
        "model": result["model"],
        "duration_ms": result["duration_ms"],
    }
