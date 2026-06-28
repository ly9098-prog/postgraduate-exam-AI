import hashlib
import logging
import re

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache
from app.core.database import get_db

logger = logging.getLogger(__name__)
from app.core.security import get_current_user
from app.models.question import Question
from app.models.user import User
from app.schemas.common import paginated_response
from app.schemas.practice import (
    AnswerResult,
    AnswerSubmit,
    BatchSubmitRequest,
    BatchSubmitResponse,
    PracticeQuestionsResponse,
    PracticeQuestion,
    PracticeRecordItem,
    PracticeStatsResponse,
)
from app.services import practice_service as svc
from app.features.text_normalizer import _split_inline_roman_subitems
from app.services.pdf_text_normalizer import deduplicate_repeated_text

# Regex: lines ending with a trailing operator (OCR-split code expressions)
_CODE_OP_SPLIT_RE = re.compile(
    r'(?:<=|>=|==|!=|&&|\|\||<<|>>|[<>=!+\-*/%&|^])\s*$'
)

# Code detection signals (mirrors frontend containsCode logic)
_CODE_SIGNALS = [
    'return', 'printf', 'scanf', 'malloc', 'free', 'NULL',
    'struct', 'typedef', 'enum', 'union',
    'int ', 'void ', 'char ', 'float ', 'double ',
    'bool', 'const', 'static', 'sizeof',
    '->', '::', '{', '}', ';',
    '++', '--', '+=', '-=', '*=', '/=',
    '#include', '#define',
]
_CONTROL_KW = [
    'for', 'while', 'if', 'else if', 'else', 'switch',
    'return', 'break', 'continue', 'case', 'do',
]
_DS_KW = [
    'LNode', 'TNode', 'BiTNode', 'BiTree', 'BSTNode', 'LinkList',
    'SqList', 'Stack', 'Queue', 'SqStack', 'ElemType', 'Status',
]


def _contains_code(text: str) -> bool:
    """Heuristic: does text contain enough signals to be code?"""
    if not isinstance(text, str) or not text:
        return False
    score = 0
    for sig in _CODE_SIGNALS:
        if sig in text:
            score += 1
    for kw in _DS_KW:
        if kw in text:
            score += 2
    for kw in _CONTROL_KW:
        if re.search(r'\b' + re.escape(kw) + r'\b', text):
            score += 1
    return score >= 3
from app.utils.trace.debug import create_trace_id, debug_log, save_debug_snapshot

_TRUE_FALSE_OPTIONS = {"A": "正确", "B": "错误"}


def _ensure_true_false_options(question_type: str, options: dict | None) -> dict | None:
    if question_type in ("true_false", "judgement") and not options:
        return _TRUE_FALSE_OPTIONS
    return options


def _fix_code_operator_splits(text: str) -> str:
    """Merge lines where a trailing operator was split across newlines by OCR.

    Handles common OCR artifacts like:
      ``i*=\n2)`` → ``i*=2)``   (operator then integer)
      ``n==\n1)`` → ``n==1)``
      ``k +=\n2)`` → ``k +=2)``
    """
    if not isinstance(text, str) or "\n" not in text:
        return text
    lines = text.split("\n")
    merged = [lines[0]]
    for line in lines[1:]:
        if _CODE_OP_SPLIT_RE.search(merged[-1]):
            merged[-1] += line.lstrip()
        else:
            merged.append(line)
    return "\n".join(merged)


def _sanitize_text_field(value: str | None) -> str | None:
    if not isinstance(value, str):
        return value

    # Normalize line endings before any processing
    value = re.sub(r"\r\n", "\n", value)
    value = re.sub(r"\r", "\n", value)

    # Code content must bypass dedup and roman-split to preserve
    # indentation, repeated lines, and control-statement structure.
    # Only apply normalize operators across newlines (OCR artifact fix).
    if _contains_code(value):
        value = _fix_code_operator_splits(value)
        return value

    value = deduplicate_repeated_text(value)
    value = _split_inline_roman_subitems(value)
    value = _fix_code_operator_splits(value)
    return value


def _sanitize_question_content(content: dict | None) -> dict | None:
    if not isinstance(content, dict):
        return content

    sanitized = dict(content)
    for field in ("text", "stem"):
        if field in sanitized:
            sanitized[field] = _sanitize_text_field(sanitized[field])

    # Prefer stem over text when both exist — stem has better code formatting
    if "text" in sanitized and "stem" in sanitized and sanitized.get("stem"):
        sanitized["text"] = sanitized["stem"]

    return sanitized


