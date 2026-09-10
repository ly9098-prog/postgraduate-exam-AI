from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from datetime import timedelta
from typing import Iterable

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.gateway import chat_with_db_model
from app.core.time_utils import utcnow
from app.models.admin import QuestionVersion, QuestionVersionKnowledgePoint, Subject
from app.models.error_diagnosis import WrongQuestionErrorDiagnosis
from app.models.knowledge_point import KnowledgePoint
from app.models.syllabus import SyllabusKnowledgePoint
from app.models.wrong_question import WrongQuestion
from app.services.question_revision_service import load_revision_kp_names

logger = logging.getLogger(__name__)

TAXONOMY_VERSION = "408-error-v1"
TASK_TYPE_ERROR_DIAGNOSIS = "error_diagnosis"
ERROR_TYPES = (
    "knowledge_gap",
    "concept_confusion",
    "memory_error",
    "calculation_error",
    "misread",
    "reasoning_error",
    "time_pressure",
    "careless",
    "unknown",
)
ERROR_TYPE_SET = frozenset(ERROR_TYPES)
ERROR_LABELS = {
    "knowledge_gap": "知识点不会",
    "concept_confusion": "概念混淆",
    "memory_error": "记忆错误",
    "calculation_error": "计算错误",
    "misread": "审题错误",
    "reasoning_error": "推理/算法思路错误",
    "time_pressure": "时间不足",
    "careless": "粗心",
    "unknown": "暂未分类",
}
ERROR_DESCRIPTIONS = {
    "knowledge_gap": "缺少完成本题所需的知识、规则或方法。",
    "concept_confusion": "知道相关知识，但混淆了相近概念、条件或边界。",
    "memory_error": "定义、公式、结论或协议规则记忆不准确。",
    "calculation_error": "方法基本正确，但计算、代入、位运算或数值处理出错。",
    "misread": "遗漏题干条件、否定词、单位、范围或选项限定。",
    "reasoning_error": "知识点已知，但推理链、算法过程或解题路径存在错误。",
    "time_pressure": "受限于考试或练习时间，未能完成充分判断。",
    "careless": "非知识性失误，例如误点、抄错、看错选项或操作疏忽。",
    "unknown": "当前证据不足，暂不做确定分类。",
}

LEGACY_TYPE_MAP = {
    "knowledge_gap": "knowledge_gap",
    "concept_confusion": "concept_confusion",
    "memory_error": "memory_error",
    "calculation_error": "calculation_error",
    "misread": "misread",
    "reasoning_error": "reasoning_error",
    "time_pressure": "time_pressure",
    "careless": "careless",
    "unknown": "unknown",
    "concept_mistake": "concept_confusion",
    "concept": "concept_confusion",
    "calculation": "calculation_error",
    "memory": "memory_error",
    "method": "reasoning_error",
    "logic": "reasoning_error",
    "other": "unknown",
    "": "unknown",
}


def taxonomy_items() -> list[dict]:
    return [
        {
            "type": error_type,
            "label": ERROR_LABELS[error_type],
            "description": ERROR_DESCRIPTIONS[error_type],
        }
        for error_type in ERROR_TYPES
    ]


def normalize_error_type(value: object, *, allow_unknown: bool = True) -> str:
    raw = str(value or "").strip()
    normalized = LEGACY_TYPE_MAP.get(raw, raw)
    if normalized not in ERROR_TYPE_SET:
        if allow_unknown:
            return "unknown"
        raise ValueError("unsupported error diagnosis type")
    return normalized


def normalize_secondary_types(values: object, primary: str | None = None) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    result: list[str] = []
    for raw in values:
        value = normalize_error_type(raw)
        if value == "unknown" or value == primary or value in result:
            continue
        result.append(value)
        if len(result) >= 3:
            break
    return result


def effective_primary(row: WrongQuestionErrorDiagnosis) -> str:
    if row.user_confirmed_at and row.user_primary_type:
        return normalize_error_type(row.user_primary_type)
    if row.ai_status == "suggested" and row.ai_primary_type:
        return normalize_error_type(row.ai_primary_type)
    return "unknown"


