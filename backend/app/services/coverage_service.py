from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import QuestionVersion, QuestionVersionKnowledgePoint, Subject
from app.models.exam import ExamPaper, ExamPaperQuestion
from app.models.question import Question
from app.models.question_knowledge_point import QuestionKnowledgePoint
from app.models.syllabus import SyllabusKnowledgePoint, SyllabusVersion
from app.services import recommendation_quality_service, syllabus_service


class CoverageError(ValueError):
    pass


_ISSUE_SAMPLE_LIMIT = 50
_DUPLICATE_GROUP_LIMIT = 30
_SOURCE_LIMIT_PER_KP = 8


def _analysis_missing_expr():
    return func.length(func.trim(func.coalesce(Question.analysis, ""))) == 0


def _image_ref_from_value(value: Any) -> tuple[bool, bool]:
    """Return (declares_image, has_valid_url) for a legacy image value."""
    if isinstance(value, str):
        return True, bool(value.strip())
    if not isinstance(value, dict):
        return True, False
    for key in ("url", "src", "image_url", "imageUrl"):
        if key in value:
            candidate = value.get(key)
            return True, isinstance(candidate, str) and bool(candidate.strip())
    return True, False


def _has_image_reference_anomaly(content: Any, options: Any, image_url: Any) -> bool:
    """Detect malformed persisted image references without remote I/O.

    This deliberately checks structural integrity only. A URL can be syntactically
    present while the remote object is unavailable; storage/network probes do not
    belong in a request-time coverage report.
    """
    if isinstance(content, dict):
        segments = content.get("segments")
        if isinstance(segments, list):
            for segment in segments:
                if not isinstance(segment, dict):
                    continue
                segment_type = str(segment.get("type") or "").strip().lower()
                if segment_type not in {
                    "image",
                    "math_image",
                    "table_image",
                    "code_image",
                }:
                    continue
                if segment.get("display") is False:
                    continue
                url = segment.get("url")
                if not isinstance(url, str) or not url.strip():
                    return True

    if image_url is not None:
        if not isinstance(image_url, list):
            return True
        for value in image_url:
            _, valid = _image_ref_from_value(value)
            if not valid:
                return True

    option_values: list[Any] = []
    if isinstance(options, dict):
        option_values = list(options.values())
    elif isinstance(options, list):
        option_values = options
    for value in option_values:
        if not isinstance(value, dict):
            continue
        image_keys = [
            key for key in ("image_url", "imageUrl", "url", "src") if key in value
        ]
        for key in image_keys:
            candidate = value.get(key)
            if candidate is not None and (
                not isinstance(candidate, str) or not candidate.strip()
            ):
                return True
    return False


async def _resolve_syllabus(
    db: AsyncSession, syllabus_version_id: int | None
) -> SyllabusVersion:
    if syllabus_version_id is None:
        version = await syllabus_service.get_active_version(db)
        if version is None:
            raise CoverageError("当前没有 active 408 考纲版本")
        return version
    version = await db.get(SyllabusVersion, syllabus_version_id)
    if version is None:
        raise CoverageError("考纲版本不存在")
    return version


async def _load_members(
    db: AsyncSession,
    version: SyllabusVersion,
    subject_id: int | None,
) -> list[tuple[SyllabusKnowledgePoint, Subject]]:
    stmt = (
        select(SyllabusKnowledgePoint, Subject)
        .join(Subject, Subject.id == SyllabusKnowledgePoint.subject_id)
        .where(SyllabusKnowledgePoint.syllabus_version_id == version.id)
    )
    if subject_id is not None:
        stmt = stmt.where(SyllabusKnowledgePoint.subject_id == subject_id)
    rows = list(
        (
            await db.execute(
                stmt.order_by(
                    Subject.sort_order.asc(),
                    SyllabusKnowledgePoint.sort_order.asc(),
                    SyllabusKnowledgePoint.id.asc(),
                )
            )
        ).all()
    )
    if subject_id is not None and not rows:
        raise CoverageError("所选科目不在该考纲版本中")
    if not rows:
        raise CoverageError("该考纲版本没有知识点")
    return rows


