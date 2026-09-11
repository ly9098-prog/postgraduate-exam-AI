"""题库相似匹配纠错层 — 为 OCR 导入题目提供"建议修正"。

位于 repair 之后、review 之前。

P2-4：
- chunked 路径下由 orchestrator 注入 ``GlobalHashIndex``（最近 N 天 + 当
  前批次的 hash → id 映射），命中即标 ``similarity_suggestion`` 为强信号
  duplicate（ratio=1.0），跳过 stem 模糊扫描。
- 单 pass / 单 chunk / 索引未注入时退化为旧的 subject-级 difflib 模糊
  匹配，行为零变化。

不修改题目内容，仅附加 ``similarity_suggestion`` 字段供人工审核参考。
"""

import asyncio
import difflib
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.global_hash_index import GlobalHashIndex
from app.features.question_pipeline import normalizer


def _strip_whitespace(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _compute_similarity(left: str, right: str) -> float:
    a = _strip_whitespace(left)
    b = _strip_whitespace(right)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _options_to_dict(options) -> dict | None:
    """[{"key": "A", "text": "..."}] → {"A": "..."}, mirroring review_service。"""
    if not options:
        return None
    if isinstance(options, dict):
        return {str(k).upper(): str(v) for k, v in options.items() if v}
    result: dict[str, str] = {}
    for opt in options:
        if not isinstance(opt, dict):
            continue
        key = (opt.get("key") or "").strip().upper()
        text = (opt.get("text") or "").strip()
        if key and text:
            result[key] = text
    return result or None


def _compute_question_hash(question: dict) -> str:
    """与 review_service.submit_to_review 相同的 hash 计算口径。"""
    stem = (question.get("stem") or "").strip()
    if not stem:
        return ""
    parsed_options = _options_to_dict(question.get("options"))
    parsed_answer = (question.get("answer") or "").strip() or None
    return normalizer.build_question_hash(stem, parsed_options, parsed_answer)


async def _load_subject_questions(db: AsyncSession, subject: str) -> list[dict]:
    from app.models.question import Question
    from app.services.admin_subject_service import resolve_subject_id

    subject_id = await resolve_subject_id(db, subject)
    if subject_id is None:
        return []
    result = await db.execute(
        select(Question.id, Question.content, Question.options, Question.answer).where(
            Question.subject_id == subject_id,
            Question.is_active == True,  # noqa: E712
        )
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


async def _load_question_payload(db: AsyncSession, question_id: int) -> dict | None:
    """命中 hash 后再单条捞 stem/options/answer 用于 suggestion 展示。"""
    from app.models.question import Question

    row = (
        await db.execute(
            select(Question.content, Question.options, Question.answer).where(
                Question.id == question_id
            )
        )
    ).first()
    if row is None:
        return None
    content, options, answer = row
    return {
        "stem": (content or {}).get("text", ""),
        "options": options,
        "answer": answer,
    }


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
    hash_index: GlobalHashIndex | None = None,
) -> dict:
    """题库相似匹配纠错层。

    Args:
        questions: repair 阶段输出的标准化题目列表
        db: 异步数据库会话
        config: {
            "enabled": True,
            "similarity_threshold": 0.85,
        }
        hash_index: 可选 ``GlobalHashIndex``。注入后 hash 命中走严格匹配
            （ratio=1.0，标 ``source="question_bank_hash"``），不再扫
            subject 全表；hash miss 的题目仍走旧的 difflib fallback。
            为保护 chunk 间内存上限，该 fallback 仅在 hash_index 未注入
            （即单 pass / 单 chunk / 无 db）时启用，避免每个 chunk 都重
            复加载 subject 全题库。

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
                "hash_hit_count": 0,
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
                "hash_hit_count": 0,
            },
            "skipped_reason": "no_db_session",
        }

    threshold = config.get("similarity_threshold", 0.85)
    matches: list[dict] = []
    subject_cache: dict[str, list[dict]] = {}
    total_ratio = 0.0
    matched_count = 0
    hash_hit_count = 0

    result_questions: list[dict] = []
    loop = asyncio.get_running_loop()

    for i, question in enumerate(questions):
        subject = question.get("subject", "")
        stem = question.get("stem", "")

        if not subject or not stem:
            result_questions.append(question)
            continue

        suggestion: dict | None = None

        # P2-4: hash 优先。命中即视为强信号 duplicate，跳过 difflib 扫描。
        if hash_index is not None:
            qhash = _compute_question_hash(question)
            if qhash:
                question_id = await hash_index.lookup_question(db, subject, qhash)
                if question_id is not None:
                    payload = await _load_question_payload(db, question_id) or {}
                    suggestion = {
                        "matched_question_id": question_id,
                        "similarity_ratio": 1.0,
                        "suggested_stem": payload.get("stem", ""),
                        "suggested_options": payload.get("options"),
                        "suggested_answer": payload.get("answer"),
                        "source": "question_bank_hash",
                    }
                    hash_hit_count += 1

        # hash miss 的 fallback：仅在没注入 index 时跑 subject 全表 difflib
        # （chunked 路径已注入 index → 不在每 chunk 重复加载题库）。
        if suggestion is None and hash_index is None:
            if subject not in subject_cache:
                subject_cache[subject] = await _load_subject_questions(db, subject)
            bank = subject_cache[subject]
            if bank:
                suggestion = await loop.run_in_executor(
                    None, _find_best_match, stem, bank, threshold
                )

        new_question = dict(question)
        if suggestion:
            new_question["similarity_suggestion"] = suggestion
            matched_count += 1
            total_ratio += suggestion["similarity_ratio"]
            matches.append(
                {
                    "question_index": i,
                    "matched_question_id": suggestion["matched_question_id"],
                    "similarity_ratio": suggestion["similarity_ratio"],
                    "source": suggestion.get("source"),
                }
            )

        result_questions.append(new_question)

    avg_ratio = round(total_ratio / matched_count, 4) if matched_count > 0 else 0.0

    return {
        "questions": result_questions,
        "matches": matches,
        "stats": {
            "total_questions": len(questions),
            "matched_count": matched_count,
            "avg_similarity": avg_ratio,
            "hash_hit_count": hash_hit_count,
        },
        "skipped_reason": None,
    }