def effective_secondary(row: WrongQuestionErrorDiagnosis) -> list[str]:
    primary = effective_primary(row)
    if row.user_confirmed_at and row.user_primary_type:
        return normalize_secondary_types(row.user_secondary_types, primary)
    if row.ai_status == "suggested" and row.ai_primary_type:
        return normalize_secondary_types(row.ai_secondary_types, primary)
    return []


def serialize_diagnosis(row: WrongQuestionErrorDiagnosis) -> dict:
    primary = effective_primary(row)
    secondary = effective_secondary(row)
    ai_primary = normalize_error_type(row.ai_primary_type) if row.ai_primary_type else None
    ai_secondary = normalize_secondary_types(row.ai_secondary_types, ai_primary)
    if row.user_confirmed_at and row.user_primary_type:
        source = "user"
    elif row.ai_status == "suggested" and row.ai_primary_type:
        source = "ai"
    else:
        source = "unknown"
    return {
        "id": int(row.id),
        "wrong_question_id": int(row.wrong_question_id),
        "question_id": int(row.question_id),
        "question_version_id": int(row.question_version_id),
        "practice_record_id": int(row.practice_record_id) if row.practice_record_id else None,
        "exam_answer_id": int(row.exam_answer_id) if row.exam_answer_id else None,
        "source_context": str(row.source_context),
        "occurred_at": row.occurred_at,
        "taxonomy_version": str(row.taxonomy_version or TAXONOMY_VERSION),
        "classification_version": int(row.classification_version or 1),
        "primary_type": primary,
        "primary_label": ERROR_LABELS[primary],
        "secondary_types": secondary,
        "secondary_labels": [ERROR_LABELS[item] for item in secondary],
        "effective_source": source,
        "user_confirmed": bool(row.user_confirmed_at and row.user_primary_type),
        "confirmed_at": row.user_confirmed_at,
        "ai_status": str(row.ai_status or "not_requested"),
        "ai_primary_type": ai_primary,
        "ai_primary_label": ERROR_LABELS.get(ai_primary) if ai_primary else None,
        "ai_secondary_types": ai_secondary,
        "ai_secondary_labels": [ERROR_LABELS[item] for item in ai_secondary],
        "ai_confidence": round(float(row.ai_confidence), 4) if row.ai_confidence is not None else None,
        "ai_reason": row.ai_reason,
        "ai_model": row.ai_model,
        "ai_suggested_at": row.ai_suggested_at,
    }


async def get_diagnosis_by_id(
    db: AsyncSession,
    user_id: int,
    diagnosis_id: int,
    *,
    lock: bool = False,
) -> WrongQuestionErrorDiagnosis | None:
    stmt = select(WrongQuestionErrorDiagnosis).where(
        WrongQuestionErrorDiagnosis.id == diagnosis_id,
        WrongQuestionErrorDiagnosis.user_id == user_id,
    )
    bind = db.get_bind()
    if lock and bind is not None and bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return await db.scalar(stmt)


async def get_latest_diagnosis(
    db: AsyncSession,
    user_id: int,
    wrong_question_id: int,
) -> WrongQuestionErrorDiagnosis | None:
    return await db.scalar(
        select(WrongQuestionErrorDiagnosis)
        .where(
            WrongQuestionErrorDiagnosis.user_id == user_id,
            WrongQuestionErrorDiagnosis.wrong_question_id == wrong_question_id,
        )
        .order_by(
            WrongQuestionErrorDiagnosis.occurred_at.desc(),
            WrongQuestionErrorDiagnosis.id.desc(),
        )
        .limit(1)
    )


async def ensure_legacy_diagnosis(
    db: AsyncSession,
    wq: WrongQuestion,
) -> WrongQuestionErrorDiagnosis:
    latest = await get_latest_diagnosis(db, int(wq.user_id), int(wq.id))
    if latest is not None:
        return latest
    legacy_type = normalize_error_type(wq.error_type)
    occurred_at = wq.last_review_at or wq.updated_at or wq.created_at or utcnow()
    row = WrongQuestionErrorDiagnosis(
        user_id=int(wq.user_id),
        wrong_question_id=int(wq.id),
        question_id=int(wq.question_id),
        question_version_id=int(wq.question_version_id),
        source_context="legacy",
        user_answer=wq.wrong_answer,
        occurred_at=occurred_at,
        taxonomy_version=TAXONOMY_VERSION,
        classification_version=1,
        ai_status="not_requested",
        user_primary_type=legacy_type if legacy_type != "unknown" else None,
        user_secondary_types=[],
        user_confirmed_at=occurred_at if legacy_type != "unknown" else None,
    )
    db.add(row)
    await db.flush()
    return row