async def _duplicate_groups(
    db: AsyncSession,
    scope_conditions: list[Any],
) -> tuple[set[int], list[dict]]:
    hash_rows = (
        await db.execute(
            select(Question.question_hash, func.count(Question.id))
            .where(
                *scope_conditions,
                Question.question_hash.is_not(None),
                func.length(func.trim(Question.question_hash)) > 0,
            )
            .group_by(Question.question_hash)
            .having(func.count(Question.id) > 1)
            .order_by(func.count(Question.id).desc(), Question.question_hash.asc())
        )
    ).all()
    hashes = [str(row[0]) for row in hash_rows]
    if not hashes:
        return set(), []
    rows = (
        await db.execute(
            select(Question.question_hash, Question.id)
            .where(*scope_conditions, Question.question_hash.in_(hashes))
            .order_by(Question.question_hash.asc(), Question.id.asc())
        )
    ).all()
    by_hash: dict[str, list[int]] = defaultdict(list)
    suspect_ids: set[int] = set()
    for question_hash, question_id in rows:
        key = str(question_hash)
        qid = int(question_id)
        by_hash[key].append(qid)
        suspect_ids.add(qid)
    samples = [
        {"question_hash": key, "question_ids": ids}
        for key, ids in sorted(
            by_hash.items(), key=lambda item: (-len(item[1]), item[0])
        )[:_DUPLICATE_GROUP_LIMIT]
    ]
    return suspect_ids, samples


async def _exam_year_report(
    db: AsyncSession,
    *,
    year_from: int | None,
    year_to: int | None,
) -> list[dict]:
    from app.services import admin_exam_service

    papers = list(
        (
            await db.scalars(
                select(ExamPaper)
                .where(
                    ExamPaper.paper_type == "past_exam_choice",
                    ExamPaper.year.is_not(None),
                )
                .order_by(
                    ExamPaper.year.asc(), ExamPaper.version.desc(), ExamPaper.id.desc()
                )
            )
        ).all()
    )

    known_years = sorted(
        {int(paper.year) for paper in papers if paper.year is not None}
    )
    if year_from is None and known_years:
        year_from = min(known_years)
    if year_to is None and known_years:
        year_to = max(known_years)
    if year_from is None or year_to is None:
        return []

    by_year: dict[int, list[ExamPaper]] = defaultdict(list)
    for paper in papers:
        if paper.year is not None and year_from <= int(paper.year) <= year_to:
            by_year[int(paper.year)].append(paper)

    def paper_rank(paper: ExamPaper) -> tuple[int, int, int]:
        if paper.status == "published" and paper.is_active:
            status_rank = 0
        elif paper.status == "draft":
            status_rank = 1
        elif paper.status == "published":
            status_rank = 2
        else:
            status_rank = 3
        return status_rank, -int(paper.version or 1), -int(paper.id)

    representatives: dict[int, ExamPaper] = {
        year: sorted(items, key=paper_rank)[0]
        for year, items in by_year.items()
        if items
    }
    representative_ids = [int(paper.id) for paper in representatives.values()]

    missing_analysis: dict[int, int] = defaultdict(int)
    missing_kp: dict[int, int] = defaultdict(int)
    if representative_ids:
        analysis_rows = (
            await db.execute(
                select(
                    ExamPaperQuestion.paper_id,
                    func.sum(
                        case(
                            (
                                func.length(
                                    func.trim(
                                        func.coalesce(QuestionVersion.analysis, "")
                                    )
                                )
                                == 0,
                                1,
                            ),
                            else_=0,
                        )
                    ),
                )
                .join(
                    QuestionVersion,
                    QuestionVersion.id == ExamPaperQuestion.question_version_id,
                )
                .where(ExamPaperQuestion.paper_id.in_(representative_ids))
                .group_by(ExamPaperQuestion.paper_id)
            )
        ).all()
        missing_analysis.update(
            {int(paper_id): int(count or 0) for paper_id, count in analysis_rows}
        )

        kp_exists = (
            select(QuestionVersionKnowledgePoint.id)
            .where(
                QuestionVersionKnowledgePoint.question_version_id
                == ExamPaperQuestion.question_version_id
            )
            .limit(1)
            .correlate(ExamPaperQuestion)
        )
        kp_rows = (
            await db.execute(
                select(
                    ExamPaperQuestion.paper_id,
                    func.sum(case((~kp_exists.exists(), 1), else_=0)),
                )
                .where(ExamPaperQuestion.paper_id.in_(representative_ids))
                .group_by(ExamPaperQuestion.paper_id)
            )
        ).all()
        missing_kp.update(
            {int(paper_id): int(count or 0) for paper_id, count in kp_rows}
        )

    result: list[dict] = []
    for year in range(year_from, year_to + 1):
        paper = representatives.get(year)
        if paper is None:
            result.append(
                {
                    "year": year,
                    "status": "missing",
                    "validation_errors": ["该年份尚无真题选择题试卷记录"],
                    "quality_warnings": [],
                }
            )
            continue

        detail = await admin_exam_service.get_exam_paper_detail(db, int(paper.id))
        errors = list(detail.get("validation_errors") or [])
        analysis_missing = int(missing_analysis.get(int(paper.id), 0))
        kp_missing = int(missing_kp.get(int(paper.id), 0))
        warnings: list[str] = []
        if analysis_missing:
            warnings.append(f"{analysis_missing} 道题缺少解析")
        if kp_missing:
            warnings.append(f"{kp_missing} 道题的固定题目版本未关联知识点")

        if paper.status == "archived":
            status = "archived"
        elif paper.status == "draft":
            status = "draft"
        elif errors or not paper.is_active:
            status = "invalid"
        else:
            status = "complete"

        result.append(
            {
                "year": year,
                "status": status,
                "paper_id": int(paper.id),
                "paper_title": paper.title,
                "paper_status": paper.status,
                "paper_version": int(paper.version or 1),
                "question_count": int(detail.get("question_count") or 0),
                "total_choice_score": float(detail.get("total_choice_score") or 0),
                "missing_analysis_count": analysis_missing,
                "missing_knowledge_point_count": kp_missing,
                "validation_errors": errors,
                "quality_warnings": warnings,
            }
        )
    return result


