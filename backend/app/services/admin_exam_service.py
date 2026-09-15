from __future__ import annotations

import re
from decimal import Decimal
from uuid import uuid4

from fastapi import Request
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import AdminPrincipal
from app.core.subject_scope import EXAM408_CORE_CODES, canonical_408_code
from app.core.time_utils import utcnow
from app.features.question_type import QT_SINGLE_CHOICE
from app.models.admin import QuestionVersion, Subject
from app.models.exam import ExamAttempt, ExamPaper, ExamPaperQuestion
from app.models.question import Question
from app.models.question_import import QuestionImport
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


# 408 统考计算机综合选择题固定结构：40 题 × 2 分 = 80 分。
# 前 40 题必须严格按下列科目区间编排；当候选题超过 40 道时，
# 额外题目再按目标占比、剩余题量和连续科目惩罚做稳定均衡排序。
EXAM408_CHOICE_BLUEPRINT: tuple[tuple[str, int], ...] = (
    ("data_structure", 10),
    ("computer_organization", 12),
    ("operating_system", 10),
    ("computer_network", 8),
)
EXAM408_CHOICE_TOTAL = sum(count for _code, count in EXAM408_CHOICE_BLUEPRINT)
EXAM408_CHOICE_SCORE = Decimal("2.00")
EXAM408_CHOICE_SUBJECT_ORDER = {
    code: index for index, (code, _count) in enumerate(EXAM408_CHOICE_BLUEPRINT)
}
EXAM408_CHOICE_TARGETS = dict(EXAM408_CHOICE_BLUEPRINT)
EXAM408_CHOICE_SUBJECT_NAMES = {
    "data_structure": "数据结构",
    "computer_organization": "计算机组成原理",
    "operating_system": "操作系统",
    "computer_network": "计算机网络",
}


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
    query = select(ExamPaper).where(ExamPaper.deleted_at.is_(None))
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
    stmt = select(ExamPaper).where(
        ExamPaper.id == paper_id,
        ExamPaper.deleted_at.is_(None),
    )
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
        select(ExamPaper.id).where(
            ExamPaper.public_id == value,
            ExamPaper.deleted_at.is_(None),
        )
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


def _format_position_ranges(positions: list[int]) -> str:
    """Format sorted question positions compactly, e.g. 11~14、18、20~22."""
    values = sorted(set(int(position) for position in positions))
    if not values:
        return ""
    ranges: list[str] = []
    start = previous = values[0]
    for value in values[1:]:
        if value == previous + 1:
            previous = value
            continue
        ranges.append(str(start) if start == previous else f"{start}~{previous}")
        start = previous = value
    ranges.append(str(start) if start == previous else f"{start}~{previous}")
    return "、".join(ranges)


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
    if len(items) > EXAM408_CHOICE_TOTAL:
        errors.append(
            f"408 选择题卷最多 {EXAM408_CHOICE_TOTAL} 道，当前 {len(items)} 道"
        )

    if paper.paper_type == "past_exam_choice":
        if paper.year is None:
            errors.append("真题选择题卷必须填写年份")

        score_mismatch_positions: list[int] = []
        for item in items:
            position = int(item["position"])
            if Decimal(str(item["score"])).quantize(Decimal("0.01")) != EXAM408_CHOICE_SCORE:
                score_mismatch_positions.append(position)

        # 不足 40 道时按“当前已有题目”直接允许发布，不再套用完整卷的
        # 固定题号区间。只有恰好 40 道时才要求 10/12/10/8 固定题号结构；
        # 超过 40 道则由上面的总题数上限直接阻止发布。
        if len(items) == EXAM408_CHOICE_TOTAL:
            fixed_ranges = (
                (1, 10, "data_structure", "数据结构"),
                (11, 22, "computer_organization", "计算机组成原理"),
                (23, 32, "operating_system", "操作系统"),
                (33, 40, "computer_network", "计算机网络"),
            )
            for start, end, expected_code, expected_name in fixed_ranges:
                subject_mismatch_positions: list[int] = []
                for item in items:
                    position = int(item["position"])
                    if position < start or position > end:
                        continue
                    actual_code = canonical_408_code(item["subject_code"])
                    if actual_code != expected_code:
                        subject_mismatch_positions.append(position)
                if subject_mismatch_positions:
                    errors.append(
                        f"固定题号 {start}~{end} 应为{expected_name}，科目不匹配题号："
                        f"{_format_position_ranges(subject_mismatch_positions)}"
                    )

        if score_mismatch_positions:
            errors.append(
                "408 统考选择题每题应为 2 分，分值异常题号："
                f"{_format_position_ranges(score_mismatch_positions)}"
            )
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