async def _queue_diagnosis(
    db: AsyncSession,
    row: WrongQuestionErrorDiagnosis,
    *,
    request_suffix: str = "auto",
) -> bool:
    try:
        from app.services.outbox_service import create_outbox

        # Outbox enrichment is optional for the primary answer transaction.
        # Isolate its flush in a savepoint so a duplicate-key/storage failure
        # cannot leave the caller's session in a failed transaction state.
        async with db.begin_nested():
            await create_outbox(
                db,
                task_id=f"error_diagnosis:{row.id}:{row.classification_version}:{request_suffix}",
                task_type=TASK_TYPE_ERROR_DIAGNOSIS,
                payload={
                    "diagnosis_id": int(row.id),
                    "user_id": int(row.user_id),
                    "classification_version": int(row.classification_version or 1),
                },
                schema_version=1,
            )
        return True
    except ValueError:
        # A non-terminal task with the same deterministic id is already queued.
        return False
    except Exception:
        # The wrong answer itself is the primary transaction. Diagnosis queue
        # availability must never reject a valid practice/exam submission. Mark
        # the optional AI enrichment as failed so clients do not display an
        # endless `pending` state when no task was actually persisted.
        row.ai_status = "failed"
        row.ai_reason = "AI 错因建议暂未进入处理队列，可直接手动确认错因。"
        logger.warning(
            "error diagnosis outbox enqueue failed diagnosis_id=%s uid=%s",
            getattr(row, "id", None),
            getattr(row, "user_id", None),
            exc_info=True,
        )
        return False


async def record_error_event(
    db: AsyncSession,
    *,
    user_id: int,
    wrong_question_id: int,
    question_id: int,
    question_version_id: int,
    practice_record_id: int | None,
    source_context: str,
    user_answer: str | None,
    occurred_at=None,
    exam_answer_id: int | None = None,
    queue_ai: bool = False,
) -> WrongQuestionErrorDiagnosis:
    if practice_record_id:
        existing = await db.scalar(
            select(WrongQuestionErrorDiagnosis).where(
                WrongQuestionErrorDiagnosis.practice_record_id == practice_record_id
            )
        )
        if existing is not None:
            return existing
    if exam_answer_id:
        existing = await db.scalar(
            select(WrongQuestionErrorDiagnosis).where(
                WrongQuestionErrorDiagnosis.exam_answer_id == exam_answer_id
            )
        )
        if existing is not None:
            return existing

    row = WrongQuestionErrorDiagnosis(
        user_id=user_id,
        wrong_question_id=wrong_question_id,
        question_id=question_id,
        question_version_id=question_version_id,
        practice_record_id=practice_record_id,
        exam_answer_id=exam_answer_id,
        source_context=source_context,
        user_answer=user_answer,
        occurred_at=occurred_at or utcnow(),
        taxonomy_version=TAXONOMY_VERSION,
        classification_version=1,
        ai_status="pending" if queue_ai else "not_requested",
        user_secondary_types=[],
        ai_secondary_types=[],
    )
    try:
        # The source record/exam answer is the idempotency key for a diagnosis.
        # Keep the insert in a savepoint so a concurrent retry that wins the
        # unique constraint does not poison the caller's primary transaction.
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        existing = None
        if practice_record_id:
            existing = await db.scalar(
                select(WrongQuestionErrorDiagnosis).where(
                    WrongQuestionErrorDiagnosis.practice_record_id == practice_record_id
                )
            )
        if existing is None and exam_answer_id:
            existing = await db.scalar(
                select(WrongQuestionErrorDiagnosis).where(
                    WrongQuestionErrorDiagnosis.exam_answer_id == exam_answer_id
                )
            )
        if existing is not None:
            return existing
        raise

    if queue_ai:
        await _queue_diagnosis(db, row)
    return row


