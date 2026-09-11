"""408 专项 AI 老师。

固定动作 + 固定题目版本 + 用户知识状态上下文。考试进行中 fail-closed，
避免通过通用 AI 端点绕过考试不展示答案/解析的产品边界。
"""

from __future__ import annotations

import json
import logging
import re
from collections import OrderedDict
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.gateway import chat_with_db_model
from app.ai.prompts_408_teacher import (
    ACTION_DEFINITIONS,
    PROMPT_VERSION,
    action_items,
    build_408_teacher_prompt,
)
from app.core.subject_scope import selected_408_subject_ids
from app.models.admin import QuestionVersion, QuestionVersionKnowledgePoint, Subject
from app.models.error_diagnosis import WrongQuestionErrorDiagnosis
from app.models.exam import ExamAnswer, ExamAttempt, ExamPaperQuestion
from app.models.knowledge_edge import KnowledgeEdge
from app.models.knowledge_point import KnowledgePoint
from app.models.practice_record import PracticeRecord
from app.models.question import Question
from app.models.user_knowledge_state import UserKnowledgeState
from app.services import error_diagnosis_service
from app.services.ai_learning_service import check_token_limit, record_token_usage

logger = logging.getLogger(__name__)


_RELATION_LABELS = {
    "prerequisite": "前置知识",
    "prerequisites": "前置知识",
    "prereq": "前置知识",
    "parent": "所属主题",
    "parent_node": "所属主题",
    "parent_topic": "所属主题",
    "next": "后续知识",
    "next_node": "后续知识",
    "next_nodes": "后续知识",
    "child": "下级知识",
    "children": "下级知识",
    "related": "相关知识",
    "related_node": "相关知识",
    "related_nodes": "相关知识",
    "sibling": "同层知识",
}

_METRIC_ASSIGNMENT_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_])(mastery(?:_score)?|confidence)\s*[:=]\s*(-?\d+(?:\.\d+)?%?)"
)


def _mastery_percent(raw_value: object) -> int | None:
    text = str(raw_value or "").strip()
    if not text:
        return None
    try:
        value = float(text[:-1] if text.endswith("%") else text)
    except (TypeError, ValueError):
        return None
    # UserKnowledgeState.mastery_score 的后端定义范围固定为 0-100。
    # 不把 0~1 猜成比例，避免 mastery_score=1 被误判成 100%。
    return max(0, min(100, round(value)))


def _mastery_status(raw_value: object) -> str:
    percent = _mastery_percent(raw_value)
    if percent is None:
        return ""
    if percent >= 85:
        return "掌握较好"
    if percent >= 60:
        return "基本掌握"
    if percent >= 40:
        return "还需巩固"
    return "建议优先复习"


def _evidence_status(confidence: object, attempt_count: object = 0) -> str:
    """把模型评估置信度转成教学语义，避免把原始 confidence 暴露给模型。"""
    try:
        value = float(confidence)
    except (TypeError, ValueError):
        value = -1.0
    try:
        attempts = max(0, int(attempt_count or 0))
    except (TypeError, ValueError):
        attempts = 0
    if value < 0 or attempts <= 0:
        return "暂无足够练习记录"
    if value < 0.3 or attempts < 2:
        return "评估依据较少"
    if value < 0.6 or attempts < 4:
        return "评估依据一般"
    return "评估依据较充分"


def _strip_edge_punctuation(text: str) -> str:
    return re.sub(r"^[\s,，;；|·:：-]+|[\s,，;；|·:：-]+$", "", text).strip()


def _replace_relation_tokens(text: str, *, include_colon: bool = True) -> str:
    separators = r"(?:→|->|=>|=|:|：)" if include_colon else r"(?:→|->|=>|=)"
    result = text
    for raw_key, label in _RELATION_LABELS.items():
        pattern = re.compile(
            rf"(?i)(?<![A-Za-z0-9_]){re.escape(raw_key)}(?![A-Za-z0-9_])\s*{separators}\s*"
        )
        result = pattern.sub(f"{label}：", result)
    return result


def _sanitize_user_text(value: object, limit: int = 1200) -> str:
    """清洗模型可见文本中的内部字段表达，同时尽量不碰正常学科术语。"""
    text = _clean_str(value, limit)
    if not text:
        return ""

    def replace_metric(match: re.Match[str]) -> str:
        key = match.group(1).lower()
        if key.startswith("mastery"):
            status = _mastery_status(match.group(2))
            return f"掌握情况：{status}" if status else "掌握情况"
        return ""

    text = _METRIC_ASSIGNMENT_RE.sub(replace_metric, text)
    # 关系枚举只有在呈现为键值/箭头格式时才替换，避免误伤如 "parent process" 这类学科术语。
    text = _replace_relation_tokens(text, include_colon=True)
    text = re.sub(
        r"(?i)(?<![A-Za-z0-9_])mastery_score(?![A-Za-z0-9_])", "掌握情况", text
    )
    text = re.sub(r"(?i)(?<![A-Za-z0-9_])mastery(?![A-Za-z0-9_])", "掌握情况", text)
    text = re.sub(r"(?i)(?<![A-Za-z0-9_])confidence(?![A-Za-z0-9_])", "评估依据", text)
    text = re.sub(r"\s*([,，;；])\s*[,，;；]+\s*", r"\1", text)
    text = re.sub(r"(?:^|[，,；;]\s*)评估依据\s*(?=$|[，,；;。])", "", text)
    return _strip_edge_punctuation(text)[:limit]


