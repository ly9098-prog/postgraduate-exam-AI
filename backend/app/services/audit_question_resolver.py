"""Resolve question detail from audit logs with backward compatibility.

Priority chain (highest first):
1. ``detail.question`` — full snapshot from new-format logs
2. ``detail.deleted_question`` — full snapshot from delete logs
3. ``detail.after`` — post-update state from old-format logs
4. ``detail.before`` — pre-update state from old-format logs (preferred for deletes)
5. ``detail.question_summary`` / ``detail_summary`` — summary-only
6. Current database — look up by ``resource_id`` (last resort)
"""
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import Subject
from app.models.question import Question
from app.schemas.admin_audit import QuestionAuditDetail


# ── Content text extraction ──

_CONTENT_TEXT_KEYS = ("text", "stem", "content", "question", "title", "value", "zh")


def extract_question_content_text(content: Any) -> str | None:
    """Extract readable text from question content in various formats."""
    if content is None:
        return None
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        for key in _CONTENT_TEXT_KEYS:
            val = content.get(key)
            if isinstance(val, str) and val.strip():
                return val
        # Fallback: return JSON
        import json
        return json.dumps(content, ensure_ascii=False)
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                val = item.get("value") or item.get("text") or item.get("type")
                if val:
                    parts.append(str(val))
            elif isinstance(item, str):
                parts.append(item)
        return " ".join(parts) if parts else None
    return str(content)


def _content_preview(content: Any, max_len: int = 200) -> str | None:
    text = extract_question_content_text(content)
    if text and len(text) > max_len:
        return text[:max_len]
    return text


# ── Resolver ──


def _pick_best_source(detail: dict) -> tuple[dict | None, str]:
    """Pick the best question data source from an audit log detail dict.

    Returns (question_dict, data_source_label).
    """
    # Priority 1: full snapshot
    for key in ("question", "deleted_question", "question_snapshot"):
        if key in detail and isinstance(detail[key], dict):
            return detail[key], "audit_snapshot"

    # Priority 2: after (post-update state)
    if "after" in detail and isinstance(detail["after"], dict):
        after = detail["after"]
        if "content" in after or "options" in after or "answer" in after:
            return after, "audit_after"

    # Priority 3: before (pre-update state, preferred for deletes)
    if "before" in detail and isinstance(detail["before"], dict):
        before = detail["before"]
        if "content" in before or "options" in before or "answer" in before:
            return before, "audit_before"

    # Priority 4: summary
    for key in ("question_summary", "question_summary"):
        if key in detail and isinstance(detail[key], dict):
            return detail[key], "audit_summary"

    return None, "audit_summary"


def _source_label(data_source: str) -> str:
    labels = {
        "audit_snapshot": "操作时快照",
        "audit_before": "操作前快照",
        "audit_after": "操作后快照",
        "audit_summary": "日志摘要",
        "current_database": "当前数据库",
    }
    return labels.get(data_source, data_source)


def _build_question_detail_from_dict(
    data: dict,
    data_source: str,
    question_id: int | None = None,
) -> QuestionAuditDetail:
    """Build a QuestionAuditDetail from a plain dict (extracted from audit log).

    Backward compatibility notes:
    - Old logs stored ``subject`` as a string code (e.g. ``"exam408-ds"``).
      New logs store ``subject_id`` as an integer.  We check both.
    """
    content = data.get("content")
    content_text = extract_question_content_text(content)
    content_preview = _content_preview(content)

    # Backward compatibility: old logs used "subject" (string code)
    subject_code = data.get("subject_code") or data.get("subject")

    return QuestionAuditDetail(
        id=data.get("id") or question_id,
        subject_id=data.get("subject_id"),
        subject_code=subject_code,
        subject_name=data.get("subject_name"),
        question_type=data.get("question_type"),
        content=content,
        content_text=content_text,
        content_preview=content_preview,
        options=data.get("options"),
        answer=data.get("answer"),
        analysis=data.get("analysis"),
        knowledge_points=data.get("knowledge_points"),
        difficulty=data.get("difficulty"),
        source=data.get("source"),
        source_type=data.get("source_type"),
        source_file=data.get("source_file"),
        year=data.get("year"),
        review_status=data.get("review_status"),
        is_active=data.get("is_active"),
        data_source=data_source,
    )


async def resolve_question_audit_detail(
    db: AsyncSession,
    audit_log_action: str,
    audit_log_resource_type: str | None,
    audit_log_resource_id: str | None,
    detail: dict | None,
) -> QuestionAuditDetail | None:
    """Resolve question detail for an audit log.

    Returns ``None`` only when this is not a question-related log
    and no resolution is possible.
    """
    # Only process question-related logs
    is_question = (
        audit_log_resource_type == "question"
        or (audit_log_action and audit_log_action.startswith("question."))
    )
    if not is_question:
        return None

    if not detail:
        detail = {}

    # Try to extract from log detail
    source_data, source = _pick_best_source(detail)

    if source_data:
        return _build_question_detail_from_dict(source_data, source)

    # Last resort: look up current question from DB
    if audit_log_resource_id and audit_log_resource_id.isdigit():
        qid = int(audit_log_resource_id)
        question = await db.get(Question, qid)
        if question:
            # Load subject
            subject_name = None
            subject_code = None
            if question.subject_id:
                subj = await db.get(Subject, question.subject_id)
                if subj:
                    subject_name = subj.name
                    subject_code = subj.code

            content = question.content
            content_text = extract_question_content_text(content)
            content_preview = _content_preview(content)

            return QuestionAuditDetail(
                id=question.id,
                subject_id=question.subject_id,
                subject_code=subject_code,
                subject_name=subject_name,
                question_type=question.question_type,
                content=content,
                content_text=content_text,
                content_preview=content_preview,
                options=question.options,
                answer=question.answer,
                analysis=question.analysis,
                knowledge_points=question.knowledge_points,
                difficulty=question.difficulty,
                source=question.source,
                source_type=question.source_type,
                source_file=question.source_file,
                year=question.year,
                review_status=question.review_status,
                is_active=question.is_active,
                data_source="current_database",
            )

    # Nothing found
    return None