def _coerce_source_question_no(value: object) -> int | None:
    if value is None:
        return None
    match = re.match(r"^\s*(\d{1,3})(?:\D|$)", str(value))
    if match is None:
        return None
    number = int(match.group(1))
    return number if number > 0 else None


def _source_question_no(content: object, raw_content: str | None) -> int | None:
    """Best-effort recovery of the original exam question number.

    Imported question numbers are intentionally stripped from the student-facing
    stem, but modern import payloads keep ``source_question_no`` in raw metadata.
    Recovering it here lets quick-add prefer the real 1..40 exam slot when more
    than one eligible candidate exists for a year.
    """
    if isinstance(content, dict):
        for key in ("source_question_no", "question_no", "number"):
            number = _coerce_source_question_no(content.get(key))
            if number is not None:
                return number
        source = content.get("source")
        if isinstance(source, dict):
            number = _coerce_source_question_no(source.get("source_question_no"))
            if number is not None:
                return number

    if raw_content:
        match = re.search(
            r"[\"']source_question_no[\"']\s*:\s*[\"']?([0-9]{1,3})",
            raw_content,
        )
        if match is not None:
            return int(match.group(1))
    return None


def _text_has_past_exam_marker(value: object, year: int) -> bool:
    """Return whether arbitrary provenance text clearly identifies a year's real exam.

    Published question stems intentionally have their original question-number label
    stripped, so relying on a single ``【YYYY统考真题】`` stem prefix loses questions
    whose whole source label was removed during publishing.  Import metadata keeps the
    original label/preview and is therefore also accepted as an authoritative signal.
    """
    if value is None:
        return False
    text = re.sub(r"\s+", "", str(value))
    if str(year) not in text:
        return False
    return "统考真题" in text or "408真题" in text or bool(
        re.search(rf"{year}[^\n\r]{{0,12}}真题", text)
    )


def _import_hint_matches_year(hint: dict, year: int) -> bool:
    return any(
        _text_has_past_exam_marker(hint.get(key), year)
        for key in (
            "source_question_label",
            "raw_text_preview",
            "source_file",
            "raw_data",
        )
    )


def _source_question_no_from_hints(hints: list[dict], year: int) -> int | None:
    """Prefer original import metadata when recovering the official 1..40 slot."""
    preferred = [hint for hint in hints if _import_hint_matches_year(hint, year)]
    search_groups = (preferred, hints)
    for group in search_groups:
        for hint in group:
            for key in (
                "source_question_no",
                "source_question_label",
                "raw_text_preview",
            ):
                number = _coerce_source_question_no(hint.get(key))
                if number is not None:
                    return number
            raw_data = hint.get("raw_data")
            if raw_data is not None:
                match = re.search(
                    r"[\"']source_question_no[\"']\s*:\s*[\"']?([0-9]{1,3})",
                    str(raw_data),
                )
                if match is not None:
                    return int(match.group(1))
    return None


def _matches_past_exam_prefix(stem: str, year: int) -> bool:
    if not stem:
        return False
    # The title prefix is the authoritative signal for this shortcut.  Legacy
    # data can have source_type/year missing on the mutable Question projection,
    # so do not make those columns a hard requirement.  Accept both Chinese and
    # ASCII square brackets plus the historical optional space after the year.
    pattern = rf"^[【\[]\s*{year}\s*(?:408\s*)?(?:统考\s*)?真题\s*[】\]]"
    return re.match(pattern, stem) is not None


def _matching_past_exam_content(
    question: Question,
    revision: QuestionVersion,
    year: int,
    import_hints: list[dict] | None = None,
) -> dict | None:
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
            return revision.content if isinstance(revision.content, dict) else content

    hints = import_hints or []
    if any(_import_hint_matches_year(hint, year) for hint in hints):
        if isinstance(revision.content, dict):
            return revision.content
        if isinstance(question.content, dict):
            return question.content

    # Legacy rows sometimes keep the year in structured columns while the source
    # label is stored separately.  Requiring both the exact year and an explicit
    # "真题" source marker avoids pulling ordinary practice questions from the same
    # year into the official-paper shortcut.
    year_matches = int(revision.year or 0) == int(year) or int(question.year or 0) == int(year)
    source_values = (
        revision.source,
        question.source,
        revision.source_file,
        question.source_file,
        revision.raw_content,
        question.raw_content,
    )
    if year_matches and any(
        value is not None and "真题" in str(value) for value in source_values
    ):
        if isinstance(revision.content, dict):
            return revision.content
        if isinstance(question.content, dict):
            return question.content
    return None