def _sanitize_option_value(value: str | None) -> str | None:
    """Sanitize a single option value — skip roman-subitem splitting.

    Option values are short display text (e.g. \"I、II、III\", \"O(n)\").
    Applying _split_inline_roman_subitems here corrupts enumeration values
    by inserting newlines inside short option text. Only apply code-operator
    split (for code options) and collapse embedded newlines (OCR artifacts).
    """
    if not isinstance(value, str):
        return value
    # Normalize line endings (PDF/OCR can produce \r\n)
    value = re.sub(r"\r\n", "\n", value)
    value = re.sub(r"\r", "\n", value)
    value = _fix_code_operator_splits(value)
    # Collapse remaining newlines to space — prevents option content from
    # rendering as two lines (newline in option → mp-html <br> → visual doubling)
    value = re.sub(r"\n+", " ", value).strip()
    return value


def _sanitize_question_options(options: dict | None) -> dict | None:
    if not isinstance(options, dict):
        return options

    sanitized = dict(options)
    for key, value in sanitized.items():
        sanitized[key] = _sanitize_option_value(value)
    return sanitized


router = APIRouter(prefix="/api/v1/practice")


@router.get("/questions")
async def get_practice_questions(
    subject: str = Query(...),
    count: int = Query(20, ge=1, le=50),
    mode: str = Query("random"),
    knowledge_point: str | None = Query(None),
    exclude_answered: bool = Query(False),
    source_question_id: int | None = Query(None),
    smart_strategy: str = Query("weakness_vector"),
    x_trace_id: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    trace_id = x_trace_id or create_trace_id()
    kps = (
        [kp.strip() for kp in knowledge_point.split(",") if kp.strip()]
        if knowledge_point
        else None
    )

    # metadata: 题目推荐元数据（仅 smart/similar 模式使用）
    question_metadata: dict[int, dict] = {}
    request_id: str | None = None

    if mode == "similar":
        if not source_question_id:
            # 缺少 source_question_id，回退到 random
            logger.warning("similar 模式缺少 source_question_id，回退到 random")
            mode = "random"
            questions = await svc.get_practice_questions(
                db=db, user_id=current_user.id, subject=subject,
                count=count, mode="random", knowledge_points=kps,
                exclude_answered=exclude_answered,
            )
        else:
            import uuid
            request_id = str(uuid.uuid4())
            questions, question_metadata = await svc.get_similar_practice_questions(
                db=db, user_id=current_user.id, subject=subject,
                source_question_id=source_question_id, count=count,
                exclude_answered=exclude_answered,
            )
            # 记录推荐日志
            try:
                from app.services import recommendation_log_service
                recs = [
                    {
                        "question_id": qid,
                        "subject": meta.get("subject", subject),
                        "recommend_score": meta.get("recommend_score"),
                        "similarity": meta.get("similarity"),
                        "reason": meta.get("recommend_reason"),
                    }
                    for qid, meta in question_metadata.items()
                ]
                if recs:
                    await recommendation_log_service.create_recommendation_logs(
                        db=db, user_id=current_user.id, recommendations=recs,
                        scene="similar", strategy="vector_plus_rule",
                        request_id=request_id, source_question_id=source_question_id,
                    )
            except Exception:
                logger.warning("similar 推荐日志写入失败", exc_info=True)

    elif mode == "smart":
        import uuid
        request_id = str(uuid.uuid4())
        questions, question_metadata = await svc.get_smart_practice_questions(
            db=db, user_id=current_user.id, subject=subject,
            count=count, exclude_answered=exclude_answered,
            request_id=request_id, smart_strategy=smart_strategy,
        )

    else:
        # random / sequential — 原有逻辑
        questions = await svc.get_practice_questions(
            db=db, user_id=current_user.id, subject=subject,
            count=count, mode=mode, knowledge_points=kps,
            exclude_answered=exclude_answered,
        )
    # ── Layer 1 诊断：API 响应 stem 数据 ──
    for q in questions:
        content = _sanitize_question_content(q.content)
        stem = (content or {}).get("text") or (content or {}).get("stem") or ""
        logger.info(
            "[API_LAYER] qid=%s textLen=%d textHash=%s stemKeys=%s",
            q.id,
            len(stem),
            hashlib.sha256(stem.encode()).hexdigest()[:8],
            [k for k in (content or {}) if k in ("text", "stem", "segments")],
        )
    response = PracticeQuestionsResponse(
        questions=[
            PracticeQuestion(
                id=q.id,
                subject=q.subject,
                question_type=q.question_type,
                content=_sanitize_question_content(q.content),
                options=_sanitize_question_options(
                    _ensure_true_false_options(q.question_type, q.options)
                ),
                knowledge_points=q.knowledge_points,
                difficulty=q.difficulty,
                trace_id=trace_id,
                recommend_reason=(question_metadata.get(q.id) or {}).get("recommend_reason"),
                recommend_score=(question_metadata.get(q.id) or {}).get("recommend_score"),
                strategy=(question_metadata.get(q.id) or {}).get("strategy"),
                similarity=(question_metadata.get(q.id) or {}).get("similarity"),
            )
            for q in questions
        ],
        total=len(questions),
        mode=mode,
        trace_id=trace_id,
        request_id=request_id,
    )
    debug_log(
        trace_id,
        "API_RESPONSE",
        {"endpoint": "practice/questions", "subject": subject, "count": len(questions)},
    )
    save_debug_snapshot(
        trace_id,
        "api_response",
        {
            "endpoint": "practice/questions",
            "subject": subject,
            "question_ids": [q.id for q in questions],
            "total": len(questions),
        },
    )
    return response


@router.post("/submit", response_model=AnswerResult)
async def submit_answer(
    data: AnswerSubmit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        result = await svc.submit_answer(
            db=db,
            user_id=current_user.id,
            question_id=data.question_id,
            user_answer=data.user_answer,
            used_time=data.used_time,
            request_id=data.request_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 失效用户相关缓存
    await cache.delete(f"practice:stats:{current_user.id}:*")
    await cache.delete(f"stats:*:{current_user.id}*")

    return AnswerResult(**result)


@router.post("/batch-submit", response_model=BatchSubmitResponse)
async def batch_submit(
    data: BatchSubmitRequest,
    x_trace_id: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    trace_id = x_trace_id or create_trace_id()
    debug_log(
        trace_id,
        "SUBMIT",
        {"endpoint": "practice/batch-submit", "answer_count": len(data.answers)},
    )
    save_debug_snapshot(
        trace_id,
        "submit_before",
        {"question_ids": [answer.question_id for answer in data.answers]},
    )
    try:
        result = await svc.batch_submit_answers(
            db=db,
            user_id=current_user.id,
            answers=[a.model_dump() for a in data.answers],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 失效用户相关缓存
    await cache.delete(f"practice:stats:{current_user.id}:*")
    await cache.delete(f"stats:*:{current_user.id}*")
    await cache.delete(f"review:*:{current_user.id}*")

    save_debug_snapshot(
        trace_id,
        "submit_after",
        {
            "total_correct": result["total_correct"],
            "total_wrong": result["total_wrong"],
            "result_count": len(result["results"]),
        },
    )
    return BatchSubmitResponse(
        results=[AnswerResult(**r) for r in result["results"]],
        total_correct=result["total_correct"],
        total_wrong=result["total_wrong"],
        trace_id=trace_id,
    )


@router.get("/stats", response_model=PracticeStatsResponse)
async def get_practice_stats(
    days: int = Query(7, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cache_key = f"practice:stats:{current_user.id}:{days}"
    cached_data = await cache.get(cache_key)
    if cached_data is not None:
        return cached_data
    data = await svc.get_practice_stats(db, current_user.id, days=days)
    result = PracticeStatsResponse(**data)
    await cache.set(cache_key, result.model_dump(), ttl=300)
    return result


@router.get("/records")
async def list_records(
    subject: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from sqlalchemy import and_, func, select
    from app.models.practice_record import PracticeRecord as PR

    conds = [PR.user_id == current_user.id]
    if subject:
        conds.append(PR.subject == subject)

    total = (
        await db.execute(select(func.count(PR.id)).where(and_(*conds)))
    ).scalar()

    rows = await db.execute(
        select(PR)
        .where(and_(*conds))
        .order_by(PR.answered_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = rows.scalars().all()

    return paginated_response(
        items=[PracticeRecordItem.model_validate(r) for r in items],
        total=total,
        page=page,
        page_size=page_size,
    )