async def confirm_diagnosis(
    db: AsyncSession,
    *,
    user_id: int,
    wrong_question_id: int,
    primary_type: str,
    secondary_types: Iterable[str] = (),
    diagnosis_id: int | None = None,
) -> WrongQuestionErrorDiagnosis | None:
    wq = await db.scalar(
        select(WrongQuestion).where(
            WrongQuestion.id == wrong_question_id,
            WrongQuestion.user_id == user_id,
            WrongQuestion.is_active,
        )
    )
    if wq is None:
        return None

    if diagnosis_id is not None:
        row = await db.scalar(
            select(WrongQuestionErrorDiagnosis).where(
                WrongQuestionErrorDiagnosis.id == diagnosis_id,
                WrongQuestionErrorDiagnosis.user_id == user_id,
                WrongQuestionErrorDiagnosis.wrong_question_id == wrong_question_id,
            )
        )
        if row is None:
            return None
    else:
        row = await ensure_legacy_diagnosis(db, wq)

    primary = normalize_error_type(primary_type, allow_unknown=False)
    secondary = normalize_secondary_types(list(secondary_types), primary)
    now = utcnow()
    row.user_primary_type = primary
    row.user_secondary_types = secondary
    row.user_confirmed_at = now
    # classification_version tracks the AI suggestion generation. A learner
    # confirmation must not invalidate an already queued suggestion; the worker
    # may still finish, while effective diagnosis continues to prefer the user.
    # This also prevents a queued row from getting stuck in `pending` forever.
    # Maintain the legacy projection for older clients/stats while the fact table
    # remains the canonical source for the new feature.
    wq.error_type = primary
    await db.commit()
    await db.refresh(row)
    return row


async def request_ai_suggestion(
    db: AsyncSession,
    *,
    user_id: int,
    wrong_question_id: int,
) -> tuple[WrongQuestionErrorDiagnosis | None, bool]:
    wq = await db.scalar(
        select(WrongQuestion).where(
            WrongQuestion.id == wrong_question_id,
            WrongQuestion.user_id == user_id,
            WrongQuestion.is_active,
        )
    )
    if wq is None:
        return None, False
    row = await ensure_legacy_diagnosis(db, wq)
    # Two manual retries must allocate different classification versions;
    # otherwise they can generate the same deterministic outbox task id and one
    # request can fail/lost-update the version counter.
    locked = await get_diagnosis_by_id(db, user_id, int(row.id), lock=True)
    if locked is not None:
        row = locked
    row.ai_status = "pending"
    row.classification_version = int(row.classification_version or 1) + 1
    # Flush before task id construction. Commit here because this endpoint is a
    # standalone user action; the worker must be able to read the new version.
    await db.flush()
    queued = await _queue_diagnosis(db, row, request_suffix="manual")
    await db.commit()
    await db.refresh(row)
    return row, queued


