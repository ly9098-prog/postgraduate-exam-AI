import hashlib
import json
import logging
import re
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache
from app.core.database import get_db
from app.core.log_context import get_log_context, normalize_trace_id

logger = logging.getLogger(__name__)
from app.core.security import get_current_user
from app.features.text_normalizer import _split_inline_roman_subitems
from app.models.sequential_reservation import SequentialReservation
from app.models.user import User
from app.schemas.common import paginated_response
from app.schemas.practice import (
    AnswerResult,
    BatchSubmitRequest,
    BatchSubmitResponse,
    PracticeKnowledgeSummaryResponse,
    PracticeMode,
    PracticeQuestion,
    PracticeQuestionsResponse,
    PracticeRecordItem,
    PracticeSessionScopeResponse,
    PracticeStatsResponse,
    SequentialPracticeResetRequest,
    SequentialPracticeResetResponse,
)
from app.services import practice_service as svc
from app.services.knowledge_point_service import load_question_kps  # noqa: F401
from app.services.pdf_text_normalizer import deduplicate_repeated_text
from app.services.question_revision_service import (
    load_revision_kp_names,
    load_revision_views,
)
from app.utils.question_content import (
    reconcile_student_stem_fields,
    strip_student_segment_metadata,
)

# Regex: lines ending with a trailing operator (OCR-split code expressions)
_CODE_OP_SPLIT_RE = re.compile(r"(?:<=|>=|==|!=|&&|\|\||<<|>>|[<>=!+\-*/%&|^])\s*$")