def _sanitize_relation_text(value: object, limit: int = 320) -> str:
    text = _clean_str(value, limit)
    if not text:
        return ""
    text = _replace_relation_tokens(text, include_colon=True)
    for raw_key, label in _RELATION_LABELS.items():
        pattern = re.compile(
            rf"(?i)(?<![A-Za-z0-9_]){re.escape(raw_key)}(?![A-Za-z0-9_])"
        )
        text = pattern.sub(label, text)
    text = _sanitize_user_text(text, limit)
    return text.replace(";", "；")


def _sanitize_mastery_hint(value: object, limit: int = 320) -> str:
    text = _clean_str(value, limit)
    if not text:
        return ""
    mastery_status = ""
    for match in _METRIC_ASSIGNMENT_RE.finditer(text):
        if match.group(1).lower().startswith("mastery"):
            mastery_status = _mastery_status(match.group(2))
            break
    text = _METRIC_ASSIGNMENT_RE.sub("", text)
    text = _sanitize_user_text(text, limit)
    if mastery_status and mastery_status not in text:
        text = f"{mastery_status}；{text}" if text else mastery_status
    return _strip_edge_punctuation(text)[:limit]


def _prompt_knowledge_context(knowledge_context: dict[str, Any]) -> dict[str, Any]:
    """生成仅供 AI 教学使用的去内部参数上下文。"""
    current_points: list[dict[str, Any]] = []
    for item in knowledge_context.get("knowledge_points") or []:
        current_points.append(
            {
                "名称": str(item.get("name") or ""),
                "学习状态": _mastery_status(item.get("mastery_score"))
                or "暂无稳定判断",
                "评估依据": _evidence_status(
                    item.get("confidence"), item.get("attempt_count")
                ),
                "练习次数": int(item.get("attempt_count") or 0),
                "近期错题次数": int(item.get("recent_wrong_count") or 0),
            }
        )

    weak_points: list[dict[str, Any]] = []
    for item in knowledge_context.get("weak_points") or []:
        weak_points.append(
            {
                "名称": str(item.get("name") or ""),
                "学习状态": _mastery_status(item.get("mastery_score")) or "还需巩固",
                "累计错题次数": int(item.get("wrong_count") or 0),
            }
        )

    recent_errors = [
        {
            "错因": str(item.get("error_label") or "暂未分类"),
            "发生时间": item.get("occurred_at"),
        }
        for item in knowledge_context.get("recent_same_kp_errors") or []
    ]

    graph_neighbors = [
        {
            "起点": str(item.get("source") or ""),
            "关系": _RELATION_LABELS.get(
                str(item.get("relation") or "").lower(), "相关知识"
            ),
            "终点": str(item.get("target") or ""),
        }
        for item in knowledge_context.get("knowledge_graph_neighbors") or []
    ]

    return {
        "本题知识点": current_points,
        "同科目薄弱知识": weak_points,
        "近期同知识点错因": recent_errors,
        "知识图谱邻居": graph_neighbors,
    }


class AIExamInProgressError(RuntimeError):
    pass


class AITeacher408AccessError(ValueError):
    pass


def get_actions() -> dict[str, Any]:
    return {"prompt_version": PROMPT_VERSION, "actions": action_items()}


def _stem_text(content: object) -> str:
    if isinstance(content, dict):
        value = content.get("text") or content.get("stem") or ""
        if value:
            return str(value)
        segments = content.get("segments")
        if isinstance(segments, list):
            parts: list[str] = []
            for item in segments:
                if isinstance(item, dict):
                    text_value = item.get("text") or item.get("content")
                    if text_value:
                        parts.append(str(text_value))
            return " ".join(parts)
    return str(content or "")


def _bounded(value: object, limit: int) -> object:
    if isinstance(value, str):
        return value[:limit]
    try:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return str(value or "")[:limit]
    if len(raw) <= limit:
        return value
    return raw[:limit]