def _exam_item_validation_error(
    question: Question,
    revision: QuestionVersion,
    subject: Subject,
) -> str | None:
    """Return a user-safe reason when a question cannot be pinned into a paper.

    Quick-add and save must use exactly the same eligibility rules.  Keeping the
    checks in one helper prevents candidates from appearing selectable only to be
    rejected later by ``replace_exam_paper_items`` with a 422.
    """
    if question.review_status != "approved":
        return "题目尚未审核通过"
    if not question.is_active:
        return "题目已停用"
    if revision.is_active is not True:
        return "当前题目版本未启用"
    if str(question.question_type or "") != QT_SINGLE_CHOICE:
        return "题目类型不是 single_choice"
    if str(revision.question_type or "") != QT_SINGLE_CHOICE:
        return "当前题目版本类型不是 single_choice"
    if int(revision.question_id or 0) != int(question.id):
        return "current revision 绑定异常"
    if int(revision.subject_id or 0) != int(question.subject_id):
        return "current revision 科目不一致"
    if not subject.is_active or canonical_408_code(subject.code) not in EXAM408_CORE_CODES:
        return "不属于启用的 canonical 408 四科"
    if not isinstance(revision.options, dict) or len(revision.options) < 2:
        return "当前题目版本缺少有效选择题选项"
    return None


def _summarize_exam_item_errors(errors: list[tuple[int, str]]) -> str:
    if not errors:
        return ""
    shown = errors[:8]
    text = "；".join(f"Q#{question_id}：{reason}" for question_id, reason in shown)
    if len(errors) > len(shown):
        text += f"；另有 {len(errors) - len(shown)} 道题存在问题"
    return f"以下题目不能保存到试卷：{text}"


def _arrange_408_candidates(items: list[dict]) -> list[dict]:
    """Return quick-add candidates in a deterministic 408-friendly order.

    The official source question number is the strongest signal when available;
    subject quota is the hard layout constraint; stable source order is the
    fallback.  The canonical first 40 slots are 10/12/10/8.  Overflow candidates
    are then interleaved with weighted-fair scoring that considers target ratio,
    remaining overflow pressure, and repeated-subject streaks.

    A malformed/incomplete source pool cannot magically satisfy missing fixed
    slots.  In that case all available candidates are still returned and draft
    validation surfaces the shortage/mismatch before publication.
    """
    if not items:
        return []

    buckets: dict[str, list[dict]] = {
        code: [] for code, _count in EXAM408_CHOICE_BLUEPRINT
    }
    unknown: list[dict] = []
    for item in items:
        code = canonical_408_code(item.get("subject_code"))
        if code in buckets:
            buckets[code].append(item)
        else:
            unknown.append(item)

    arranged: list[dict] = []
    selected_counts: dict[str, int] = {code: 0 for code in buckets}
    remaining: dict[str, list[dict]] = {}
    slot_start = 1

    # Build the official 1..40 section.  Candidates carrying their original
    # question number are reserved for that exact slot first.  Duplicate/number-
    # less candidates only fill holes, so an extra Q1 cannot accidentally push
    # the real Q10 outside the first ten data-structure positions.
    for code, target in EXAM408_CHOICE_BLUEPRINT:
        bucket = buckets[code]
        slot_end = slot_start + target - 1
        primary_by_number: dict[int, dict] = {}
        for item in bucket:
            number = _coerce_source_question_no(item.get("_source_question_no"))
            if number is None or not (slot_start <= number <= slot_end):
                continue
            primary_by_number.setdefault(number, item)

        reserved_ids = {id(item) for item in primary_by_number.values()}
        fallback = [item for item in bucket if id(item) not in reserved_ids]
        selected: list[dict] = []
        fallback_index = 0
        for position in range(slot_start, slot_end + 1):
            item = primary_by_number.get(position)
            if item is None and fallback_index < len(fallback):
                item = fallback[fallback_index]
                fallback_index += 1
            if item is not None:
                selected.append(item)

        selected_ids = {id(item) for item in selected}
        arranged.extend(selected)
        selected_counts[code] = len(selected)
        remaining[code] = [item for item in bucket if id(item) not in selected_ids]
        slot_start = slot_end + 1

    # Position 41+ is outside the official 408 choice section.  Keep surplus
    # useful for admin review, but avoid a giant same-subject tail.
    last_codes: list[str] = []
    for item in arranged[-2:]:
        code = canonical_408_code(item.get("subject_code"))
        if code in buckets:
            last_codes.append(code)

    while any(remaining.values()):
        total_after_pick = len(arranged) + 1
        total_remaining = sum(len(values) for values in remaining.values())
        best_code: str | None = None
        best_score: tuple[float, float, float, int] | None = None

        for code, values in remaining.items():
            if not values:
                continue
            target = EXAM408_CHOICE_TARGETS[code]
            weight = target / EXAM408_CHOICE_TOTAL
            expected_count = total_after_pick * weight
            ratio_deficit = expected_count - selected_counts[code]
            overflow_pressure = len(values) / max(total_remaining, 1)

            streak_penalty = 0.0
            if last_codes and last_codes[-1] == code:
                streak_penalty = 0.20
                if len(last_codes) >= 2 and last_codes[-2] == code:
                    streak_penalty = 1.00

            score = (
                ratio_deficit - streak_penalty,
                overflow_pressure,
                weight,
                -EXAM408_CHOICE_SUBJECT_ORDER[code],
            )
            if best_score is None or score > best_score:
                best_score = score
                best_code = code

        if best_code is None:
            break
        arranged.append(remaining[best_code].pop(0))
        selected_counts[best_code] += 1
        last_codes.append(best_code)
        if len(last_codes) > 2:
            last_codes.pop(0)

    arranged.extend(unknown)
    return arranged


