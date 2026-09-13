from __future__ import annotations

import re
from decimal import Decimal
from uuid import uuid4

from fastapi import Request
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import AdminPrincipal
from app.core.subject_scope import EXAM408_CORE_CODES, canonical_408_code
from app.core.time_utils import utcnow
from app.features.question_type import QT_SINGLE_CHOICE
from app.models.admin import QuestionVersion, Subject
from app.models.exam import ExamAttempt, ExamPaper, ExamPaperQuestion
from app.models.question import Question
from app.schemas.admin_exam import (
    AdminExamPaperCreateRequest,
    AdminExamPaperItemsReplaceRequest,
    AdminExamPaperUpdateRequest,
)
from app.services.admin_audit_service import write_admin_audit


class ExamPaperNotFoundError(ValueError):
    pass


class ExamPaperStateError(ValueError):
    pass


def _money(value) -> float:
    return round(float(value or 0), 2)


async def _paper_aggregates(db: AsyncSession, paper_ids: list[int]) -> dict[int, dict]:
    if not paper_ids:
        return {}
    item_rows = await db.execute(
        select(
            ExamPaperQuestion.paper_id,
            func.count(ExamPaperQuestion.id),
            func.coalesce(func.sum(ExamPaperQuestion.score), 0),
        )
        .where(ExamPaperQuestion.paper_id.in_(paper_ids))
        .group_by(ExamPaperQuestion.paper_id)
    )
    attempt_rows = await db.execute(
        select(ExamAttempt.paper_id, func.count(ExamAttempt.id))
        .where(ExamAttempt.paper_id.in_(paper_ids))
        .group_by(ExamAttempt.paper_id)
    )
    result = {
        int(pid): {
            "question_count": int(count),
            "total_choice_score": _money(score),
            "attempt_count": 0,
        }
        for pid, count, score in item_rows.all()
    }
    for pid, count in attempt_rows.all():
        result.setdefault(
            int(pid),
            {"question_count": 0, "total_choice_score": 0.0, "attempt_count": 0},
        )["attempt_count"] = int(count)
    return result


def _paper_payload(paper: ExamPaper, aggregate: dict | None = None) -> dict:
    aggregate = aggregate or {}
    return {
        "id": int(paper.id),
        "public_id": paper.public_id,
        "title": paper.title,
        "paper_type": paper.paper_type,
        "year": paper.year,
        "source": paper.source,
        "duration_sec": paper.duration_sec,
        "version": int(paper.version),
        "status": paper.status,
        "is_active": bool(paper.is_active),
        "question_count": int(aggregate.get("question_count", 0)),
        "total_choice_score": _money(aggregate.get("total_choice_score", 0)),
        "attempt_count": int(aggregate.get("attempt_count", 0)),
        "published_at": paper.published_at,
        "created_at": paper.created_at,
        "updated_at": paper.updated_at,
    }


async def list_exam_papers(
    db: AsyncSession,
    *,
    status: str | None = None,
    paper_type: str | None = None,
    year: int | None = None,
) -> list[dict]:
    query = select(ExamPaper)
    if status:
        query = query.where(ExamPaper.status == status)
    if paper_type:
        query = query.where(ExamPaper.paper_type == paper_type)
    if year is not None:
        query = query.where(ExamPaper.year == year)
    query = query.order_by(
        ExamPaper.year.desc().nullslast(),
        ExamPaper.created_at.desc(),
        ExamPaper.id.desc(),
    )
    papers = list((await db.execute(query)).scalars().all())
    aggregates = await _paper_aggregates(db, [int(p.id) for p in papers])
    return [_paper_payload(p, aggregates.get(int(p.id))) for p in papers]


async def _get_paper(
    db: AsyncSession, paper_id: int, *, lock: bool = False
) -> ExamPaper:
    stmt = select(ExamPaper).where(ExamPaper.id == paper_id)
    if (
        lock
        and db.get_bind() is not None
        and db.get_bind().dialect.name == "postgresql"
    ):
        stmt = stmt.with_for_update()
    paper = await db.scalar(stmt)
    if paper is None:
        raise ExamPaperNotFoundError("试卷不存在")
    return paper


