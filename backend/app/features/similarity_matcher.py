"""题库相似匹配纠错层 — 用已有题库为 OCR 导入题目提供"建议修正"。

位于 repair 之后、review 之前。
匹配范围：同 subject 内活跃题目。
不修改题目内容，仅附加 similarity_suggestion 字段供人工审核参考。
"""

import asyncio
import difflib
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _strip_whitespace(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _compute_similarity(left: str, right: str) -> float:
    a = _strip_whitespace(left)
    b = _strip_whitespace(right)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


async def _load_subject_questions(db: AsyncSession, subject: str) -> list[dict]:
    from app.models.question import Question

    result = await db.execute(
        select(Question.id, Question.content, Question.options, Question.answer)
        .where(Question.subject == subject, Question.is_active == True)  # noqa: E712
    )
    rows = result.all()
    return [
        {
            "id": row.id,
            "stem": (row.content or {}).get("text", ""),
            "options": row.options,
            "answer": row.answer,
        }
        for row in rows
    ]


def _find_best_match(
    stem: str,
    bank: list[dict],
    threshold: float,
) -> dict | None:
    a = _strip_whitespace(stem)
    if not a:
        return None

    a_len = len(a)
    best_ratio = 0.0
    best_match = None

    for item in bank:
        b = _strip_whitespace(item["stem"])
        if not b:
            continue

        b_len = len(b)
        # Pre-filter: length difference > 50% can't reach 0.85 similarity
        # (relaxed for short stems < 20 chars)
        if a_len >= 20 and b_len >= 20:
            if abs(a_len - b_len) / max(a_len, b_len) > 0.5:
                continue

        ratio = difflib.SequenceMatcher(None, a, b).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = item

    if best_ratio >= threshold and best_match is not None:
        return {
            "matched_question_id": best_match["id"],
            "similarity_ratio": round(best_ratio, 4),
            "suggested_stem": best_match["stem"],
            "suggested_options": best_match["options"],
            "suggested_answer": best_match["answer"],
            "source": "question_bank",
        }
    return None


async def match_similar_questions(
    questions: list[dict],
    db: AsyncSession | None = None,
    config: dict | None = None,
) -> dict:
    """题库相似匹配纠错层。

    Args:
        questions: repair 阶段输出的标准化题目列表
        db: 异步数据库会话
        config: {
            "enabled": True,
            "similarity_threshold": 0.85,
        }

    Returns:
        {
            "questions": [...],
            "matches": [...],
            "stats": {...},
            "skipped_reason": str | None,
        }
    """
    if config is None:
        config = {}

    enabled = config.get("enabled", True)
    if not enabled:
        return {
            "questions": questions,
            "matches": [],
            "stats": {
                "total_questions": len(questions),
                "matched_count": 0,
                "avg_similarity": 0.0,
            },
            "skipped_reason": "disabled",
        }

    if db is None:
        return {
            "questions": questions,
            "matches": [],
            "stats": {
                "total_questions": len(questions),
                "matched_count": 0,
                "avg_similarity": 0.0,
            },
            "skipped_reason": "no_db_session",
        }

    threshold = config.get("similarity_threshold", 0.85)
    matches: list[dict] = []
    subject_cache: dict[str, list[dict]] = {}
    total_ratio = 0.0
    matched_count = 0

    result_questions = []
    loop = asyncio.get_running_loop()

    for i, question in enumerate(questions):
        subject = question.get("subject", "")
        stem = question.get("stem", "")

        if not subject or not stem:
            result_questions.append(question)
            continue

        if subject not in subject_cache:
            subject_cache[subject] = await _load_subject_questions(db, subject)

        bank = subject_cache[subject]
        if not bank:
            result_questions.append(question)
            continue

        suggestion = await loop.run_in_executor(
            None, _find_best_match, stem, bank, threshold
        )

        new_question = dict(question)
        if suggestion:
            new_question["similarity_suggestion"] = suggestion
            matched_count += 1
            total_ratio += suggestion["similarity_ratio"]
            matches.append({
                "question_index": i,
                "matched_question_id": suggestion["matched_question_id"],
                "similarity_ratio": suggestion["similarity_ratio"],
            })

        result_questions.append(new_question)

    avg_ratio = round(total_ratio / matched_count, 4) if matched_count > 0 else 0.0

    return {
        "questions": result_questions,
        "matches": matches,
        "stats": {
            "total_questions": len(questions),
            "matched_count": matched_count,
            "avg_similarity": avg_ratio,
        },
        "skipped_reason": None,
    }
