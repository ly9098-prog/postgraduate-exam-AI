"""Public formula-library filters responsibilities, with live caller ports."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _exam_scope_values(exam_scope: str | None, *, ports) -> tuple[str, ...] | None:
    raw = ports("str")(exam_scope or "").strip().lower()
    if not raw:
        return None
    return (
        (ports("EXAM408_FORMULA_SCOPE"),)
        if raw == ports("EXAM408_FORMULA_SCOPE")
        else (raw,)
    )


def _apply_study_card_type_filter(query, study_card_type: str | None, *, ports):
    if not study_card_type or study_card_type == "all":
        return query
    normalized = ports("validate_study_card_type")(study_card_type)
    return query.where(ports("FormulaCard").study_card_type == normalized)


def _apply_library_type_filter(query, library_type: str | None, *, ports):
    if library_type is None or library_type == "formula":
        return query
    if library_type == "function_graph":
        exists_subq = (
            ports("select")(ports("FormulaGraphAsset").id)
            .where(
                ports("FormulaGraphAsset").formula_card_id == ports("FormulaCard").id,
                ports("FormulaGraphAsset").image_url.isnot(None),
            )
            .exists()
        )
        return query.where(
            ports("or_")(
                ports("FormulaCard").card_type == "function_graph",
                ports("and_")(
                    ~ports("FormulaCard").card_type.in_(
                        ["function_graph", "pure_formula"]
                    ),
                    exists_subq,
                ),
            )
        )
    raise ports("HTTPException")(
        status_code=400,
        detail=f"无效的 library_type: '{library_type}'，允许的值: formula, function_graph",
    )


async def _validate_chapter(
    db: AsyncSession, chapter_id: int, subject_code: str | None, *, ports
) -> None:
    result = await db.execute(
        ports("select")(ports("FormulaCategory")).where(
            ports("FormulaCategory").id == chapter_id,
            ports("FormulaCategory").is_active,
            ports("FormulaCategory").node_type == "chapter",
        )
    )
    chapter = result.scalar_one_or_none()
    if not chapter:
        raise ports("HTTPException")(
            status_code=400, detail=f"章节 ID {chapter_id} 不存在或不是章节目录"
        )
    subject_codes = ports("expand_formula_subject_code")(subject_code)
    if subject_codes:
        subject_result = await db.execute(
            ports("select")(ports("FormulaCategory").id).where(
                ports("FormulaCategory").is_active,
                ports("FormulaCategory").code.in_(subject_codes),
                ports("FormulaCategory").node_type == "subject",
            )
        )
        subject_ids = ports("set")(subject_result.scalars().all())
        if subject_ids and chapter.parent_id not in subject_ids:
            raise ports("HTTPException")(
                status_code=400,
                detail=f"章节 ID {chapter_id} 不属于学科 {subject_code}",
            )


def _apply_list_filters(
    query, subject_code, chapter_id, category_id, tags, q, *, ports
):
    query = ports("apply_formula_subject_filter")(query, subject_code)
    if chapter_id:
        scoped_category_ids_subq = ports("select")(ports("FormulaCategory").id).where(
            ports("FormulaCategory").is_active,
            ports("or_")(
                ports("FormulaCategory").id == chapter_id,
                ports("FormulaCategory").parent_id == chapter_id,
            ),
        )
        query = query.where(
            ports("FormulaCard").category_id.in_(scoped_category_ids_subq)
        )
    if category_id:
        query = query.where(ports("FormulaCard").category_id == category_id)
    if tags:
        tag_codes = [t.strip() for t in tags.split(",") if t.strip()]
        if tag_codes:
            matching_card_ids = (
                ports("select")(ports("FormulaCardTag").formula_card_id)
                .join(
                    ports("FormulaTag"),
                    ports("FormulaCardTag").tag_id == ports("FormulaTag").id,
                )
                .where(ports("FormulaTag").code.in_(tag_codes))
                .group_by(ports("FormulaCardTag").formula_card_id)
                .having(
                    ports("func").count(ports("FormulaCardTag").formula_card_id)
                    == ports("len")(tag_codes)
                )
            )
            query = query.where(ports("FormulaCard").id.in_(matching_card_ids))
    if q:
        like_pattern = f"%{q}%"
        query = query.where(
            ports("or_")(
                ports("FormulaCard").title.ilike(like_pattern),
                ports("FormulaCard").search_text.ilike(like_pattern),
            )
        )
    return query