def _select_official_408_candidates(items: list[dict]) -> tuple[list[dict], list[str]]:
    """Select reliable 408 candidates in canonical section order, capped at 40.

    Each subject keeps its official 10/12/10/8 capacity. Missing source positions do
    not prevent the remaining reliable questions from being returned: partial papers
    are valid and later subjects are compacted forward while preserving subject order.
    Original source question numbers win; unnumbered candidates may fill holes inside
    their canonical subject section. Conflicting numbered candidates are not used as a
    fallback because they usually indicate an import/subject classification problem.
    """
    buckets: dict[str, list[dict]] = {
        code: [] for code, _count in EXAM408_CHOICE_BLUEPRINT
    }
    for item in items:
        code = canonical_408_code(item.get("subject_code"))
        if code in buckets:
            buckets[code].append(item)

    selected: list[dict] = []
    diagnostics: list[str] = []
    slot_start = 1
    for code, target in EXAM408_CHOICE_BLUEPRINT:
        slot_end = slot_start + target - 1
        bucket = buckets[code]
        exact_by_number: dict[int, dict] = {}
        unnumbered: list[dict] = []
        conflicting_number_count = 0

        for item in bucket:
            number = _coerce_source_question_no(item.get("_source_question_no"))
            if number is None:
                unnumbered.append(item)
                continue
            if slot_start <= number <= slot_end:
                exact_by_number.setdefault(number, item)
            else:
                conflicting_number_count += 1

        used_ids: set[int] = set()
        missing_positions: list[int] = []
        fallback_index = 0
        section_selected: list[dict] = []
        for position in range(slot_start, slot_end + 1):
            item = exact_by_number.get(position)
            if item is None:
                while fallback_index < len(unnumbered) and id(unnumbered[fallback_index]) in used_ids:
                    fallback_index += 1
                if fallback_index < len(unnumbered):
                    item = unnumbered[fallback_index]
                    fallback_index += 1
            if item is None:
                missing_positions.append(position)
                continue
            used_ids.add(id(item))
            section_selected.append(item)

        selected.extend(section_selected)
        if missing_positions:
            subject_name = EXAM408_CHOICE_SUBJECT_NAMES[code]
            message = (
                f"{subject_name}应有 {target} 道，当前可可靠匹配 {len(section_selected)} 道，"
                f"缺少题号 {_format_position_ranges(missing_positions)}"
            )
            if conflicting_number_count:
                message += f"；另有 {conflicting_number_count} 道原题号与该科固定区间冲突，已忽略"
            diagnostics.append(message)
        slot_start = slot_end + 1

    if len(selected) != EXAM408_CHOICE_TOTAL and not diagnostics:
        diagnostics.append(
            f"408 统考选择题应为 {EXAM408_CHOICE_TOTAL} 道，当前仅可可靠匹配 {len(selected)} 道"
        )
    return selected, diagnostics