def _parse_json_object(content: object) -> dict[str, Any] | None:
    text = str(content or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline >= 0:
            text = text[first_newline + 1 :]
        if text.endswith("```"):
            text = text[:-3].rstrip()
    left = text.find("{")
    right = text.rfind("}")
    if left >= 0 and right > left:
        text = text[left : right + 1]
    try:
        value = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _clean_str(value: object, limit: int = 1200) -> str:
    return str(value or "").strip()[:limit]


def _clean_points(
    value: object, *, max_items: int = 5, item_limit: int = 500
) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for raw in value:
        text = _clean_str(raw, item_limit)
        if text:
            result.append(text)
        if len(result) >= max_items:
            break
    return result


def _analysis_text_points(
    value: object, *, max_items: int = 5, item_limit: int = 800
) -> list[str]:
    if isinstance(value, list):
        result: list[str] = []
        for raw in value:
            if isinstance(raw, dict):
                preferred = (
                    raw.get("text")
                    or raw.get("content")
                    or raw.get("point")
                    or raw.get("description")
                )
                text = _clean_str(preferred, item_limit) if preferred else ""
            else:
                text = _clean_str(raw, item_limit)
            if text:
                result.append(text)
            if len(result) >= max_items:
                break
        return result
    if isinstance(value, dict):
        preferred = (
            value.get("text")
            or value.get("content")
            or value.get("summary")
            or value.get("description")
            or value.get("reason")
        )
        if preferred:
            return [_clean_str(preferred, item_limit)]
        result: list[str] = []
        for raw in value.values():
            if isinstance(raw, (str, int, float, bool)):
                text = _clean_str(raw, item_limit)
                if text:
                    result.append(text)
            if len(result) >= max_items:
                break
        return result
    text = _clean_str(value, item_limit)
    return [text] if text else []


def _structured_analysis_sections(value: object) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        parsed = value
    else:
        parsed = _parse_json_object(value)
    if not parsed:
        return []

    groups = (
        (
            (
                "mistake_diagnosis",
                "mistakeDiagnosis",
                "error_analysis",
                "diagnosis",
                "错因诊断",
            ),
            "错因诊断",
        ),
        (
            (
                "knowledge_patch",
                "knowledgePatch",
                "knowledge_weakness",
                "knowledgeGap",
                "知识补漏",
                "补漏重点",
            ),
            "知识补漏",
        ),
        (
            (
                "review_task",
                "reviewTask",
                "review_plan",
                "suggestion",
                "复练任务",
                "复习建议",
            ),
            "复练建议",
        ),
        (
            (
                "analysis",
                "explanation",
                "solution",
                "answer_analysis",
                "题目解析",
                "解析",
            ),
            "题目解析",
        ),
    )
    sections: list[dict[str, Any]] = []
    for keys, heading in groups:
        raw_value = None
        for key in keys:
            if key in parsed and parsed.get(key) not in (None, ""):
                raw_value = parsed.get(key)
                break
        points = _analysis_text_points(raw_value)
        if points:
            sections.append({"heading": heading, "points": points})

    if not sections:
        for key, raw_value in list(parsed.items())[:4]:
            points = _analysis_text_points(raw_value)
            if points:
                sections.append(
                    {
                        "heading": _clean_str(key, 120).replace("_", " "),
                        "points": points,
                    }
                )
    return sections[:8]


def _normalize_generated_question(value: object, action: str) -> dict[str, Any] | None:
    if action not in {"similar_question", "harder_question"}:
        return None
    if not isinstance(value, dict):
        return None
    options_raw = value.get("options")
    options: dict[str, str] = {}
    if isinstance(options_raw, dict):
        for key in ("A", "B", "C", "D"):
            text = _sanitize_user_text(options_raw.get(key), 800)
            if text:
                options[key] = text
    answer = _clean_str(value.get("answer"), 16).upper()
    if answer not in options:
        answer = ""
    stem = _sanitize_user_text(value.get("stem"), 3000)
    if not stem or len(options) < 2 or not answer:
        return None
    try:
        difficulty_delta = int(
            value.get("difficulty_delta", 1 if action == "harder_question" else 0)
        )
    except (TypeError, ValueError):
        difficulty_delta = 1 if action == "harder_question" else 0
    difficulty_delta = max(0, min(1, difficulty_delta))
    return {
        "stem": stem,
        "options": options,
        "answer": answer,
        "analysis": _sanitize_user_text(value.get("analysis"), 3000),
        "difficulty_delta": difficulty_delta,
    }


def _normalize_ai_payload(value: dict[str, Any], action: str) -> dict[str, Any]:
    sections: list[dict[str, Any]] = []
    summary_sections = _structured_analysis_sections(value.get("summary"))
    sections.extend(summary_sections)

    for raw in value.get("sections") or []:
        if not isinstance(raw, dict):
            continue
        heading = _sanitize_user_text(raw.get("heading"), 120)
        points: list[str] = []
        for point in raw.get("points") or []:
            nested = _structured_analysis_sections(point)
            if nested:
                sections.extend(nested)
                continue
            text = _sanitize_user_text(point, 500)
            if text:
                points.append(text)
            if len(points) >= 5:
                break
        if heading or points:
            if points:
                sections.append({"heading": heading, "points": points})
        if len(sections) >= 8:
            break

    deduped_sections: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for section in sections:
        heading = _sanitize_user_text(section.get("heading"), 120)
        points = [
            _sanitize_user_text(point, 500)
            for point in _analysis_text_points(
                section.get("points"), max_items=5, item_limit=500
            )
        ]
        points = [point for point in points if point]
        if not points:
            continue
        key = (heading, tuple(points))
        if key in seen:
            continue
        seen.add(key)
        deduped_sections.append({"heading": heading, "points": points})
        if len(deduped_sections) >= 8:
            break

    knowledge_points: list[dict[str, str]] = []
    for raw in value.get("knowledge_points") or []:
        if not isinstance(raw, dict):
            continue
        name = _sanitize_user_text(raw.get("name"), 128)
        if not name:
            continue
        knowledge_points.append(
            {
                "name": name,
                "relation": _sanitize_relation_text(raw.get("relation"), 320),
                "mastery_hint": _sanitize_mastery_hint(raw.get("mastery_hint"), 320),
            }
        )
        if len(knowledge_points) >= 8:
            break

    next_raw = (
        value.get("next_action") if isinstance(value.get("next_action"), dict) else {}
    )
    next_action = {
        "type": _clean_str(next_raw.get("type"), 64) or "none",
        "label": _sanitize_user_text(next_raw.get("label"), 128),
        "params": next_raw.get("params")
        if isinstance(next_raw.get("params"), dict)
        else {},
    }
    summary = _sanitize_user_text(value.get("summary"), 1200)
    if summary_sections:
        summary = _sanitize_user_text(summary_sections[0].get("points", [""])[0], 1200)
    elif _parse_json_object(summary):
        summary = deduped_sections[0]["points"][0] if deduped_sections else ""
    return {
        "title": _sanitize_user_text(value.get("title"), 160),
        "summary": summary,
        "sections": deduped_sections,
        "knowledge_points": knowledge_points,
        "practice_question": _normalize_generated_question(
            value.get("practice_question"), action
        ),
        "next_action": next_action,
    }


async def _active_408_subject_ids(db: AsyncSession) -> set[int]:
    subjects = list((await db.execute(select(Subject))).scalars().all())
    return selected_408_subject_ids(subjects)


async def active_exam_blocked_question_ids(
    db: AsyncSession,
    *,
    user_id: int,
    question_ids: list[int] | set[int] | tuple[int, ...],
) -> set[int]:
    """Return questions covered by any active exam attempt for this user."""
    normalized = {int(item) for item in question_ids if int(item) > 0}
    if not normalized:
        return set()
    rows = await db.execute(
        select(ExamPaperQuestion.question_id)
        .join(ExamAttempt, ExamAttempt.paper_id == ExamPaperQuestion.paper_id)
        .where(
            ExamAttempt.user_id == user_id,
            ExamAttempt.status == "in_progress",
            ExamPaperQuestion.question_id.in_(normalized),
        )
        .distinct()
    )
    return {int(item) for item in rows.scalars().all()}


async def assert_ai_answer_access_allowed(
    db: AsyncSession,
    *,
    user_id: int,
    question_id: int,
) -> None:
    """Block answer-bearing AI while this user has the question in an active exam.

    This guard is shared by the 408 teacher and all legacy answer-bearing AI
    routes so cached wrong-question analysis cannot be used as a bypass.
    """
    blocked = await active_exam_blocked_question_ids(
        db,
        user_id=user_id,
        question_ids=[question_id],
    )
    if int(question_id) in blocked:
        raise AIExamInProgressError(
            "考试进行中禁止调用会泄露答案或解析的 AI 能力，请交卷后再使用。"
        )


async def _resolve_exam_context(
    db: AsyncSession,
    *,
    user_id: int,
    question_id: int,
    exam_attempt_id: int | None,
) -> dict[str, Any]:
    if not exam_attempt_id:
        await assert_ai_answer_access_allowed(
            db, user_id=user_id, question_id=question_id
        )
        return {}

    attempt = await db.scalar(
        select(ExamAttempt).where(
            ExamAttempt.id == exam_attempt_id,
            ExamAttempt.user_id == user_id,
        )
    )
    if attempt is None:
        raise AITeacher408AccessError("考试记录不存在")
    item = await db.scalar(
        select(ExamPaperQuestion).where(
            ExamPaperQuestion.paper_id == attempt.paper_id,
            ExamPaperQuestion.question_id == question_id,
        )
    )
    if item is None:
        raise AITeacher408AccessError("该题不属于指定考试记录")
    if attempt.status == "in_progress":
        raise AIExamInProgressError(
            "考试进行中禁止调用会泄露答案或解析的 AI 能力，请交卷后再使用。"
        )
    if attempt.status == "abandoned":
        raise AITeacher408AccessError(
            "该考试尚未形成可复盘的交卷结果，暂不开放 AI 讲解。"
        )

    answer = await db.scalar(
        select(ExamAnswer).where(
            ExamAnswer.attempt_id == attempt.id,
            ExamAnswer.exam_paper_question_id == item.id,
        )
    )
    return {
        "attempt": attempt,
        "item": item,
        "answer": answer,
        "question_version_id": int(item.question_version_id),
    }


async def _resolve_revision_and_diagnosis(
    db: AsyncSession,
    *,
    user_id: int,
    question_id: int,
    requested_version_id: int | None,
    diagnosis_id: int | None,
    exam_context: dict[str, Any],
) -> tuple[Question, QuestionVersion, WrongQuestionErrorDiagnosis | None]:
    question = await db.scalar(select(Question).where(Question.id == question_id))
    if question is None:
        raise AITeacher408AccessError("题目不存在")

    diagnosis = None
    if diagnosis_id:
        diagnosis = await error_diagnosis_service.get_diagnosis_by_id(
            db, user_id, diagnosis_id
        )
        if diagnosis is None or int(diagnosis.question_id) != question_id:
            raise AITeacher408AccessError("错因记录不存在或与题目不匹配")

    # 历史考试/错题/练习复盘必须以固定版本为准，不能因为管理员后来
    # 将 Question 当前投影下架就丢失历史 AI 复盘能力。无用户历史事实时，
    # 仍要求题目当前可用，避免把下架题当作普通公开 AI 入口。
    has_owned_history = bool(exam_context) or diagnosis is not None
    if not question.is_active and not has_owned_history and requested_version_id:
        practice_fact = await db.scalar(
            select(PracticeRecord.id)
            .where(
                PracticeRecord.user_id == user_id,
                PracticeRecord.question_id == question_id,
                PracticeRecord.question_version_id == requested_version_id,
            )
            .limit(1)
        )
        has_owned_history = practice_fact is not None
    if not question.is_active and not has_owned_history:
        raise AITeacher408AccessError("题目当前不可用，且没有可验证的历史作答事实")

    allowed_subject_ids = await _active_408_subject_ids(db)

    exam_version_id = exam_context.get("question_version_id")
    diagnosis_version_id = (
        int(diagnosis.question_version_id) if diagnosis is not None else None
    )
    current_version_id = (
        int(question.current_version_id) if question.current_version_id else None
    )

    # An explicit version from the client is only a consistency assertion unless
    # the user can prove that exact historical revision belongs to one of their
    # own practice facts. This prevents authenticated users from enumerating old
    # unpublished/replaced revisions merely by guessing question_version_id.
    authoritative = next(
        (int(item) for item in (exam_version_id, diagnosis_version_id) if item),
        None,
    )
    if (
        authoritative
        and requested_version_id
        and int(requested_version_id) != authoritative
    ):
        raise AITeacher408AccessError("题目版本与当前复盘事实不一致")

    if authoritative is not None:
        version_id = authoritative
    elif requested_version_id is not None:
        requested = int(requested_version_id)
        if current_version_id is not None and requested == current_version_id:
            version_id = requested
        else:
            owned_practice_record_id = await db.scalar(
                select(PracticeRecord.id)
                .where(
                    PracticeRecord.user_id == user_id,
                    PracticeRecord.question_id == question_id,
                    PracticeRecord.question_version_id == requested,
                )
                .limit(1)
            )
            if owned_practice_record_id is None:
                raise AITeacher408AccessError(
                    "该历史题目版本不属于当前用户的可复盘记录"
                )
            version_id = requested
    else:
        version_id = current_version_id

    if version_id is None:
        raise AITeacher408AccessError("题目尚未冻结历史版本，暂不能用于 AI 复盘")

    revision = await db.scalar(
        select(QuestionVersion).where(
            QuestionVersion.id == version_id,
            QuestionVersion.question_id == question_id,
        )
    )
    if revision is None:
        raise AITeacher408AccessError("题目历史版本不存在")
    effective_subject_id = int(revision.subject_id or question.subject_id)
    if effective_subject_id not in allowed_subject_ids:
        raise AITeacher408AccessError("题目历史版本不属于当前启用的计算机专业课范围")
    return question, revision, diagnosis


async def _load_knowledge_context(
    db: AsyncSession,
    *,
    user_id: int,
    revision: QuestionVersion,
) -> dict[str, Any]:
    kp_rows = (
        (
            await db.execute(
                select(KnowledgePoint)
                .join(
                    QuestionVersionKnowledgePoint,
                    QuestionVersionKnowledgePoint.knowledge_point_id
                    == KnowledgePoint.id,
                )
                .where(QuestionVersionKnowledgePoint.question_version_id == revision.id)
                .order_by(
                    QuestionVersionKnowledgePoint.position.asc(),
                    KnowledgePoint.id.asc(),
                )
            )
        )
        .scalars()
        .all()
    )
    kp_ids = [int(item.id) for item in kp_rows]

    mastery_rows = []
    if kp_ids:
        mastery_rows = list(
            (
                await db.execute(
                    select(UserKnowledgeState).where(
                        UserKnowledgeState.user_id == user_id,
                        UserKnowledgeState.knowledge_point_id.in_(kp_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
    mastery_by_kp = {int(item.knowledge_point_id): item for item in mastery_rows}
    current_kps = []
    for kp in kp_rows:
        state = mastery_by_kp.get(int(kp.id))
        current_kps.append(
            {
                "id": int(kp.id),
                "name": str(kp.name),
                "mastery_score": round(float(state.mastery_score), 2)
                if state
                else None,
                "confidence": round(float(state.confidence), 4) if state else None,
                "attempt_count": int(state.attempt_count) if state else 0,
                "recent_wrong_count": int(state.recent_wrong_count) if state else 0,
                "weakness_level": str(state.weakness_level) if state else "unknown",
            }
        )

    weak_points = []
    if revision.subject_id is not None:
        weak_rows = (
            await db.execute(
                select(UserKnowledgeState, KnowledgePoint)
                .join(
                    KnowledgePoint,
                    KnowledgePoint.id == UserKnowledgeState.knowledge_point_id,
                )
                .where(
                    UserKnowledgeState.user_id == user_id,
                    UserKnowledgeState.subject_id == int(revision.subject_id),
                    UserKnowledgeState.attempt_count > 0,
                    KnowledgePoint.is_active,
                )
                .order_by(
                    UserKnowledgeState.mastery_score.asc(),
                    UserKnowledgeState.confidence.desc(),
                    UserKnowledgeState.wrong_count.desc(),
                )
                .limit(5)
            )
        ).all()
        weak_points = [
            {
                "id": int(kp.id),
                "name": str(kp.name),
                "mastery_score": round(float(state.mastery_score), 2),
                "confidence": round(float(state.confidence), 4),
                "wrong_count": int(state.wrong_count),
            }
            for state, kp in weak_rows
        ]

    recent_errors: list[dict[str, Any]] = []
    if kp_ids:
        rows = (
            (
                await db.execute(
                    select(WrongQuestionErrorDiagnosis)
                    .join(
                        QuestionVersionKnowledgePoint,
                        QuestionVersionKnowledgePoint.question_version_id
                        == WrongQuestionErrorDiagnosis.question_version_id,
                    )
                    .where(
                        WrongQuestionErrorDiagnosis.user_id == user_id,
                        QuestionVersionKnowledgePoint.knowledge_point_id.in_(kp_ids),
                    )
                    .order_by(
                        WrongQuestionErrorDiagnosis.occurred_at.desc(),
                        WrongQuestionErrorDiagnosis.id.desc(),
                    )
                    .limit(12)
                )
            )
            .scalars()
            .all()
        )
        deduped: OrderedDict[int, WrongQuestionErrorDiagnosis] = OrderedDict()
        for row in rows:
            deduped.setdefault(int(row.id), row)
            if len(deduped) >= 5:
                break
        for row in deduped.values():
            primary = error_diagnosis_service.effective_primary(row)
            recent_errors.append(
                {
                    "diagnosis_id": int(row.id),
                    "question_id": int(row.question_id),
                    "occurred_at": row.occurred_at.isoformat()
                    if row.occurred_at
                    else None,
                    "error_type": primary,
                    "error_label": error_diagnosis_service.ERROR_LABELS.get(
                        primary, "暂未分类"
                    ),
                    "source_context": str(row.source_context),
                }
            )

    graph_neighbors: list[dict[str, Any]] = []
    if kp_ids:
        edges = list(
            (
                await db.execute(
                    select(KnowledgeEdge)
                    .where(
                        KnowledgeEdge.is_active,
                        or_(
                            KnowledgeEdge.source_knowledge_point_id.in_(kp_ids),
                            KnowledgeEdge.target_knowledge_point_id.in_(kp_ids),
                        ),
                    )
                    .order_by(KnowledgeEdge.weight.desc(), KnowledgeEdge.id.asc())
                    .limit(20)
                )
            )
            .scalars()
            .all()
        )
        for edge in edges:
            source = edge.source_kp
            target = edge.target_kp
            if source is None or target is None:
                continue
            graph_neighbors.append(
                {
                    "source": str(source.name),
                    "relation": str(edge.relation_type),
                    "target": str(target.name),
                    "weight": round(float(edge.weight or 0), 3),
                }
            )
            if len(graph_neighbors) >= 12:
                break

    return {
        "knowledge_points": current_kps,
        "weak_points": weak_points,
        "recent_same_kp_errors": recent_errors,
        "knowledge_graph_neighbors": graph_neighbors,
    }


async def _latest_practice_context(
    db: AsyncSession,
    *,
    user_id: int,
    question_id: int,
    question_version_id: int,
) -> dict[str, Any]:
    row = await db.scalar(
        select(PracticeRecord)
        .where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.question_id == question_id,
            PracticeRecord.question_version_id == question_version_id,
        )
        .order_by(PracticeRecord.answered_at.desc(), PracticeRecord.id.desc())
        .limit(1)
    )
    if row is None:
        return {}
    return {
        "practice_record_id": int(row.id),
        "user_answer": str(row.user_answer or ""),
        "is_correct": bool(row.is_correct),
        "answered_at": row.answered_at.isoformat() if row.answered_at else None,
    }


def _fallback_payload(
    *,
    action: str,
    revision: QuestionVersion,
    knowledge_context: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    meta = ACTION_DEFINITIONS[action]
    kp_names = [
        str(item.get("name"))
        for item in knowledge_context.get("knowledge_points", [])
        if item.get("name")
    ]
    # 降级内容也必须遵守动作边界：不能因为专项动作失败，就把完整的
    # “错因/补漏/复练”报告再次塞回弹层。只有讲解类动作可引用一段题库
    # 解析；生成题与陷阱总结在没有可靠生成结果时明确告知不可用。
    explanation_actions = {"explain_correct", "explain_options", "core_concept"}
    summary = reason
    if action in explanation_actions and revision.analysis:
        structured = _structured_analysis_sections(revision.analysis)
        preferred = next(
            (item for item in structured if item.get("heading") == "题目解析"), None
        )
        if preferred is None and structured:
            preferred = structured[0]
        if preferred and preferred.get("points"):
            summary = _clean_str(preferred["points"][0], 1200)
        else:
            summary = _clean_str(revision.analysis, 1200) or reason
    return {
        "title": meta["label"],
        "summary": _sanitize_user_text(summary, 1200),
        "sections": [],
        "knowledge_points": [
            {"name": name, "relation": "本题知识点", "mastery_hint": ""}
            for name in kp_names[:6]
        ]
        if action == "connect_knowledge"
        else [],
        "practice_question": None,
        "next_action": {"type": "none", "label": "", "params": {}},
    }


async def run_teacher_action(
    db: AsyncSession,
    *,
    user_id: int,
    question_id: int,
    action: str,
    question_version_id: int | None = None,
    diagnosis_id: int | None = None,
    exam_attempt_id: int | None = None,
    user_answer: str | None = None,
) -> dict[str, Any]:
    if action not in ACTION_DEFINITIONS:
        raise AITeacher408AccessError("不支持的 AI 固定动作")

    exam_context = await _resolve_exam_context(
        db,
        user_id=user_id,
        question_id=question_id,
        exam_attempt_id=exam_attempt_id,
    )
    question, revision, diagnosis = await _resolve_revision_and_diagnosis(
        db,
        user_id=user_id,
        question_id=question_id,
        requested_version_id=question_version_id,
        diagnosis_id=diagnosis_id,
        exam_context=exam_context,
    )
    knowledge_context = await _load_knowledge_context(
        db, user_id=user_id, revision=revision
    )

    exam_answer = exam_context.get("answer")
    practice_context = await _latest_practice_context(
        db,
        user_id=user_id,
        question_id=question_id,
        question_version_id=int(revision.id),
    )
    resolved_user_answer = None
    resolved_is_correct = None
    answer_source = "none"
    if exam_answer is not None:
        resolved_user_answer = exam_answer.selected_answer
        resolved_is_correct = exam_answer.is_correct
        answer_source = "exam"
    elif diagnosis is not None:
        resolved_user_answer = diagnosis.user_answer
        answer_source = str(diagnosis.source_context or "diagnosis")
        if practice_context:
            resolved_is_correct = practice_context.get("is_correct")
    elif practice_context:
        resolved_user_answer = practice_context.get("user_answer")
        resolved_is_correct = practice_context.get("is_correct")
        answer_source = "practice"
    elif user_answer:
        resolved_user_answer = str(user_answer)[:1000]
        answer_source = "client_context"

    diagnosis_context = None
    if diagnosis is not None:
        diagnosis_context = error_diagnosis_service.serialize_diagnosis(diagnosis)
        # Only pass fields useful to teaching; do not expose worker/model metadata.
        diagnosis_context = {
            "primary_type": diagnosis_context.get("primary_type"),
            "primary_label": diagnosis_context.get("primary_label"),
            "secondary_labels": diagnosis_context.get("secondary_labels"),
            "effective_source": diagnosis_context.get("effective_source"),
            "user_confirmed": diagnosis_context.get("user_confirmed"),
        }

    context = {
        "question": {
            "question_id": int(question.id),
            "question_version_id": int(revision.id),
            "subject_id": int(revision.subject_id or question.subject_id),
            "question_type": str(
                revision.question_type or question.question_type or ""
            ),
            "difficulty": int(revision.difficulty or question.difficulty or 0),
            "stem": _bounded(_stem_text(revision.content), 5000),
            "options": _bounded(revision.options or {}, 4000),
            "correct_answer": _clean_str(revision.answer, 500),
            "official_analysis": _clean_str(revision.analysis, 6000),
        },
        "learner_answer": {
            "answer": _clean_str(resolved_user_answer, 1000),
            "is_correct": resolved_is_correct,
            "source": answer_source,
        },
        "error_diagnosis": diagnosis_context,
        "knowledge": _prompt_knowledge_context(knowledge_context),
    }
    messages = build_408_teacher_prompt(action=action, context=context)

    personalization = {
        "used_mastery": any(
            item.get("mastery_score") is not None
            for item in knowledge_context.get("knowledge_points", [])
        ),
        "used_recent_errors": bool(knowledge_context.get("recent_same_kp_errors")),
        "used_error_diagnosis": bool(diagnosis_context),
        "used_knowledge_graph": bool(
            knowledge_context.get("knowledge_graph_neighbors")
        ),
        "weak_point_names": [
            str(item.get("name"))
            for item in knowledge_context.get("weak_points", [])
            if item.get("name")
        ][:5],
    }

    base = {
        "question_id": int(question.id),
        "question_version_id": int(revision.id),
        "action": action,
        "action_label": ACTION_DEFINITIONS[action]["label"],
        "prompt_version": PROMPT_VERSION,
        "personalization": personalization,
    }

    if not await check_token_limit(db, user_id, 900):
        fallback = _fallback_payload(
            action=action,
            revision=revision,
            knowledge_context=knowledge_context,
            reason="今日 AI 调用额度已用尽，可先查看题库解析与知识点。",
        )
        return {**base, **fallback, "tokens_used": 0, "from_fallback": True}

    try:
        result = await chat_with_db_model(
            db,
            messages,
            feature="analysis",
            temperature=0.2,
            timeout=45,
            max_tokens=1400,
            response_format={"type": "json_object"},
            prefer_direct_answer=True,
        )
    except Exception:
        logger.warning(
            "408 teacher call failed uid=%s qid=%s action=%s",
            user_id,
            question_id,
            action,
            exc_info=True,
        )
        result = None

    if result is None:
        fallback = _fallback_payload(
            action=action,
            revision=revision,
            knowledge_context=knowledge_context,
            reason="AI 老师暂不可用，可先查看题库解析。",
        )
        return {**base, **fallback, "tokens_used": 0, "from_fallback": True}

    # Count every successful provider call, including malformed structured
    # output. Otherwise repeated JSON failures could consume provider tokens
    # without ever affecting the user's daily/monthly budget.
    await record_token_usage(
        db,
        user_id,
        f"408_teacher:{action}",
        f"question_id={question_id} question_version_id={revision.id} action={action}",
        str(result.get("content") or ""),
        result,
    )

    parsed = _parse_json_object(result.get("content"))
    if parsed is None:
        fallback = _fallback_payload(
            action=action,
            revision=revision,
            knowledge_context=knowledge_context,
            reason="AI 返回格式异常，可先查看题库解析。",
        )
        return {
            **base,
            **fallback,
            "tokens_used": int(result.get("tokens_used") or 0),
            "from_fallback": True,
        }

    normalized = _normalize_ai_payload(parsed, action)
    # Generated-question actions must not pretend success when the structured
    # question is invalid; fail back to a truthful, non-generated response.
    if (
        action in {"similar_question", "harder_question"}
        and normalized["practice_question"] is None
    ):
        fallback = _fallback_payload(
            action=action,
            revision=revision,
            knowledge_context=knowledge_context,
            reason="AI 未生成可校验的单选题，请稍后重试。",
        )
        return {
            **base,
            **fallback,
            "tokens_used": int(result.get("tokens_used") or 0),
            "from_fallback": True,
        }

    return {
        **base,
        **normalized,
        "tokens_used": int(result.get("tokens_used") or 0),
        "from_fallback": False,
    }