async def get_exam_paper_id_by_public_id(
    db: AsyncSession, public_id: str
) -> int:
    value = (public_id or "").strip()
    if not value:
        raise ExamPaperNotFoundError("试卷不存在")
    paper_id = await db.scalar(
        select(ExamPaper.id).where(ExamPaper.public_id == value)
    )
    if paper_id is None:
        raise ExamPaperNotFoundError("试卷不存在")
    return int(paper_id)


async def _load_paper_items(db: AsyncSession, paper_id: int) -> list[dict]:
    rows = await db.execute(
        select(ExamPaperQuestion, Question, QuestionVersion, Subject)
        .join(Question, Question.id == ExamPaperQuestion.question_id)
        .join(
            QuestionVersion, QuestionVersion.id == ExamPaperQuestion.question_version_id
        )
        .join(Subject, Subject.id == ExamPaperQuestion.section_subject_id)
        .where(ExamPaperQuestion.paper_id == paper_id)
        .order_by(ExamPaperQuestion.position.asc(), ExamPaperQuestion.id.asc())
    )
    result: list[dict] = []
    for item, question, revision, subject in rows.all():
        result.append(
            {
                "id": int(item.id),
                "question_id": int(item.question_id),
                "question_version_id": int(item.question_version_id),
                "position": int(item.position),
                "score": _money(item.score),
                "subject_id": int(item.section_subject_id),
                "subject_code": subject.code,
                "subject_name": subject.name,
                "question_type": str(
                    revision.question_type or question.question_type or ""
                ),
                "content": revision.content,
                "options": revision.options,
                "year": revision.year,
                "source": revision.source,
                "difficulty": int(revision.difficulty or 3),
                "review_status": question.review_status,
                "is_active": bool(question.is_active and revision.is_active),
                "current_version_id": int(question.current_version_id)
                if question.current_version_id
                else None,
                "version_is_current": int(question.current_version_id or 0)
                == int(item.question_version_id),
            }
        )
    return result


async def validate_exam_paper(db: AsyncSession, paper_id: int) -> list[str]:
    paper = await _get_paper(db, paper_id)
    items = await _load_paper_items(db, paper_id)
    errors: list[str] = []
    if not items:
        errors.append("试卷至少需要 1 道选择题")
        return errors
    positions = [int(item["position"]) for item in items]
    expected = list(range(1, len(items) + 1))
    if positions != expected:
        errors.append("题目 position 必须从 1 开始连续且唯一")
    qids = [int(item["question_id"]) for item in items]
    if len(qids) != len(set(qids)):
        errors.append("试卷存在重复题目")
    for item in items:
        prefix = f"第 {item['position']} 题"
        if item["question_type"] != QT_SINGLE_CHOICE:
            errors.append(f"{prefix} 不是 single_choice，V1 仅允许单选题")
        if (
            not item["options"]
            or not isinstance(item["options"], dict)
            or len(item["options"]) < 2
        ):
            errors.append(f"{prefix} 缺少有效选项")
        # Draft papers are validated against current publishability.
        # Published/archived papers are historical snapshots and must not fail
        # only because the source question was later disabled or reviewed again.
        if paper.status == "draft" and (
            not item["is_active"] or item["review_status"] != "approved"
        ):
            errors.append(f"{prefix} 当前不是 approved + active 可发布题目")
        # Draft validation protects against accidentally publishing against a
        # superseded mutable question projection. Published/archived papers are
        # historical snapshots and must continue to validate against their
        # frozen question_version_id rather than the current Question pointer.
        if paper.status == "draft" and not item["version_is_current"]:
            errors.append(f"{prefix} 已产生新题目版本，请重新保存组卷后再发布")
        if canonical_408_code(item["subject_code"]) not in EXAM408_CORE_CODES:
            errors.append(f"{prefix} 不属于 canonical 408 四科")
        if _money(item["score"]) <= 0:
            errors.append(f"{prefix} 分值必须大于 0")
    if paper.paper_type == "past_exam_choice" and paper.year is None:
        errors.append("真题选择题卷必须填写年份")
    return errors


async def get_exam_paper_detail(db: AsyncSession, paper_id: int) -> dict:
    paper = await _get_paper(db, paper_id)
    aggregates = await _paper_aggregates(db, [paper_id])
    payload = _paper_payload(paper, aggregates.get(paper_id))
    payload["items"] = await _load_paper_items(db, paper_id)
    payload["validation_errors"] = await validate_exam_paper(db, paper_id)
    return payload