def _extract_json_object(value: object) -> dict | None:
    text_value = str(value or "").strip()
    if not text_value:
        return None
    if text_value.startswith("```"):
        first_newline = text_value.find("\n")
        if first_newline >= 0:
            text_value = text_value[first_newline + 1 :]
        if text_value.endswith("```"):
            text_value = text_value[:-3].rstrip()
    left = text_value.find("{")
    right = text_value.rfind("}")
    if left >= 0 and right > left:
        text_value = text_value[left : right + 1]
    try:
        parsed = json.loads(text_value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _bounded_json(value: object, max_chars: int) -> str:
    try:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        raw = str(value or "")
    return raw[:max_chars]


async def generate_ai_suggestion(
    db: AsyncSession,
    *,
    user_id: int,
    diagnosis_id: int,
    expected_classification_version: int | None = None,
) -> dict:
    row = await get_diagnosis_by_id(db, user_id, diagnosis_id)
    if row is None:
        return {"processed": False, "missing": True}
    if (
        expected_classification_version is not None
        and int(row.classification_version or 1) != int(expected_classification_version)
    ):
        return {"processed": False, "stale": True}

    revision = await db.scalar(
        select(QuestionVersion).where(QuestionVersion.id == row.question_version_id)
    )
    wq = await db.scalar(
        select(WrongQuestion).where(
            WrongQuestion.id == row.wrong_question_id,
            WrongQuestion.user_id == user_id,
        )
    )
    if revision is None or wq is None:
        row.ai_status = "failed"
        row.ai_reason = "题目历史版本不可用，无法生成建议错因。"
        await db.commit()
        return {"processed": True, "suggested": False, "reason": "missing_revision"}

    kp_map = await load_revision_kp_names(db, [int(revision.id)])
    knowledge_points = kp_map.get(int(revision.id), [])
    taxonomy_text = "\n".join(
        f"- {key}: {ERROR_LABELS[key]} — {ERROR_DESCRIPTIONS[key]}"
        for key in ERROR_TYPES
    )
    messages = [
        {
            "role": "system",
            "content": (
                "你是 408 学习错因分类器。只做分类，不扩写讲解。"
                "必须基于题干、选项、正确答案、用户答案、解析和知识点证据判断；"
                "证据不足时 primary_type 必须为 unknown。用户最终确认会覆盖你的建议。\n"
                "允许的 taxonomy：\n" + taxonomy_text + "\n"
                "输出严格 JSON："
                '{"primary_type":"...","secondary_types":[],"confidence":0.0,'
                '"reason":"不超过80字的证据说明"}'
            ),
        },
        {
            "role": "user",
            "content": (
                "题干=" + _bounded_json(revision.content, 5000) + "\n"
                "选项=" + _bounded_json(revision.options, 3500) + "\n"
                "正确答案=" + str(revision.answer or "")[:500] + "\n"
                "用户答案=" + str(row.user_answer or "")[:500] + "\n"
                "解析=" + str(revision.analysis or "")[:5000] + "\n"
                "知识点=" + _bounded_json(knowledge_points, 1200)
            ),
        },
    ]

    try:
        response = await chat_with_db_model(
            db,
            messages,
            feature="analysis",
            temperature=0.0,
            timeout=35,
            max_tokens=320,
            response_format={"type": "json_object"},
            prefer_direct_answer=True,
        )
        if response is None:
            row.ai_status = "failed"
            row.ai_reason = "AI 分析模型未配置。"
            row.ai_model = None
            await db.commit()
            return {"processed": True, "suggested": False, "reason": "model_unconfigured"}

        parsed = _extract_json_object(response.get("content"))
        if parsed is None:
            raise ValueError("invalid_json")
        # Re-acquire the diagnosis row immediately before applying the AI result.
        # A manual retry can advance classification_version while the model call
        # is in flight; the old worker must never overwrite that newer state.
        current = await get_diagnosis_by_id(db, user_id, diagnosis_id, lock=True)
        if current is None:
            return {"processed": False, "missing": True}
        row = current
        if (
            expected_classification_version is not None
            and int(row.classification_version or 1) != int(expected_classification_version)
        ):
            return {"processed": False, "stale": True}
        primary = normalize_error_type(parsed.get("primary_type"))
        secondary = normalize_secondary_types(parsed.get("secondary_types"), primary)
        try:
            confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.0))))
        except (TypeError, ValueError):
            confidence = 0.0
        reason = str(parsed.get("reason") or "").strip()[:320]

        row.ai_primary_type = primary
        row.ai_secondary_types = secondary
        row.ai_confidence = confidence
        row.ai_reason = reason
        row.ai_status = "suggested"
        row.ai_model = str(response.get("model") or "")[:128] or None
        row.ai_suggested_at = utcnow()
        await db.commit()
        return {"processed": True, "suggested": True, "primary_type": primary}
    except Exception:
        logger.warning(
            "AI error diagnosis failed diagnosis_id=%s uid=%s",
            diagnosis_id,
            user_id,
            exc_info=True,
        )
        # The exception may come from a DB flush/commit, so reset the worker's
        # dedicated transaction before trying to persist failure state. More
        # importantly, an older failed worker must not turn a newer manual retry
        # from pending into failed.
        await db.rollback()
        current = await get_diagnosis_by_id(db, user_id, diagnosis_id, lock=True)
        if current is None:
            return {"processed": False, "missing": True}
        if (
            expected_classification_version is not None
            and int(current.classification_version or 1) != int(expected_classification_version)
        ):
            return {"processed": False, "stale": True}
        current.ai_status = "failed"
        current.ai_reason = "AI 分类暂不可用，可直接由用户手动确认错因。"
        current.ai_model = None
        await db.commit()
        return {"processed": True, "suggested": False, "reason": "ai_failed"}


def _effective_type_sql():
    return case(
        (
            WrongQuestionErrorDiagnosis.user_confirmed_at.is_not(None),
            WrongQuestionErrorDiagnosis.user_primary_type,
        ),
        (
            WrongQuestionErrorDiagnosis.ai_status == "suggested",
            WrongQuestionErrorDiagnosis.ai_primary_type,
        ),
        else_="unknown",
    )