async def build_coverage_report(
    db: AsyncSession,
    *,
    syllabus_version_id: int | None = None,
    subject_id: int | None = None,
    min_questions: int = 10,
    year_from: int | None = None,
    year_to: int | None = None,
) -> dict:
    version = await _resolve_syllabus(db, syllabus_version_id)
    members = await _load_members(db, version, subject_id)
    kp_ids = [int(member.knowledge_point_id) for member, _ in members]
    subject_ids = sorted({int(member.subject_id) for member, _ in members})
    scope_conditions = [
        Question.subject_id.in_(subject_ids),
        Question.is_active.is_(True),
        Question.review_status == "approved",
    ]

    aggregate_rows = (
        await db.execute(
            select(
                QuestionKnowledgePoint.knowledge_point_id,
                func.count(func.distinct(Question.id)).label("total_count"),
                func.sum(case((Question.difficulty.in_((1, 2)), 1), else_=0)).label(
                    "easy_count"
                ),
                func.sum(case((Question.difficulty == 3, 1), else_=0)).label(
                    "medium_count"
                ),
                func.sum(case((Question.difficulty.in_((4, 5)), 1), else_=0)).label(
                    "hard_count"
                ),
                func.sum(case((_analysis_missing_expr(), 1), else_=0)).label(
                    "missing_analysis_count"
                ),
            )
            .join(Question, Question.id == QuestionKnowledgePoint.question_id)
            .where(
                QuestionKnowledgePoint.knowledge_point_id.in_(kp_ids), *scope_conditions
            )
            .group_by(QuestionKnowledgePoint.knowledge_point_id)
        )
    ).all()
    aggregates = {
        int(row.knowledge_point_id): {
            "total": int(row.total_count or 0),
            "easy": int(row.easy_count or 0),
            "medium": int(row.medium_count or 0),
            "hard": int(row.hard_count or 0),
            "missing_analysis": int(row.missing_analysis_count or 0),
        }
        for row in aggregate_rows
    }

    type_rows = (
        await db.execute(
            select(
                QuestionKnowledgePoint.knowledge_point_id,
                Question.question_type,
                func.count(Question.id),
            )
            .join(Question, Question.id == QuestionKnowledgePoint.question_id)
            .where(
                QuestionKnowledgePoint.knowledge_point_id.in_(kp_ids), *scope_conditions
            )
            .group_by(QuestionKnowledgePoint.knowledge_point_id, Question.question_type)
        )
    ).all()
    type_counts: dict[int, dict[str, int]] = defaultdict(dict)
    for kp_id, question_type, count in type_rows:
        type_counts[int(kp_id)][str(question_type)] = int(count or 0)

    year_rows = (
        await db.execute(
            select(QuestionKnowledgePoint.knowledge_point_id, Question.year)
            .join(Question, Question.id == QuestionKnowledgePoint.question_id)
            .where(
                QuestionKnowledgePoint.knowledge_point_id.in_(kp_ids),
                *scope_conditions,
                Question.year.is_not(None),
            )
            .distinct()
            .order_by(
                QuestionKnowledgePoint.knowledge_point_id.asc(), Question.year.desc()
            )
        )
    ).all()
    years_by_kp: dict[int, list[int]] = defaultdict(list)
    for kp_id, year in year_rows:
        years_by_kp[int(kp_id)].append(int(year))

    source_rows = (
        await db.execute(
            select(QuestionKnowledgePoint.knowledge_point_id, Question.source)
            .join(Question, Question.id == QuestionKnowledgePoint.question_id)
            .where(
                QuestionKnowledgePoint.knowledge_point_id.in_(kp_ids),
                *scope_conditions,
                Question.source.is_not(None),
                func.length(func.trim(Question.source)) > 0,
            )
            .distinct()
            .order_by(
                QuestionKnowledgePoint.knowledge_point_id.asc(), Question.source.asc()
            )
        )
    ).all()
    sources_by_kp: dict[int, list[str]] = defaultdict(list)
    for kp_id, source in source_rows:
        values = sources_by_kp[int(kp_id)]
        if len(values) < _SOURCE_LIMIT_PER_KP:
            values.append(str(source))

    # Exam-paper coverage is attributed through the immutable question-version
    # knowledge snapshot pinned by each paper item. Using the mutable current
    # QuestionKnowledgePoint relation here would make historical coverage drift
    # after administrators edit a question's knowledge-point mapping.
    exam_type_rows = (
        await db.execute(
            select(
                QuestionVersionKnowledgePoint.knowledge_point_id,
                ExamPaper.paper_type,
                func.count(func.distinct(ExamPaperQuestion.question_id)),
            )
            .select_from(ExamPaperQuestion)
            .join(ExamPaper, ExamPaper.id == ExamPaperQuestion.paper_id)
            .join(
                QuestionVersionKnowledgePoint,
                QuestionVersionKnowledgePoint.question_version_id
                == ExamPaperQuestion.question_version_id,
            )
            .where(
                QuestionVersionKnowledgePoint.knowledge_point_id.in_(kp_ids),
                # Exam coverage is historical paper coverage, not current-bank
                # availability. The paper item already pins question_version_id, so
                # mutable Question active/review/current-version state must not make
                # an already published paper disappear from coverage later.
                ExamPaper.paper_type.in_(("past_exam_choice", "mock_choice")),
                ExamPaper.status != "archived",
            )
            .group_by(
                QuestionVersionKnowledgePoint.knowledge_point_id, ExamPaper.paper_type
            )
        )
    ).all()
    past_counts: dict[int, int] = {}
    mock_counts: dict[int, int] = {}
    for kp_id, paper_type, count in exam_type_rows:
        target = past_counts if str(paper_type) == "past_exam_choice" else mock_counts
        target[int(kp_id)] = int(count or 0)

    duplicate_question_ids, duplicate_samples = await _duplicate_groups(
        db, scope_conditions
    )
    duplicate_kp_counts: dict[int, int] = {}
    if duplicate_question_ids:
        duplicate_rows = (
            await db.execute(
                select(
                    QuestionKnowledgePoint.knowledge_point_id,
                    func.count(func.distinct(QuestionKnowledgePoint.question_id)),
                )
                .where(
                    QuestionKnowledgePoint.knowledge_point_id.in_(kp_ids),
                    QuestionKnowledgePoint.question_id.in_(duplicate_question_ids),
                )
                .group_by(QuestionKnowledgePoint.knowledge_point_id)
            )
        ).all()
        duplicate_kp_counts = {
            int(kp_id): int(count or 0) for kp_id, count in duplicate_rows
        }

    total_questions = int(
        await db.scalar(select(func.count(Question.id)).where(*scope_conditions)) or 0
    )
    mapped_qids_stmt = (
        select(QuestionKnowledgePoint.question_id)
        .where(QuestionKnowledgePoint.knowledge_point_id.in_(kp_ids))
        .distinct()
    )
    mapped_questions = int(
        await db.scalar(
            select(func.count(Question.id)).where(
                *scope_conditions, Question.id.in_(mapped_qids_stmt)
            )
        )
        or 0
    )

    unmapped_ids = [
        int(qid)
        for qid in (
            await db.scalars(
                select(Question.id)
                .where(*scope_conditions, ~Question.id.in_(mapped_qids_stmt))
                .order_by(Question.id.asc())
                .limit(_ISSUE_SAMPLE_LIMIT)
            )
        ).all()
    ]
    missing_analysis_ids = [
        int(qid)
        for qid in (
            await db.scalars(
                select(Question.id)
                .where(*scope_conditions, _analysis_missing_expr())
                .order_by(Question.id.asc())
                .limit(_ISSUE_SAMPLE_LIMIT)
            )
        ).all()
    ]
    missing_analysis_count = int(
        await db.scalar(
            select(func.count(Question.id)).where(
                *scope_conditions, _analysis_missing_expr()
            )
        )
        or 0
    )

    unversioned_count = int(
        await db.scalar(
            select(func.count(Question.id)).where(
                *scope_conditions, Question.current_version_id.is_(None)
            )
        )
        or 0
    )
    unversioned_ids = [
        int(qid)
        for qid in (
            await db.scalars(
                select(Question.id)
                .where(*scope_conditions, Question.current_version_id.is_(None))
                .order_by(Question.id.asc())
                .limit(_ISSUE_SAMPLE_LIMIT)
            )
        ).all()
    ]

    snapshot_problem_stmt = (
        select(Question.id)
        .join(QuestionKnowledgePoint, QuestionKnowledgePoint.question_id == Question.id)
        .outerjoin(
            QuestionVersionKnowledgePoint,
            and_(
                QuestionVersionKnowledgePoint.question_version_id
                == Question.current_version_id,
                QuestionVersionKnowledgePoint.knowledge_point_id
                == QuestionKnowledgePoint.knowledge_point_id,
            ),
        )
        .where(
            *scope_conditions,
            Question.current_version_id.is_not(None),
            QuestionKnowledgePoint.knowledge_point_id.in_(kp_ids),
            or_(
                QuestionVersionKnowledgePoint.id.is_(None),
                QuestionVersionKnowledgePoint.syllabus_knowledge_point_id.is_(None),
            ),
        )
        .distinct()
    )
    snapshot_missing_count = int(
        await db.scalar(
            select(func.count()).select_from(snapshot_problem_stmt.subquery())
        )
        or 0
    )
    snapshot_missing_ids = [
        int(qid)
        for qid in (
            await db.scalars(
                snapshot_problem_stmt.order_by(Question.id.asc()).limit(
                    _ISSUE_SAMPLE_LIMIT
                )
            )
        ).all()
    ]

    image_rows = (
        await db.execute(
            select(Question.id, Question.content, Question.options, Question.image_url)
            .where(*scope_conditions)
            .order_by(Question.id.asc())
        )
    ).all()
    image_anomaly_ids_all = [
        int(question_id)
        for question_id, content, options, image_url in image_rows
        if _has_image_reference_anomaly(content, options, image_url)
    ]

    items: list[dict] = []
    for member, subject in members:
        kp_id = int(member.knowledge_point_id)
        stats = aggregates.get(
            kp_id,
            {"total": 0, "easy": 0, "medium": 0, "hard": 0, "missing_analysis": 0},
        )
        issues: list[str] = []
        total = int(stats["total"])
        if total == 0:
            status = "empty"
            issues.append("没有 approved + active 题目")
        elif total < min_questions:
            status = "insufficient"
            issues.append(f"题量不足：{total} < {min_questions}")
        elif int(stats["medium"]) == 0 or int(stats["hard"]) == 0:
            status = "imbalanced"
        else:
            status = "healthy"
        if total > 0 and int(stats["medium"]) == 0:
            issues.append("缺少中等难度题")
        if total > 0 and int(stats["hard"]) == 0:
            issues.append("缺少较难/困难题")
        if int(stats["missing_analysis"]) > 0:
            issues.append(f"{int(stats['missing_analysis'])} 道题缺解析")
        if duplicate_kp_counts.get(kp_id, 0) > 0:
            issues.append(f"{duplicate_kp_counts[kp_id]} 道题命中重复 hash")

        items.append(
            {
                "syllabus_knowledge_point_id": int(member.id),
                "knowledge_point_id": kp_id,
                "subject_id": int(member.subject_id),
                "subject_code": subject.code,
                "subject_name": subject.name,
                "name": member.name_snapshot,
                "total_question_count": total,
                "past_exam_choice_count": int(past_counts.get(kp_id, 0)),
                "mock_choice_count": int(mock_counts.get(kp_id, 0)),
                "difficulty_easy_count": int(stats["easy"]),
                "difficulty_medium_count": int(stats["medium"]),
                "difficulty_hard_count": int(stats["hard"]),
                "question_type_counts": type_counts.get(kp_id, {}),
                "years": years_by_kp.get(kp_id, []),
                "sources": sources_by_kp.get(kp_id, []),
                "missing_analysis_count": int(stats["missing_analysis"]),
                "duplicate_suspect_count": int(duplicate_kp_counts.get(kp_id, 0)),
                "status": status,
                "issues": issues,
            }
        )

    status_rank = {"empty": 0, "insufficient": 1, "imbalanced": 2, "healthy": 3}
    items.sort(
        key=lambda item: (
            status_rank[item["status"]],
            int(item["total_question_count"]),
            str(item["subject_code"]),
            str(item["name"]),
        )
    )

    status_counts = defaultdict(int)
    for item in items:
        status_counts[item["status"]] += 1

    knowledge_graph_quality = (
        await recommendation_quality_service.build_knowledge_quality_report(
            db,
            subject_id=subject_id,
            knowledge_point_ids=kp_ids,
        )
    )
    exam_years = await _exam_year_report(db, year_from=year_from, year_to=year_to)

    return {
        "syllabus": {
            "id": int(version.id),
            "code": version.code,
            "name": version.name,
            "effective_year": int(version.effective_year),
        },
        "summary": {
            "min_questions": int(min_questions),
            "total_knowledge_points": len(items),
            "healthy_knowledge_points": int(status_counts["healthy"]),
            "empty_knowledge_points": int(status_counts["empty"]),
            "insufficient_knowledge_points": int(status_counts["insufficient"]),
            "imbalanced_knowledge_points": int(status_counts["imbalanced"]),
            "total_questions": total_questions,
            "mapped_questions": mapped_questions,
            "unmapped_questions": max(total_questions - mapped_questions, 0),
            "missing_analysis_questions": missing_analysis_count,
            "image_reference_anomaly_questions": len(image_anomaly_ids_all),
            "duplicate_suspect_questions": len(duplicate_question_ids),
            "unversioned_questions": unversioned_count,
            "syllabus_snapshot_missing_questions": snapshot_missing_count,
        },
        "items": items,
        "exam_years": exam_years,
        "quality_issues": {
            "unmapped_question_ids": unmapped_ids,
            "missing_analysis_question_ids": missing_analysis_ids,
            "image_reference_anomaly_question_ids": image_anomaly_ids_all[
                :_ISSUE_SAMPLE_LIMIT
            ],
            "unversioned_question_ids": unversioned_ids,
            "syllabus_snapshot_missing_question_ids": snapshot_missing_ids,
            "duplicate_groups": duplicate_samples,
        },
        "knowledge_graph_quality": knowledge_graph_quality,
    }