def _question_stem(content: object) -> str:
    if not isinstance(content, dict):
        return ""
    for key in ("stem", "text", "question", "content", "title"):
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _matches_past_exam_prefix(stem: str, year: int) -> bool:
    if not stem:
        return False
    # The title prefix is the authoritative signal for this shortcut.  Legacy
    # data can have source_type/year missing on the mutable Question projection,
    # so do not make those columns a hard requirement.  Accept both Chinese and
    # ASCII square brackets plus the historical optional space after the year.
    pattern = rf"^[【\[]\s*{year}\s*统考真题\s*[】\]]"
    return re.match(pattern, stem) is not None


def _matching_past_exam_content(question: Question, revision: QuestionVersion, year: int) -> dict | None:
    """Return the versioned content whose stem carries the requested prefix.

    Current-version content is preferred, but older imports can have an empty or
    partially migrated revision payload while the Question projection is valid.
    Checking both makes quick-add work for those rows without relaxing the final
    title-prefix requirement.
    """
    candidates = [revision.content, question.content]
    for content in candidates:
        if not isinstance(content, dict):
            continue
        if _matches_past_exam_prefix(_question_stem(content), year):
            return content
    return None


async def list_past_exam_candidates(db: AsyncSession, year: int) -> dict:
    rows = await db.execute(
        select(Question, QuestionVersion, Subject)
        .join(QuestionVersion, QuestionVersion.id == Question.current_version_id)
        .join(Subject, Subject.id == Question.subject_id)
        .where(
            Question.review_status == "approved",
            Question.is_active.is_(True),
            QuestionVersion.is_active.is_(True),
            or_(
                Question.question_type == QT_SINGLE_CHOICE,
                QuestionVersion.question_type == QT_SINGLE_CHOICE,
            ),
            Subject.is_active.is_(True),
        )
        .order_by(Question.id.asc())
    )
    items: list[dict] = []
    for question, revision, subject in rows.all():
        if canonical_408_code(subject.code) not in EXAM408_CORE_CODES:
            continue
        content = _matching_past_exam_content(question, revision, year)
        if content is None:
            continue
        items.append(
            {
                "question_id": int(question.id),
                "subject_id": int(question.subject_id),
                "subject_code": subject.code,
                "subject_name": subject.name,
                "content": content,
                "year": int(year),
                "source": revision.source or question.source,
            }
        )
    return {"year": int(year), "total": len(items), "items": items}