def _effective_type_count_stmt(conditions):
    """Build a PostgreSQL-safe grouped effective-type count query.

    Repeating ``_effective_type_sql()`` independently in SELECT and GROUP BY
    creates distinct bind parameters for the CASE literals. PostgreSQL then no
    longer considers the two CASE expressions identical and raises GroupingError
    for ``user_confirmed_at``. Grouping a labeled subquery column avoids that
    dialect-specific ambiguity and remains valid on SQLite.
    """
    effective_type = _effective_type_sql().label("effective_type")
    source = (
        select(effective_type)
        .join(
            QuestionVersion,
            QuestionVersion.id == WrongQuestionErrorDiagnosis.question_version_id,
        )
        .where(*conditions)
        .subquery()
    )
    return select(source.c.effective_type, func.count()).group_by(source.c.effective_type)


async def get_stats(
    db: AsyncSession,
    *,
    user_id: int,
    window_days: int,
    allowed_subject_ids: set[int] | None = None,
    subject_id: int | None = None,
    knowledge_point_id: int | None = None,
) -> dict:
    now = utcnow()
    start = now - timedelta(days=window_days)
    previous_start = start - timedelta(days=window_days)
    effective_type = _effective_type_sql().label("effective_type")

    base_conditions = [
        WrongQuestionErrorDiagnosis.user_id == user_id,
        WrongQuestionErrorDiagnosis.occurred_at >= start,
    ]
    if allowed_subject_ids is not None:
        base_conditions.append(QuestionVersion.subject_id.in_(allowed_subject_ids))
    if subject_id is not None:
        base_conditions.append(QuestionVersion.subject_id == subject_id)
    if knowledge_point_id is not None:
        base_conditions.append(
            WrongQuestionErrorDiagnosis.question_version_id.in_(
                select(QuestionVersionKnowledgePoint.question_version_id).where(
                    QuestionVersionKnowledgePoint.knowledge_point_id == knowledge_point_id
                )
            )
        )

    rows = (
        await db.execute(
            select(
                WrongQuestionErrorDiagnosis.id,
                WrongQuestionErrorDiagnosis.question_version_id,
                WrongQuestionErrorDiagnosis.user_confirmed_at,
                QuestionVersion.subject_id,
                effective_type,
            )
            .join(
                QuestionVersion,
                QuestionVersion.id == WrongQuestionErrorDiagnosis.question_version_id,
            )
            .where(*base_conditions)
        )
    ).all()

    total = len(rows)
    type_counts: Counter[str] = Counter()
    type_confirmed: Counter[str] = Counter()
    subject_type_counts: dict[int, Counter[str]] = defaultdict(Counter)
    subject_totals: Counter[int] = Counter()
    revision_ids: list[int] = []
    for _id, revision_id, confirmed_at, subject_value, type_value in rows:
        error_type = normalize_error_type(type_value)
        type_counts[error_type] += 1
        if confirmed_at is not None:
            type_confirmed[error_type] += 1
        if subject_value is not None:
            sid = int(subject_value)
            subject_totals[sid] += 1
            subject_type_counts[sid][error_type] += 1
        revision_ids.append(int(revision_id))

    subject_rows = []
    if subject_totals:
        subjects = (
            await db.execute(select(Subject).where(Subject.id.in_(subject_totals.keys())))
        ).scalars().all()
        subject_map = {int(item.id): item for item in subjects}
        for sid, count in subject_totals.most_common():
            top_type, top_count = subject_type_counts[sid].most_common(1)[0]
            subject = subject_map.get(sid)
            subject_rows.append(
                {
                    "subject_id": sid,
                    "subject_code": str(subject.code or "") if subject else "",
                    "subject_name": str(subject.name or "") if subject else "",
                    "count": int(count),
                    "top_type": top_type,
                    "top_label": ERROR_LABELS[top_type],
                    "top_count": int(top_count),
                }
            )

    kp_rows: list[dict] = []
    if revision_ids:
        kp_data = (
            await db.execute(
                select(
                    QuestionVersionKnowledgePoint.question_version_id,
                    KnowledgePoint.id,
                    func.coalesce(SyllabusKnowledgePoint.name_snapshot, KnowledgePoint.name),
                )
                .join(
                    KnowledgePoint,
                    KnowledgePoint.id == QuestionVersionKnowledgePoint.knowledge_point_id,
                )
                .outerjoin(
                    SyllabusKnowledgePoint,
                    SyllabusKnowledgePoint.id == QuestionVersionKnowledgePoint.syllabus_knowledge_point_id,
                )
                .where(QuestionVersionKnowledgePoint.question_version_id.in_(set(revision_ids)))
            )
        ).all()
        row_by_revision: dict[int, list[str]] = defaultdict(list)
        for _id, revision_id, _confirmed_at, _subject, type_value in rows:
            row_by_revision[int(revision_id)].append(normalize_error_type(type_value))
        kp_totals: Counter[int] = Counter()
        kp_types: dict[int, Counter[str]] = defaultdict(Counter)
        kp_names: dict[int, str] = {}
        # One diagnosis can relate to multiple KPs; each KP receives one count
        # for that occurrence, which is the useful interpretation for a KP view.
        seen_pairs: set[tuple[int, int, int]] = set()
        for revision_id, kp_id, kp_name in kp_data:
            for ordinal, error_type in enumerate(row_by_revision.get(int(revision_id), [])):
                key = (int(revision_id), int(kp_id), ordinal)
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)
                kid = int(kp_id)
                kp_totals[kid] += 1
                kp_types[kid][error_type] += 1
                kp_names[kid] = str(kp_name)
        for kid, count in kp_totals.most_common(20):
            top_type, top_count = kp_types[kid].most_common(1)[0]
            kp_rows.append(
                {
                    "knowledge_point_id": kid,
                    "name": kp_names.get(kid, ""),
                    "count": int(count),
                    "top_type": top_type,
                    "top_label": ERROR_LABELS[top_type],
                    "top_count": int(top_count),
                }
            )

    previous_conditions = [
        WrongQuestionErrorDiagnosis.user_id == user_id,
        WrongQuestionErrorDiagnosis.occurred_at >= previous_start,
        WrongQuestionErrorDiagnosis.occurred_at < start,
    ]
    if allowed_subject_ids is not None:
        previous_conditions.append(QuestionVersion.subject_id.in_(allowed_subject_ids))
    if subject_id is not None:
        previous_conditions.append(QuestionVersion.subject_id == subject_id)
    if knowledge_point_id is not None:
        previous_conditions.append(
            WrongQuestionErrorDiagnosis.question_version_id.in_(
                select(QuestionVersionKnowledgePoint.question_version_id).where(
                    QuestionVersionKnowledgePoint.knowledge_point_id == knowledge_point_id
                )
            )
        )
    previous_rows = (
        await db.execute(_effective_type_count_stmt(previous_conditions))
    ).all()
    previous_counts = Counter(
        {normalize_error_type(error_type): int(count) for error_type, count in previous_rows}
    )

    by_type = []
    for error_type, count in type_counts.most_common():
        by_type.append(
            {
                "type": error_type,
                "label": ERROR_LABELS[error_type],
                "count": int(count),
                "percent": round(count / total, 4) if total else 0.0,
                "confirmed_count": int(type_confirmed[error_type]),
            }
        )

    changes = []
    all_change_types = set(type_counts) | set(previous_counts)
    for error_type in all_change_types:
        current_count = int(type_counts[error_type])
        previous_count = int(previous_counts[error_type])
        changes.append(
            {
                "type": error_type,
                "label": ERROR_LABELS[error_type],
                "current_count": current_count,
                "previous_count": previous_count,
                "delta": current_count - previous_count,
            }
        )
    changes.sort(key=lambda item: (abs(item["delta"]), item["current_count"]), reverse=True)

    confirmed_count = sum(type_confirmed.values())
    unknown_count = int(type_counts["unknown"])
    return {
        "taxonomy_version": TAXONOMY_VERSION,
        "window_days": window_days,
        "total_errors": total,
        "classified_count": max(0, total - unknown_count),
        "confirmed_count": int(confirmed_count),
        "unknown_count": unknown_count,
        "by_type": by_type,
        "by_subject": subject_rows,
        "by_knowledge_point": kp_rows,
        "changes": changes[:9],
    }