async def _load_question_import_hints(
    db: AsyncSession, question_ids: list[int]
) -> dict[int, list[dict]]:
    """Load only provenance needed to recover real-exam identity and source slots."""
    if not question_ids:
        return {}
    result: dict[int, list[dict]] = {}
    unique_ids = list(dict.fromkeys(int(question_id) for question_id in question_ids))
    # Keep SQLite/dev and PostgreSQL both safe from oversized IN parameter lists.
    for offset in range(0, len(unique_ids), 500):
        chunk = unique_ids[offset : offset + 500]
        rows = await db.execute(
            select(
                QuestionImport.question_id,
                QuestionImport.source_question_no,
                QuestionImport.source_question_label,
                QuestionImport.raw_text_preview,
                QuestionImport.source_file,
                QuestionImport.raw_data,
            )
            .where(QuestionImport.question_id.in_(chunk))
            .order_by(QuestionImport.id.desc())
        )
        for (
            question_id,
            source_question_no,
            source_question_label,
            raw_text_preview,
            source_file,
            raw_data,
        ) in rows.all():
            if question_id is None:
                continue
            result.setdefault(int(question_id), []).append(
                {
                    "source_question_no": source_question_no,
                    "source_question_label": source_question_label,
                    "raw_text_preview": raw_text_preview,
                    "source_file": source_file,
                    "raw_data": raw_data,
                }
            )
    return result