async def create_exam_paper(
    db: AsyncSession,
    data: AdminExamPaperCreateRequest,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> ExamPaper:
    title = data.title.strip()
    if not title:
        raise ValueError("试卷名称不能为空")
    paper = ExamPaper(
        public_id=uuid4().hex,
        title=title,
        paper_type=data.paper_type,
        year=data.year,
        source=(data.source or "").strip() or None,
        duration_sec=data.duration_sec,
        status="draft",
        is_active=True,
        created_by=operator.id,
        updated_by=operator.id,
    )
    db.add(paper)
    await db.flush()
    await write_admin_audit(
        db,
        operator,
        "exam.paper.create",
        "exam_paper",
        paper.id,
        detail={
            "title": paper.title,
            "paper_type": paper.paper_type,
            "year": paper.year,
        },
        request=request,
    )
    return paper


async def update_exam_paper(
    db: AsyncSession,
    paper_id: int,
    data: AdminExamPaperUpdateRequest,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> ExamPaper:
    paper = await _get_paper(db, paper_id, lock=True)
    if paper.status != "draft":
        raise ExamPaperStateError("已发布/归档试卷元数据不可直接修改，请新建版本")
    before = {
        "title": paper.title,
        "paper_type": paper.paper_type,
        "year": paper.year,
        "source": paper.source,
        "duration_sec": paper.duration_sec,
        "is_active": paper.is_active,
    }
    values = data.model_dump(exclude_unset=True)
    if "title" in values:
        values["title"] = values["title"].strip()
        if not values["title"]:
            raise ValueError("试卷名称不能为空")
    if "source" in values:
        values["source"] = (values["source"] or "").strip() or None
    future_type = values.get("paper_type", paper.paper_type)
    future_year = values.get("year", paper.year)
    if future_type == "past_exam_choice" and future_year is None:
        raise ValueError("真题选择题卷必须填写年份")
    for key, value in values.items():
        setattr(paper, key, value)
    paper.updated_by = operator.id
    await write_admin_audit(
        db,
        operator,
        "exam.paper.update",
        "exam_paper",
        paper.id,
        detail={"before": before, "after": values},
        request=request,
    )
    return paper


async def replace_exam_paper_items(
    db: AsyncSession,
    paper_id: int,
    data: AdminExamPaperItemsReplaceRequest,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> None:
    paper = await _get_paper(db, paper_id, lock=True)
    if paper.status != "draft":
        raise ExamPaperStateError("已发布/归档试卷题目不可修改，请新建版本")

    ids = [item.question_id for item in data.items]
    rows = await db.execute(
        select(Question, QuestionVersion, Subject)
        .join(QuestionVersion, QuestionVersion.id == Question.current_version_id)
        .join(Subject, Subject.id == Question.subject_id)
        .where(Question.id.in_(ids))
    )
    by_id = {int(q.id): (q, rev, subject) for q, rev, subject in rows.all()}
    if len(by_id) != len(ids):
        missing = sorted(set(ids) - set(by_id))
        raise ValueError(f"部分题目不存在或缺少 current revision: {missing}")

    new_rows: list[ExamPaperQuestion] = []
    for position, input_item in enumerate(data.items, start=1):
        question, revision, subject = by_id[input_item.question_id]
        if (
            question.review_status != "approved"
            or not question.is_active
            or not revision.is_active
        ):
            raise ValueError(
                f"question_id={question.id} 不是 approved + active 可组卷题目"
            )
        if (
            str(question.question_type or "") != QT_SINGLE_CHOICE
            or str(revision.question_type or "") != QT_SINGLE_CHOICE
        ):
            raise ValueError(
                f"question_id={question.id} 不是 single_choice，V1 仅允许单选题"
            )
        if int(revision.question_id) != int(question.id):
            raise ValueError(f"question_id={question.id} current revision 绑定异常")
        if int(revision.subject_id or 0) != int(question.subject_id):
            raise ValueError(f"question_id={question.id} current revision 科目不一致")
        if (
            canonical_408_code(subject.code) not in EXAM408_CORE_CODES
            or not subject.is_active
        ):
            raise ValueError(
                f"question_id={question.id} 不属于启用的 canonical 408 四科"
            )
        if not isinstance(revision.options, dict) or len(revision.options) < 2:
            raise ValueError(f"question_id={question.id} 缺少有效选择题选项")
        new_rows.append(
            ExamPaperQuestion(
                paper_id=paper.id,
                question_id=question.id,
                question_version_id=revision.id,
                position=position,
                score=Decimal(str(input_item.score)).quantize(Decimal("0.01")),
                section_subject_id=question.subject_id,
            )
        )

    await db.execute(
        delete(ExamPaperQuestion).where(ExamPaperQuestion.paper_id == paper.id)
    )
    db.add_all(new_rows)
    paper.updated_by = operator.id
    await db.flush()
    await write_admin_audit(
        db,
        operator,
        "exam.paper.items.replace",
        "exam_paper",
        paper.id,
        severity="important",
        detail={"question_count": len(new_rows), "question_ids": ids},
        request=request,
    )


async def publish_exam_paper(
    db: AsyncSession,
    paper_id: int,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> ExamPaper:
    paper = await _get_paper(db, paper_id, lock=True)
    if paper.status == "published":
        return paper
    if paper.status != "draft":
        raise ExamPaperStateError("只有草稿试卷可以发布")
    errors = await validate_exam_paper(db, paper_id)
    if errors:
        raise ValueError("发布校验失败：" + "；".join(errors))
    paper.status = "published"
    paper.is_active = True
    paper.published_at = utcnow()
    paper.updated_by = operator.id
    await write_admin_audit(
        db,
        operator,
        "exam.paper.publish",
        "exam_paper",
        paper.id,
        severity="important",
        detail={"version": paper.version},
        request=request,
    )
    return paper


async def archive_exam_paper(
    db: AsyncSession,
    paper_id: int,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> ExamPaper:
    paper = await _get_paper(db, paper_id, lock=True)
    if paper.status == "archived":
        return paper
    paper.status = "archived"
    paper.is_active = False
    paper.updated_by = operator.id
    await write_admin_audit(
        db,
        operator,
        "exam.paper.archive",
        "exam_paper",
        paper.id,
        severity="important",
        detail={"version": paper.version},
        request=request,
    )
    return paper