# Code detection signals (mirrors frontend containsCode logic)
_CODE_SIGNALS = [
    "return",
    "printf",
    "scanf",
    "malloc",
    "free",
    "NULL",
    "struct",
    "typedef",
    "enum",
    "union",
    "int ",
    "void ",
    "char ",
    "float ",
    "double ",
    "bool",
    "const",
    "static",
    "sizeof",
    "->",
    "::",
    "{",
    "}",
    ";",
    "++",
    "--",
    "+=",
    "-=",
    "*=",
    "/=",
    "#include",
    "#define",
]
_CONTROL_KW = [
    "for",
    "while",
    "if",
    "else if",
    "else",
    "switch",
    "return",
    "break",
    "continue",
    "case",
    "do",
]
_DS_KW = [
    "LNode",
    "TNode",
    "BiTNode",
    "BiTree",
    "BSTNode",
    "LinkList",
    "SqList",
    "Stack",
    "Queue",
    "SqStack",
    "ElemType",
    "Status",
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
        if re.search(r"\b" + re.escape(kw) + r"\b", text):
            score += 1
    return score >= 3


from app.utils.trace.debug import debug_log, save_debug_snapshot

_TRUE_FALSE_OPTIONS = {"A": "正确", "B": "错误"}


def _sequential_submission_request_id(
    start_request_id: str,
    subject_id: int,
    scope_identity: dict,
) -> str:
    """Derive a stable submission id without crossing practice scopes."""
    canonical_scope = json.dumps(
        scope_identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(
        f"{start_request_id}:{subject_id}:{canonical_scope}".encode()
    ).hexdigest()[:48]
    return f"practice_{digest}"


def _ensure_true_false_options(question_type: str, options: dict | None) -> dict | None:
    if question_type == "true_false" and not options:
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

    # Historical revisions can contain a freshly edited ``text`` alongside a
    # stale ``stem``. Reconcile them before the payload reaches renderers so the
    # newest revision cannot look like an older question version.
    sanitized = reconcile_student_stem_fields(sanitized)

    # Strip admin-only fields that should never reach student clients
    sanitized.pop("source_snapshot_url", None)
    sanitized.pop("source_snapshot_full_page", None)
    sanitized.pop("visual_regions", None)
    sanitized.pop("visual_region_ids", None)

    return strip_student_segment_metadata(sanitized)


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
        if isinstance(value, dict):
            # Rich format: {"A": {"text": "...", "segments": [...]}}
            text_val = value.get("text") or value.get("value") or ""
            sanitized[key] = {
                **value,
                "text": _sanitize_option_value(text_val),
            }
        else:
            sanitized[key] = _sanitize_option_value(value)
    return sanitized


router = APIRouter(prefix="/api/v1/practice")


@router.get("/subjects")
async def get_practice_subjects(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """返回刷题页可用科目树（动态，不硬编码）。"""
    return await svc.get_practice_subject_tree(db)


@router.get("/questions", response_model=PracticeQuestionsResponse)
async def get_practice_questions(
    response: Response,
    subject_id: int = Query(...),
    include_children: bool = Query(True),
    count: int = Query(20, ge=1, le=50),
    mode: PracticeMode = Query("random"),
    knowledge_point: str | None = Query(None),
    knowledge_point_id: int | None = Query(None, ge=1),
    include_descendants: bool = Query(False),
    exclude_answered: bool = Query(False),
    no_repeat_days: int | None = Query(None, ge=1, le=365),
    use_leitner: bool = Query(True),
    source_question_id: int | None = Query(None),
    question_ids: str | None = Query(None, max_length=1024),
    start_request_id: str | None = Query(None, max_length=128),
    # smart 默认走综合 scored；客户端仍只需要传 mode=smart。
    # weakness_vector 保留为显式 fallback / A/B control。
    smart_strategy: str = Query("scored"),
    plan_token: str | None = Query(None, max_length=2048),
    x_trace_id: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Personalized practice batches contain a signed immutable-revision token.
    # Never let a WebView/proxy reuse an older GET response after a question edit.
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"

    # 解析 subject_id → (subject_code, subject_name)
    resolved = await svc.resolve_subject_id_to_code(db, subject_id)
    if resolved is None:
        raise HTTPException(
            status_code=404, detail=f"科目不存在: subject_id={subject_id}"
        )
    subject_code, subject_name = resolved

    # 始终使用 subject_code（字符串）作查询参数，避免与 VARCHAR 列比较时类型不匹配
    subject_for_query: str = subject_code

    # 解析科目作用域：是否有启用子科目、需要查询的 subject ID 列表
    has_enabled_children, scope_subject_ids = await svc.resolve_practice_subject_scope(
        db,
        subject_id,
        include_children,
    )
    if not scope_subject_ids:
        # The subject may have been disabled after the client cached the subject
        # tree.  Treat that as an unavailable subject instead of continuing with
        # an empty SQL scope and presenting a misleading “暂无题目” state.
        raise HTTPException(
            status_code=404, detail="科目不可用或已停用，请重新选择科目"
        )

    # 父级科目 + sequential → 400
    if has_enabled_children and mode == "sequential":
        raise HTTPException(
            status_code=400,
            detail="顺序练习仅支持具体科目，不支持父级科目聚合刷题",
        )

    trace_id = str(get_log_context().get("trace_id") or normalize_trace_id(x_trace_id))
    if knowledge_point and knowledge_point_id is not None:
        raise HTTPException(
            status_code=400, detail="knowledge_point 与 knowledge_point_id 不能同时使用"
        )
    if include_descendants and knowledge_point_id is None:
        raise HTTPException(
            status_code=400, detail="include_descendants 需要 knowledge_point_id"
        )
    if include_descendants and mode != "random":
        raise HTTPException(
            status_code=400, detail="章节专项练习当前仅支持 random 模式"
        )

    knowledge_scope: dict | None = None
    knowledge_point_ids: list[int] | None = None
    if knowledge_point_id is not None:
        knowledge_scope = await svc.resolve_practice_knowledge_scope(
            db,
            knowledge_point_id=knowledge_point_id,
            subject_ids=scope_subject_ids,
            include_descendants=include_descendants,
        )
        if knowledge_scope is None:
            raise HTTPException(
                status_code=404, detail="知识点不存在、不属于当前科目范围或不在当前大纲"
            )
        knowledge_point_ids = list(knowledge_scope["knowledge_point_ids"])
        # 非章节模式保留历史名称过滤契约（sequential/similar fallback 仍会使用）；
        # random 同时携带 canonical ID，名称只是兼容约束。
        kps = [str(knowledge_scope["root_name"])] if not include_descendants else None
    else:
        kps = (
            [kp.strip() for kp in knowledge_point.split(",") if kp.strip()]
            if knowledge_point
            else None
        )

    targeted_question_ids: list[int] = []
    if question_ids:
        try:
            raw_ids = [
                part.strip() for part in str(question_ids).split(",") if part.strip()
            ]
            targeted_question_ids = [int(part) for part in raw_ids]
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=400, detail="question_ids 格式无效"
            ) from exc
        if not targeted_question_ids or len(targeted_question_ids) > 50:
            raise HTTPException(status_code=400, detail="question_ids 数量必须为 1-50")
        if any(qid <= 0 for qid in targeted_question_ids):
            raise HTTPException(status_code=400, detail="question_ids 必须为正整数")
        if len(set(targeted_question_ids)) != len(targeted_question_ids):
            raise HTTPException(status_code=400, detail="question_ids 不允许重复")
        if source_question_id or kps or knowledge_point_ids:
            raise HTTPException(
                status_code=400,
                detail="定向题目不可与 source_question_id/knowledge_point 混用",
            )
        if mode != "random":
            raise HTTPException(status_code=400, detail="定向题目仅支持 random runner")
        # A targeted retry is an explicit set, not a candidate pool.  Honour
        # every requested id (the client may omit ``count`` or leave its
        # generic default in place) and make the signed session count match
        # that immutable set instead of silently truncating it.
        count = len(targeted_question_ids)

    # metadata: 题目推荐元数据（仅 smart/similar 模式使用）
    question_metadata: dict[int, dict] = {}
    request_id: str | None = None
    sequential_progress: dict | None = None
    sequential_reservation_request_id: str | None = None

    # Random 模式多取一小段候选。最终版本/学科一致性守卫可能隔离历史误分类题；
    # 预留候选可以在不改变客户端请求 count 的情况下尽量补足题量。
    random_candidate_count = min(100, count + max(5, count // 2))

    if targeted_question_ids:
        questions = await svc.get_targeted_practice_questions(
            db,
            question_ids=targeted_question_ids,
            subject_ids=scope_subject_ids,
        )
        returned_ids = [int(question.id) for question in questions]
        expected_ids = targeted_question_ids
        if returned_ids != expected_ids:
            missing_ids = [qid for qid in expected_ids if qid not in set(returned_ids)]
            raise HTTPException(
                status_code=400,
                detail=f"定向题目已失效或超出当前科目范围: {missing_ids}",
            )

    elif mode == "similar":
        if not source_question_id:
            # 缺少 source_question_id，回退到 random
            logger.warning("similar 模式缺少 source_question_id，回退到 random")
            mode = "random"
            questions = await svc.get_practice_questions(
                db=db,
                user_id=current_user.id,
                subject_code=subject_for_query,
                count=random_candidate_count,
                mode="random",
                knowledge_points=kps,
                exclude_answered=exclude_answered,
                no_repeat_days=no_repeat_days,
                use_leitner=use_leitner,
                subject_ids=scope_subject_ids,
            )
        else:
            import uuid

            request_id = str(uuid.uuid4())
            questions, question_metadata = await svc.get_similar_practice_questions(
                db=db,
                user_id=current_user.id,
                subject_code=subject_for_query,
                source_question_id=source_question_id,
                count=count,
                exclude_answered=exclude_answered,
                no_repeat_days=no_repeat_days,
                use_leitner=use_leitner,
                subject_ids=scope_subject_ids,
            )
            # 记录推荐日志
            try:
                from app.services import recommendation_log_service

                recs = [
                    {
                        "question_id": qid,
                        "subject": meta.get("subject", subject_code),
                        "recommend_score": meta.get("recommend_score"),
                        "similarity": meta.get("similarity"),
                        "reason": meta.get("recommend_reason"),
                    }
                    for qid, meta in question_metadata.items()
                ]
                if recs:
                    await (
                        recommendation_log_service.create_recommendation_logs_isolated(
                            db=db,
                            user_id=current_user.id,
                            recommendations=recs,
                            scene="similar",
                            strategy="vector_plus_rule",
                            request_id=request_id,
                            source_question_id=source_question_id,
                        )
                    )
            except Exception:
                logger.warning("similar 推荐日志写入失败", exc_info=True)

    elif mode == "sequential":
        # 顺序模式是独立的题库进度模式：严格按 Question.id 推进，
        # 不参与 Leitner、薄弱点、错题优先或 no-repeat 调度。
        try:
            sequential_reservation_request_id = str(
                start_request_id or f"seqstart:{current_user.id}:{uuid4().hex}"
            ).strip()
            (
                questions,
                sequential_progress,
            ) = await svc.get_sequential_practice_questions(
                db=db,
                user_id=current_user.id,
                subject_id=subject_id,
                subject_ids=scope_subject_ids,
                count=count,
                knowledge_points=kps,
                reservation_request_id=sequential_reservation_request_id,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    elif mode == "smart":
        import uuid

        request_id = str(uuid.uuid4())
        if len(scope_subject_ids) > 1:
            # 父级科目聚合智能推荐
            questions, question_metadata = await svc.get_aggregated_smart_questions(
                db=db,
                user_id=current_user.id,
                subject_code=subject_for_query,
                subject_ids=scope_subject_ids,
                count=count,
                exclude_answered=exclude_answered,
                no_repeat_days=no_repeat_days,
                use_leitner=use_leitner,
                request_id=request_id,
                smart_strategy=smart_strategy,
            )
        else:
            questions, question_metadata = await svc.get_smart_practice_questions(
                db=db,
                user_id=current_user.id,
                subject_code=subject_for_query,
                subject_ids=scope_subject_ids,
                count=count,
                exclude_answered=exclude_answered,
                no_repeat_days=no_repeat_days,
                use_leitner=use_leitner,
                request_id=request_id,
                smart_strategy=smart_strategy,
            )

    else:
        # random
        if include_descendants and knowledge_point_ids:
            # 章节专项：先按 active syllabus 的 parent 子树限定题池，再在已通过
            # 普通 practice/Leitner 守卫的候选中按薄弱/待建立知识点优先选题。
            questions = await svc.get_knowledge_scope_practice_questions(
                db=db,
                user_id=current_user.id,
                subject_code=subject_for_query,
                subject_ids=scope_subject_ids,
                knowledge_point_ids=knowledge_point_ids,
                count=count,
                exclude_answered=exclude_answered,
                no_repeat_days=no_repeat_days,
                use_leitner=use_leitner,
            )
        elif len(scope_subject_ids) > 1:
            # 父级科目聚合随机
            questions = await svc.get_aggregated_random_questions(
                db=db,
                user_id=current_user.id,
                subject_code=subject_for_query,
                subject_ids=scope_subject_ids,
                count=random_candidate_count,
                knowledge_points=(kps if not knowledge_point_ids else None),
                knowledge_point_ids=knowledge_point_ids,
                exclude_answered=exclude_answered,
                no_repeat_days=no_repeat_days,
                use_leitner=use_leitner,
            )
        else:
            # 具体科目（叶子或 include_children=false）—— 精确查询
            # 传入 subject_ids 阻止 resolve_subject_ids 的内部递归扩展
            questions = await svc.get_practice_questions(
                db=db,
                user_id=current_user.id,
                subject_code=subject_for_query,
                subject_ids=scope_subject_ids,
                count=random_candidate_count,
                mode=mode,
                knowledge_points=(kps if not knowledge_point_ids else None),
                knowledge_point_ids=knowledge_point_ids,
                exclude_answered=exclude_answered,
                no_repeat_days=no_repeat_days,
                use_leitner=use_leitner,
            )
    # Recommendation providers (vector/path/scored) are external to the
    # canonical Leitner query and may return a question that became
    # not-yet-due after the provider built its candidate list. Enforce the
    # user-question schedule immediately before signing the batch.
    if use_leitner and mode in {"smart", "similar"} and questions:
        from app.services.question_review_service import get_due_question_ids

        due_ids = await get_due_question_ids(
            db, current_user.id, [int(question.id) for question in questions]
        )
        filtered_questions = [
            question for question in questions if int(question.id) in due_ids
        ]
        if len(filtered_questions) != len(questions):
            logger.info(
                "[PRACTICE_LEITNER_GUARD] uid=%s mode=%s filtered=%s remaining=%s",
                current_user.id,
                mode,
                len(questions) - len(filtered_questions),
                len(filtered_questions),
            )
        missing_count = max(0, count - len(filtered_questions))
        if missing_count:
            fallback = await svc.get_practice_questions(
                db=db,
                user_id=current_user.id,
                subject_code=subject_for_query,
                subject_ids=scope_subject_ids,
                count=min(100, missing_count + len(filtered_questions)),
                mode="random",
                knowledge_points=kps,
                knowledge_point_ids=knowledge_point_ids,
                exclude_answered=exclude_answered,
                no_repeat_days=no_repeat_days,
                use_leitner=True,
            )
            fallback_due_ids = await get_due_question_ids(
                db, current_user.id, [int(question.id) for question in fallback]
            )
            existing_ids = {int(question.id) for question in filtered_questions}
            for question in fallback:
                if (
                    int(question.id) in fallback_due_ids
                    and int(question.id) not in existing_ids
                ):
                    filtered_questions.append(question)
                    existing_ids.add(int(question.id))
                if len(filtered_questions) >= count:
                    break
        questions = filtered_questions[:count]
    # ── 作用域强制过滤：同时校验 mutable Question 与将实际下发的 current revision。
    # 候选查询大多按 questions.subject_id 过滤，但响应内容来自 QuestionVersion。
    # 两者若因历史修复/并发编辑短暂不一致，旧逻辑仍可能把其他学科的 revision
    # 发给客户端。签发 batch token 前做最后一次不可变版本校验。
    latest_revision_ids = await svc.load_latest_question_revision_ids(
        db, [int(question.id) for question in questions]
    )
    questions = await svc.filter_questions_to_revision_scope(
        db,
        questions,
        scope_subject_ids,
        revision_ids=latest_revision_ids,
    )
    scope_set = set(scope_subject_ids)
    # Preserve ranking/order while guaranteeing a qid appears at most once.  A
    # duplicate can surface when multiple recommendation/fallback sources merge;
    # signing it would create a batch that the stricter submit validator rejects.
    deduped_questions = []
    seen_question_ids: set[int] = set()
    duplicate_question_ids: list[int] = []
    for question in questions:
        question_id = int(question.id)
        if question_id in seen_question_ids:
            duplicate_question_ids.append(question_id)
            continue
        seen_question_ids.add(question_id)
        if question.subject_id in scope_set:
            deduped_questions.append(question)
    if duplicate_question_ids:
        logger.warning(
            "[PRACTICE_DUPLICATE_CANDIDATE] subject_id=%s mode=%s duplicate_ids=%s",
            subject_id,
            mode,
            sorted(set(duplicate_question_ids)),
        )
    questions = deduped_questions[:count]
    if targeted_question_ids:
        # A targeted retry is an explicit immutable set.  If a question is
        # disabled or its current revision leaves the scope between the initial
        # load and this final guard, reject the whole request instead of issuing
        # a silently shortened batch that no longer matches the client snapshot.
        final_targeted_ids = [int(question.id) for question in questions]
        if final_targeted_ids != targeted_question_ids:
            missing_ids = [
                qid
                for qid in targeted_question_ids
                if qid not in set(final_targeted_ids)
            ]
            raise HTTPException(
                status_code=409,
                detail=f"定向题目在签发前已失效或超出当前科目范围: {missing_ids}",
            )
    final_question_ids = {int(q.id) for q in questions}
    question_metadata = {
        k: v for k, v in question_metadata.items() if int(k) in final_question_ids
    }
    # Recommendation services can log their candidate list before this final
    # revision/scope guard.  Retain only exposure rows for questions that are
    # actually present in the signed batch so analytics never records phantom
    # "shown" questions.  request_id is per-practice-request, so pruning is local.
    if request_id and mode in {"smart", "similar"}:
        try:
            from app.services import recommendation_log_service

            await recommendation_log_service.retain_recommendation_logs_for_questions(
                db,
                user_id=current_user.id,
                request_id=request_id,
                question_ids=final_question_ids,
            )
        except Exception:
            logger.warning(
                "推荐日志最终题目集合对齐失败 request_id=%s",
                request_id,
                exc_info=True,
            )
    # ── 结构化日志：刷题请求范围与分布 ──
    scope_desc = "聚合" if len(scope_subject_ids) > 1 else "精确"
    from collections import Counter

    subject_distribution = dict(Counter(q.subject_id for q in questions))
    logger.info(
        "[PRACTICE_SCOPE] subject_id=%s subject_code=%s include_children=%s "
        "include_descendants=%s knowledge_scope_size=%d has_children=%s "
        "scope=%s scope_ids=%s mode=%s count=%d result_count=%d subject_distribution=%s",
        subject_id,
        subject_code,
        include_children,
        include_descendants,
        len(knowledge_point_ids or []),
        has_enabled_children,
        scope_desc,
        scope_subject_ids,
        mode,
        count,
        len(questions),
        subject_distribution,
    )
    # Freeze the response from the exact immutable revisions signed into the
    # batch. A mutable Question/KP edit committed between candidate selection and
    # response serialization can therefore never create a mixed-version payload.
    # For knowledge-scoped practice, snapshot the user's pre-practice state in the
    # signed token so the result page can later show an exact before/after impact
    # without introducing a second chapter-mastery persistence table.
    from app.services.practice.knowledge_session_summary import (
        build_issue_knowledge_context,
    )

    knowledge_context = await build_issue_knowledge_context(
        db,
        user_id=current_user.id,
        knowledge_scope=knowledge_scope,
        questions=questions,
        revision_ids=latest_revision_ids,
    )

    # Home today-plan attribution is accepted only from a valid server-issued token
    # that still matches the actual practice request.  Users may edit the config
    # page; a mismatch simply drops attribution and never blocks normal practice.
    entry_context = None
    if plan_token:
        from app.services.study_hub_plan_token import validate_plan_task_token

        entry_context = validate_plan_task_token(
            plan_token,
            user_id=current_user.id,
            subject_id=subject_id,
            mode=mode,
            count=count,
            knowledge_point_id=knowledge_point_id,
            include_descendants=include_descendants,
            question_ids=question_ids,
        )
        if entry_context is None:
            logger.info(
                "[STUDY_HUB_PLAN_ATTRIBUTION_SKIPPED] user_id=%s subject_id=%s mode=%s",
                current_user.id,
                subject_id,
                mode,
            )

    sequential_submission_request_id = None
    if sequential_reservation_request_id:
        scope_identity = (
            {"knowledge_scope": knowledge_scope}
            if knowledge_scope is not None
            else {"knowledge_points": sorted(kps or [])}
        )
        sequential_submission_request_id = _sequential_submission_request_id(
            sequential_reservation_request_id,
            subject_id,
            scope_identity,
        )
    batch_token, issued_revisions, submission_request_id = (
        svc.create_practice_batch_token(
            user_id=current_user.id,
            subject_id=subject_id,
            mode=mode,
            questions=questions,
            revision_ids=latest_revision_ids,
            recommendation_request_id=request_id,
            knowledge_context=knowledge_context,
            entry_context=entry_context,
            sequential_reservation_request_id=sequential_reservation_request_id,
            submission_request_id=sequential_submission_request_id,
        )
    )
    revision_views = await load_revision_views(db, issued_revisions.values())
    revision_kps = await load_revision_kp_names(db, issued_revisions.values())
    issued_rows = []
    for selected in questions:
        revision_id = issued_revisions.get(int(selected.id))
        revision = revision_views.get(int(revision_id or 0))
        if revision is None or int(revision.question_id) != int(selected.id):
            raise HTTPException(
                status_code=500, detail="题目版本数据不完整，请稍后重试"
            )
        issued_rows.append((selected, revision))

        content = _sanitize_question_content(revision.content)
        stem = (content or {}).get("text") or (content or {}).get("stem") or ""
        logger.info(
            "[API_LAYER] qid=%s revision_id=%s textLen=%d textHash=%s stemKeys=%s",
            selected.id,
            revision_id,
            len(stem),
            hashlib.sha256(stem.encode()).hexdigest()[:8],
            [k for k in (content or {}) if k in ("text", "stem", "segments")],
        )

    response = PracticeQuestionsResponse(
        questions=[
            PracticeQuestion(
                id=revision.question_id,
                question_version_id=revision.question_version_id,
                question_version=revision.version,
                subject_id=revision.subject_id,
                subject_code=revision.subject_ref.code if revision.subject_ref else "",
                subject_name=revision.subject_ref.name if revision.subject_ref else "",
                question_type=revision.question_type,
                content=_sanitize_question_content(revision.content),
                options=_sanitize_question_options(
                    _ensure_true_false_options(revision.question_type, revision.options)
                ),
                knowledge_points=revision_kps.get(revision.question_version_id, []),
                difficulty=revision.difficulty,
                image_url=revision.image_url,
                trace_id=trace_id,
                recommend_reason=(question_metadata.get(selected.id) or {}).get(
                    "recommend_reason"
                ),
                recommend_score=(question_metadata.get(selected.id) or {}).get(
                    "recommend_score"
                ),
                strategy=(question_metadata.get(selected.id) or {}).get("strategy"),
                similarity=(question_metadata.get(selected.id) or {}).get("similarity"),
            )
            for selected, revision in issued_rows
        ],
        total=len(questions),
        mode=mode,
        trace_id=trace_id,
        request_id=request_id,
        sequential_progress=sequential_progress,
        knowledge_scope=(
            {
                "root_knowledge_point_id": int(knowledge_scope["root_id"]),
                "root_name": str(knowledge_scope["root_name"]),
                "include_descendants": bool(knowledge_scope["include_descendants"]),
                "knowledge_point_count": len(knowledge_scope["knowledge_point_ids"]),
            }
            if knowledge_scope is not None
            else None
        ),
        batch_token=batch_token,
        submission_request_id=submission_request_id,
    )
    debug_log(
        trace_id,
        "API_RESPONSE",
        {
            "endpoint": "practice/questions",
            "subject_id": subject_id,
            "count": len(questions),
        },
    )
    save_debug_snapshot(
        trace_id,
        "api_response",
        {
            "endpoint": "practice/questions",
            "subject_id": subject_id,
            "question_ids": [q.id for q in questions],
            "total": len(questions),
        },
    )
    if mode == "sequential":
        # A revision/scope guard may remove a question after reservation.  Do
        # not leave a lease for an item that was never included in the signed
        # response; the whole cleanup remains in this request transaction.
        await db.execute(
            delete(SequentialReservation).where(
                SequentialReservation.user_id == current_user.id,
                SequentialReservation.subject_id == subject_id,
                SequentialReservation.start_request_id
                == sequential_reservation_request_id,
                SequentialReservation.question_id.notin_(final_question_ids),
            )
        )
        # Reservation writes are intentionally committed only after the full
        # response has been assembled. Any exception before this point causes
        # the request transaction to roll back and leaves no ghost claims.
        await db.commit()
    return response


@router.post(
    "/sequential/reset",
    response_model=SequentialPracticeResetResponse,
)
async def reset_sequential_practice(
    data: SequentialPracticeResetRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """完成一轮后显式开始新的顺序刷题轮次。"""
    resolved = await svc.resolve_subject_id_to_code(db, data.subject_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail="科目不存在")

    has_enabled_children, scope_subject_ids = await svc.resolve_practice_subject_scope(
        db,
        data.subject_id,
        include_children=False,
    )
    if has_enabled_children or len(scope_subject_ids) != 1:
        raise HTTPException(
            status_code=400,
            detail="顺序练习仅支持具体科目，不支持父级科目聚合刷题",
        )

    await svc.reset_sequential_progress(
        db,
        user_id=current_user.id,
        subject_id=data.subject_id,
    )
    return SequentialPracticeResetResponse(subject_id=data.subject_id, reset=True)


@router.post("/batch-submit", response_model=BatchSubmitResponse)
async def batch_submit(
    data: BatchSubmitRequest,
    x_trace_id: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    trace_id = str(get_log_context().get("trace_id") or normalize_trace_id(x_trace_id))
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
            session_meta=data.session.model_dump()
            if data.session is not None
            else None,
            skipped_question_ids=data.skipped_question_ids,
            batch_token=data.batch_token,
        )
    except svc.PracticeBatchTokenError as e:
        logger.warning(
            "practice submit batch token rejected uid=%s trace_id=%s: %s",
            current_user.id,
            trace_id,
            e,
        )
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "PRACTICE_BATCH_INVALID",
                "retryable": False,
            },
        )
    except svc.PracticeSubmissionConflictError as e:
        logger.warning(
            "practice submit idempotency conflict uid=%s trace_id=%s: %s",
            current_user.id,
            trace_id,
            e,
        )
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "PRACTICE_SUBMISSION_CONFLICT",
                "retryable": False,
            },
        )
    except ValueError as e:
        logger.warning(
            "practice submit payload rejected uid=%s trace_id=%s: %s",
            current_user.id,
            trace_id,
            e,
        )
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "PRACTICE_PAYLOAD_INVALID",
                "retryable": False,
            },
        )

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
            "total_skipped": result.get("total_skipped", 0),
            "result_count": len(result["results"]),
        },
    )
    return BatchSubmitResponse(
        results=[AnswerResult(**r) for r in result["results"]],
        total_correct=result["total_correct"],
        total_wrong=result["total_wrong"],
        total_skipped=result.get("total_skipped", 0),
        trace_id=trace_id,
        knowledge_session=result.get("knowledge_session"),
    )