async def list_past_exam_candidates(db: AsyncSession, year: int) -> dict:
    rows = await db.execute(
        select(Question, QuestionVersion, Subject)
        .join(QuestionVersion, QuestionVersion.id == Question.current_version_id)
        .join(Subject, Subject.id == Question.subject_id)
        .where(
            Question.review_status == "approved",
            Question.is_active.is_(True),
            QuestionVersion.is_active.is_(True),
            Question.question_type == QT_SINGLE_CHOICE,
            QuestionVersion.question_type == QT_SINGLE_CHOICE,
            Subject.is_active.is_(True),
        )
        .order_by(Question.id.asc())
    )
    eligible_rows = list(rows.all())
    import_hints_by_question = await _load_question_import_hints(
        db, [int(question.id) for question, _revision, _subject in eligible_rows]
    )
    items: list[dict] = []
    for question, revision, subject in eligible_rows:
        # Keep the quick-add candidate contract identical to the final save
        # contract.  A candidate returned here must be safe to pin immediately.
        if _exam_item_validation_error(question, revision, subject) is not None:
            continue
        import_hints = import_hints_by_question.get(int(question.id), [])
        content = _matching_past_exam_content(
            question, revision, year, import_hints=import_hints
        )
        if content is None:
            continue
        source_question_no = _source_question_no_from_hints(import_hints, year)
        if source_question_no is None:
            source_question_no = _source_question_no(
                content, revision.raw_content or question.raw_content
            )
        items.append(
            {
                "question_id": int(question.id),
                "subject_id": int(question.subject_id),
                "subject_code": subject.code,
                "subject_name": subject.name,
                "content": content,
                "year": int(year),
                "source": revision.source or question.source,
                "_source_question_no": source_question_no,
            }
        )
    arranged_items, _diagnostics = _select_official_408_candidates(items)
    for item in arranged_items:
        item.pop("_source_question_no", None)
    return {"year": int(year), "total": len(arranged_items), "items": arranged_items}


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

    validation_errors: list[tuple[int, str]] = []
    for input_item in data.items:
        question, revision, subject = by_id[input_item.question_id]
        reason = _exam_item_validation_error(question, revision, subject)
        if reason is not None:
            validation_errors.append((int(question.id), reason))
    if validation_errors:
        raise ValueError(_summarize_exam_item_errors(validation_errors))

    ordered_items = list(data.items)
    if paper.paper_type == "past_exam_choice":
        # The admin quick-add UI may submit candidates in discovery/database
        # order.  Normalize again at the persistence boundary so the official
        # 408 subject ranges stay correct even if a client is stale or manually
        # reorders the candidate list before saving.
        wrappers: list[dict] = []
        for input_item in ordered_items:
            _question, _revision, subject = by_id[input_item.question_id]
            wrappers.append(
                {
                    "question_id": int(input_item.question_id),
                    "subject_code": subject.code,
                    "_source_question_no": _source_question_no(
                        _revision.content, _revision.raw_content or _question.raw_content
                    ),
                    "_input": input_item,
                }
            )
        ordered_items = [
            wrapper["_input"] for wrapper in _arrange_408_candidates(wrappers)
        ]

    new_rows: list[ExamPaperQuestion] = []
    for position, input_item in enumerate(ordered_items, start=1):
        question, revision, _subject = by_id[input_item.question_id]
        score = (
            EXAM408_CHOICE_SCORE
            if paper.paper_type == "past_exam_choice"
            else Decimal(str(input_item.score)).quantize(Decimal("0.01"))
        )
        new_rows.append(
            ExamPaperQuestion(
                paper_id=paper.id,
                question_id=question.id,
                question_version_id=revision.id,
                position=position,
                score=score,
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
        detail={
            "question_count": len(new_rows),
            "question_ids": [int(item.question_id) for item in ordered_items],
        },
        request=request,
    )



async def _fill_past_exam_paper_items(
    db: AsyncSession,
    paper_id: int,
    operator: AdminPrincipal,
    request: Request | None,
    *,
    replace_existing: bool,
) -> int:
    """Atomically quick-fill or refresh a draft 408 real-exam paper.

    ``replace_existing=False`` is the one-shot quick-add path and is rejected as
    soon as any paper item exists. ``replace_existing=True`` is the refresh path.
    Both paths persist every reliably matched candidate up to the 40-question cap;
    an incomplete year is still useful and publishable. Refresh clears and rebuilds
    the paper in the *same transaction*, so any validation error rolls the old set
    back intact at the route boundary.
    """
    paper = await _get_paper(db, paper_id, lock=True)
    if paper.status != "draft":
        raise ExamPaperStateError("已发布/归档试卷题目不可修改，请新建版本")
    if paper.paper_type != "past_exam_choice":
        raise ExamPaperStateError("仅历年真题选择题卷支持快速填入/刷新题目")
    if paper.year is None:
        raise ValueError("真题选择题卷必须先填写年份")

    existing_count = int(
        (
            await db.scalar(
                select(func.count(ExamPaperQuestion.id)).where(
                    ExamPaperQuestion.paper_id == paper.id
                )
            )
        )
        or 0
    )
    if existing_count and not replace_existing:
        raise ExamPaperStateError(
            "当前试卷已存在题目，快速添加仅允许空试卷使用；请使用“刷新题目”更新整卷。"
        )

    candidate_result = await list_past_exam_candidates(db, int(paper.year))
    candidate_items = list(candidate_result.get("items") or [])
    if not candidate_items:
        raise ValueError(
            f"未匹配到 {int(paper.year)} 年可用的 408 真题选择题，已保留当前试卷题目。"
        )
    if len(candidate_items) > EXAM408_CHOICE_TOTAL:
        # ``list_past_exam_candidates`` already caps by blueprint. Keep this as a
        # persistence-boundary guard in case another caller changes that contract.
        raise ValueError(
            f"快速匹配结果超过 {EXAM408_CHOICE_TOTAL} 道，已取消写入并保留原试卷。"
        )

    candidate_ids = [int(item["question_id"]) for item in candidate_items]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("快速匹配结果存在重复题目，已取消写入并保留原试卷。")

    rows = await db.execute(
        select(Question, QuestionVersion, Subject)
        .join(QuestionVersion, QuestionVersion.id == Question.current_version_id)
        .join(Subject, Subject.id == Question.subject_id)
        .where(Question.id.in_(candidate_ids))
    )
    by_id = {int(question.id): (question, revision, subject) for question, revision, subject in rows.all()}
    if len(by_id) != len(candidate_ids):
        raise ValueError("快速匹配题目在写入前发生变化，已取消操作并保留原试卷。")

    # Recheck eligibility, subject identity, order and per-subject caps at the
    # persistence boundary. For incomplete years later subjects are allowed to
    # move forward; only a complete 40-question paper uses absolute fixed ranges.
    subject_counts = {code: 0 for code, _target in EXAM408_CHOICE_BLUEPRINT}
    last_subject_rank = -1
    new_rows: list[ExamPaperQuestion] = []
    for position, candidate in enumerate(candidate_items, start=1):
        question, revision, subject = by_id[int(candidate["question_id"])]
        reason = _exam_item_validation_error(question, revision, subject)
        if reason is not None:
            raise ValueError(
                f"快速匹配题目 Q#{int(question.id)} 当前不可写入：{reason}；已保留原试卷。"
            )
        actual_code = canonical_408_code(subject.code)
        candidate_code = canonical_408_code(candidate.get("subject_code"))
        if actual_code not in EXAM408_CHOICE_TARGETS or candidate_code != actual_code:
            raise ValueError(
                f"快速匹配第 {position} 题科目在写入前发生变化，已取消操作并保留原试卷。"
            )
        subject_counts[actual_code] += 1
        if subject_counts[actual_code] > EXAM408_CHOICE_TARGETS[actual_code]:
            raise ValueError(
                f"快速匹配的{EXAM408_CHOICE_SUBJECT_NAMES[actual_code]}超过 "
                f"{EXAM408_CHOICE_TARGETS[actual_code]} 道上限，已取消操作并保留原试卷。"
            )
        subject_rank = EXAM408_CHOICE_SUBJECT_ORDER[actual_code]
        if subject_rank < last_subject_rank:
            raise ValueError("快速匹配科目顺序异常，已取消操作并保留原试卷。")
        last_subject_rank = subject_rank
        new_rows.append(
            ExamPaperQuestion(
                paper_id=paper.id,
                question_id=question.id,
                question_version_id=revision.id,
                position=position,
                score=EXAM408_CHOICE_SCORE,
                section_subject_id=question.subject_id,
            )
        )

    if replace_existing:
        await db.execute(
            delete(ExamPaperQuestion).where(ExamPaperQuestion.paper_id == paper.id)
        )
    db.add_all(new_rows)
    paper.updated_by = operator.id
    await db.flush()

    validation_errors = await validate_exam_paper(db, int(paper.id))
    if validation_errors:
        shown = "；".join(validation_errors[:4])
        if len(validation_errors) > 4:
            shown += f"；另有 {len(validation_errors) - 4} 项"
        raise ValueError(
            f"自动组卷结果未通过发布校验，操作已回滚并保留原试卷：{shown}"
        )

    action = (
        "exam.paper.items.refresh_past_exam"
        if replace_existing
        else "exam.paper.items.quick_fill_past_exam"
    )
    await write_admin_audit(
        db,
        operator,
        action,
        "exam_paper",
        paper.id,
        severity="important",
        detail={
            "year": int(paper.year),
            "question_count_before": existing_count,
            "question_count_after": len(new_rows),
            "question_ids": candidate_ids,
            "mode": "refresh" if replace_existing else "quick_fill_once",
        },
        request=request,
    )
    return existing_count


async def quick_fill_past_exam_paper_items(
    db: AsyncSession,
    paper_id: int,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> int:
    return await _fill_past_exam_paper_items(
        db,
        paper_id,
        operator,
        request,
        replace_existing=False,
    )


async def refresh_past_exam_paper_items(
    db: AsyncSession,
    paper_id: int,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> int:
    return await _fill_past_exam_paper_items(
        db,
        paper_id,
        operator,
        request,
        replace_existing=True,
    )


async def clear_exam_paper_items(
    db: AsyncSession,
    paper_id: int,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> int:
    """Delete every pinned question from a draft paper before rebuilding it."""
    paper = await _get_paper(db, paper_id, lock=True)
    if paper.status != "draft":
        raise ExamPaperStateError("已发布/归档试卷题目不可修改，请新建版本")

    question_count = int(
        (
            await db.scalar(
                select(func.count(ExamPaperQuestion.id)).where(
                    ExamPaperQuestion.paper_id == paper.id
                )
            )
        )
        or 0
    )
    await db.execute(
        delete(ExamPaperQuestion).where(ExamPaperQuestion.paper_id == paper.id)
    )
    paper.updated_by = operator.id
    await db.flush()
    await write_admin_audit(
        db,
        operator,
        "exam.paper.items.clear",
        "exam_paper",
        paper.id,
        severity="important",
        detail={
            "question_count_before": question_count,
            "question_count_after": 0,
        },
        request=request,
    )
    return question_count


async def soft_delete_exam_paper(
    db: AsyncSession,
    paper_id: int,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> ExamPaper:
    """Soft-delete an exam paper while preserving attempts and audit history."""
    paper = await _get_paper(db, paper_id, lock=True)
    before = {
        "status": paper.status,
        "is_active": bool(paper.is_active),
        "deleted_at": paper.deleted_at.isoformat() if paper.deleted_at else None,
    }
    deleted_at = utcnow()
    paper.deleted_at = deleted_at
    paper.is_active = False
    if paper.status != "archived":
        paper.status = "archived"
    paper.updated_by = operator.id
    await write_admin_audit(
        db,
        operator,
        "exam.paper.delete",
        "exam_paper",
        paper.id,
        severity="critical",
        detail={
            "before": before,
            "after": {
                "status": paper.status,
                "is_active": False,
                "deleted_at": deleted_at.isoformat(),
            },
            "delete_mode": "soft",
            "title": paper.title,
            "public_id": paper.public_id,
        },
        request=request,
    )
    return paper


async def _same_year_past_exam_conflict(
    db: AsyncSession,
    paper: ExamPaper,
    *,
    statuses: tuple[str, ...],
) -> ExamPaper | None:
    """Return another live paper that would conflict with this real-exam year."""
    if paper.paper_type != "past_exam_choice" or paper.year is None:
        return None
    return await db.scalar(
        select(ExamPaper)
        .where(
            ExamPaper.id != paper.id,
            ExamPaper.deleted_at.is_(None),
            ExamPaper.paper_type == paper.paper_type,
            ExamPaper.year == paper.year,
            ExamPaper.status.in_(statuses),
        )
        .order_by(ExamPaper.id.desc())
        .limit(1)
    )


async def restore_and_publish_exam_paper(
    db: AsyncSession,
    paper_id: int,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> ExamPaper:
    """Restore an archived paper directly to published state when its year is free."""
    paper = await _get_paper(db, paper_id, lock=True)

    # Treat a repeated restore request as idempotent once this same paper is
    # already published. This avoids a misleading 409 when the first request
    # succeeded but the client retried before receiving the response.
    if paper.status == "published" and bool(paper.is_active):
        return paper

    if paper.status != "archived":
        status_label = {
            "draft": "草稿",
            "published": "已发布",
            "archived": "已归档",
        }.get(paper.status, paper.status or "未知")
        raise ExamPaperStateError(
            f"当前试卷状态为「{status_label}」，只有已归档试卷可以还原并重新发布。"
            "页面可能已被其他操作更新，请刷新后确认最新状态。"
        )

    conflict = await _same_year_past_exam_conflict(
        db, paper, statuses=("draft", "published")
    )
    if conflict is not None:
        conflict_status = "已发布" if conflict.status == "published" else "草稿"
        raise ExamPaperStateError(
            f"无法还原：{paper.year} 年已存在{conflict_status}真题《{conflict.title}》。"
            "同一年不能同时存在其他草稿或已发布真题，请先归档、删除或调整冲突试卷后再重试。"
        )

    errors = await validate_exam_paper(db, paper_id)
    if errors:
        raise ValueError(
            "当前归档试卷未通过发布校验：" + "；".join(errors) + "。请处理后再尝试还原发布。"
        )

    before = {
        "status": paper.status,
        "is_active": bool(paper.is_active),
        "published_at": paper.published_at.isoformat() if paper.published_at else None,
    }
    paper.status = "published"
    paper.is_active = True
    paper.published_at = utcnow()
    paper.updated_by = operator.id
    await write_admin_audit(
        db,
        operator,
        "exam.paper.restore_publish",
        "exam_paper",
        paper.id,
        severity="important",
        detail={
            "before": before,
            "after": {
                "status": paper.status,
                "is_active": True,
                "published_at": paper.published_at.isoformat(),
            },
            "year": paper.year,
            "version": paper.version,
        },
        request=request,
    )
    return paper


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
    conflict = await _same_year_past_exam_conflict(
        db, paper, statuses=("published",)
    )
    if conflict is not None:
        raise ExamPaperStateError(
            f"{paper.year} 年已有已发布真题试卷《{conflict.title}》，请先归档后再发布当前试卷。"
        )
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