@router.get("/session/scope", response_model=PracticeSessionScopeResponse)
async def get_practice_session_scope_snapshot(
    request_id: str = Query(..., min_length=1, max_length=128),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the immutable semantic scope persisted for a completed batch."""
    from app.services.practice.session_scope import get_practice_session_scope

    found, scope = await get_practice_session_scope(
        db,
        user_id=current_user.id,
        request_id=request_id,
    )
    if not found:
        raise HTTPException(status_code=404, detail="练习会话不存在")
    return PracticeSessionScopeResponse(request_id=request_id, scope=scope)


@router.get(
    "/session/knowledge-summary", response_model=PracticeKnowledgeSummaryResponse
)
async def get_practice_session_knowledge_summary(
    request_id: str = Query(..., min_length=1, max_length=128),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return post-projection knowledge impact for one completed practice session.

    The endpoint deliberately reports ``processing`` while answer-projection outbox
    tasks are pending, so the result UI never presents stale mastery values as final.
    """
    from app.services.practice.knowledge_session_summary import (
        get_session_knowledge_summary,
    )

    summary = await get_session_knowledge_summary(
        db,
        user_id=current_user.id,
        request_id=request_id,
    )
    if summary is None:
        raise HTTPException(status_code=404, detail="练习会话不存在")
    return PracticeKnowledgeSummaryResponse(**summary)


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
    subject_id: int | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from sqlalchemy import and_, func, select

    from app.models.admin import Subject
    from app.models.practice_record import PracticeRecord as PR

    conds = [PR.user_id == current_user.id]
    if subject_id:
        conds.append(PR.subject_id == subject_id)

    total = (await db.execute(select(func.count(PR.id)).where(and_(*conds)))).scalar()

    rows = await db.execute(
        select(
            PR.id,
            PR.question_id,
            PR.subject_id,
            Subject.code.label("subject_code"),
            Subject.name.label("subject_name"),
            PR.question_type,
            PR.user_answer,
            PR.is_correct,
            PR.used_time,
            PR.answered_at,
        )
        .outerjoin(Subject, Subject.id == PR.subject_id)
        .where(and_(*conds))
        .order_by(PR.answered_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = rows.all()

    return paginated_response(
        items=[
            PracticeRecordItem(
                id=r.id,
                question_id=r.question_id,
                subject_id=r.subject_id,
                subject_code=r.subject_code or "",
                subject_name=r.subject_name or "",
                question_type=r.question_type,
                user_answer=r.user_answer,
                is_correct=r.is_correct,
                used_time=r.used_time,
                answered_at=r.answered_at,
            )
            for r in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


# ── V3: 知识点掌握度查询接口 ──


@router.get("/knowledge-states")
async def get_knowledge_states(
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询当前用户所有知识点掌握状态。

    可选 status 过滤：weak / normal / good / mastered / observing / possible_weak / possible_mastered。
    """
    from sqlalchemy import select as sa_select

    # 获取所有科目的状态（跨科目汇总）
    # 先获取用户有记录的科目列表
    from app.models.user_knowledge_state import UserKnowledgeState
    from app.services import mastery_service

    subjects_result = await db.execute(
        sa_select(UserKnowledgeState.subject_id)
        .where(UserKnowledgeState.user_id == current_user.id)
        .distinct()
    )
    subjects = [row[0] for row in subjects_result.all()]

    all_items = []
    for subject_id in subjects:
        states = await mastery_service.get_user_knowledge_states(
            db,
            current_user.id,
            subject_id,
        )
        all_items.extend(states)

    # status 过滤
    if status:
        all_items = [item for item in all_items if item.get("weakness_level") == status]

    # 按 mastery_score 升序
    all_items.sort(key=lambda x: x.get("mastery_score", 50))

    # 限制数量
    all_items = all_items[:limit]

    # 转换为 Schema
    from app.schemas.mastery import KnowledgeStateItem, KnowledgeStateListResponse

    items = [
        KnowledgeStateItem(
            knowledge_point_id=item.get("knowledge_point_id"),
            knowledge_point=item.get("name", ""),
            mastery_score=item.get("mastery_score", 50.0),
            confidence=item.get("confidence", 0.0),
            label=item.get("weakness_level", "observing"),
            answer_count=item.get("attempt_count", 0),
            correct_count=item.get("correct_count", 0),
            wrong_count=item.get("wrong_count", 0),
            recent_wrong_count=item.get("recent_wrong_count", 0),
            last_practiced_at=item.get("last_practiced_at"),
        )
        for item in all_items
    ]

    return KnowledgeStateListResponse(items=items, total=len(items))


@router.get("/weak-knowledge-points")
async def get_weak_knowledge_points(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询用户明确薄弱的知识点（mastery_score < 40 且 confidence >= 0.3）。

    主要为 V4 智能推荐提供数据基础。
    """
    from sqlalchemy import select as sa_select

    from app.models.user_knowledge_state import UserKnowledgeState
    from app.services import mastery_service

    # 获取用户有记录的科目
    subjects_result = await db.execute(
        sa_select(UserKnowledgeState.subject_id)
        .where(UserKnowledgeState.user_id == current_user.id)
        .distinct()
    )
    subjects = [row[0] for row in subjects_result.all()]

    all_weak = []
    for subject_id in subjects:
        weak = await mastery_service.get_user_weak_knowledge_points(
            db,
            current_user.id,
            subject_id,
            limit=limit,
        )
        all_weak.extend(weak)

    # 过滤：只保留 mastery_score < 40 且 confidence >= 0.3
    all_weak = [
        item
        for item in all_weak
        if item.get("mastery_score", 50) < 40 and item.get("confidence", 0) >= 0.3
    ]

    # 排序：mastery_score ASC, recent_wrong_count DESC
    all_weak.sort(
        key=lambda x: (x.get("mastery_score", 50), -x.get("attempt_count", 0))
    )
    all_weak = all_weak[:limit]

    from app.schemas.mastery import KnowledgeStateItem, KnowledgeStateListResponse

    items = [
        KnowledgeStateItem(
            knowledge_point_id=item.get("knowledge_point_id"),
            knowledge_point=item.get("name", ""),
            mastery_score=item.get("mastery_score", 50.0),
            confidence=item.get("confidence", 0.0),
            label=item.get("weakness_level", "weak"),
            answer_count=item.get("attempt_count", 0),
            correct_count=item.get("correct_count", 0)
            if isinstance(item.get("correct_count"), int)
            else round(item.get("accuracy", 0) * item.get("attempt_count", 0)),
            wrong_count=item.get("wrong_count", 0)
            if isinstance(item.get("wrong_count"), int)
            else item.get("attempt_count", 0)
            - round(item.get("accuracy", 0) * item.get("attempt_count", 0)),
            recent_wrong_count=item.get("recent_wrong_count", 0),
        )
        for item in all_weak
    ]

    return KnowledgeStateListResponse(items=items, total=len(items))
