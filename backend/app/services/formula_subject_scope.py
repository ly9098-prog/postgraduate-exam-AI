"""Logical subject scopes for student-facing formula queries.

Formula categories remain stored under their canonical database subjects.  This
module only expands logical request codes into those stored subjects and builds
SQL filters over the combined category set, so sorting, pagination, and counts
continue to run on one database query.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import or_, select

from app.models.formula import FormulaCard, FormulaCategory

FORMULA_MATH_SUBJECT_CODE = "math"
FORMULA_MATH_SUBJECT_NAME = "数学"
FORMULA_MATH_SOURCE_CODES: tuple[str, ...] = (
    "elementary_math",
    "math2_high_math",
)

_FORMULA_SUBJECT_EXPANSIONS: dict[str, tuple[str, ...]] = {
    FORMULA_MATH_SUBJECT_CODE: FORMULA_MATH_SOURCE_CODES,
}


def expand_formula_subject_code(subject_code: str | None) -> tuple[str, ...] | None:
    """Resolve a request subject code to stored formula subject codes.

    Unknown and existing canonical codes remain exact-match scopes for backward
    compatibility.  A blank value means that no subject filter is requested.
    """
    code = str(subject_code or "").strip()
    if not code:
        return None
    return _FORMULA_SUBJECT_EXPANSIONS.get(code, (code,))


def _formula_subject_and_chapter_ids(subject_codes: Sequence[str]):
    subject_ids = select(FormulaCategory.id).where(
        FormulaCategory.is_active,
        FormulaCategory.node_type == "subject",
        FormulaCategory.code.in_(subject_codes),
    )
    chapter_ids = select(FormulaCategory.id).where(
        FormulaCategory.is_active,
        FormulaCategory.node_type == "chapter",
        FormulaCategory.parent_id.in_(subject_ids),
    )
    return subject_ids, chapter_ids


def formula_card_category_ids(subject_code: str | None):
    """Return the category-id query used by formula-card subject filtering."""
    subject_codes = expand_formula_subject_code(subject_code)
    if not subject_codes:
        return None

    _, chapter_ids = _formula_subject_and_chapter_ids(subject_codes)
    return select(FormulaCategory.id).where(
        FormulaCategory.is_active,
        or_(
            FormulaCategory.id.in_(chapter_ids),
            FormulaCategory.parent_id.in_(chapter_ids),
        ),
    )


def formula_catalog_category_ids(subject_code: str | None):
    """Return subject, chapter, and group ids for a catalog subject scope."""
    subject_codes = expand_formula_subject_code(subject_code)
    if not subject_codes:
        return None

    subject_ids, chapter_ids = _formula_subject_and_chapter_ids(subject_codes)
    return select(FormulaCategory.id).where(
        FormulaCategory.is_active,
        or_(
            FormulaCategory.id.in_(subject_ids),
            FormulaCategory.parent_id.in_(subject_ids),
            FormulaCategory.parent_id.in_(chapter_ids),
        ),
    )


def apply_formula_subject_filter(query, subject_code: str | None):
    """Apply a logical subject scope to a FormulaCard-selecting query."""
    category_ids = formula_card_category_ids(subject_code)
    if category_ids is None:
        return query
    return query.where(FormulaCard.category_id.in_(category_ids))


def collapse_formula_catalog_subjects(
    tree: list[dict], subject_code: str | None
) -> list[dict]:
    """Expose the logical ``math`` catalog as one synthetic subject node."""
    if str(subject_code or "").strip() != FORMULA_MATH_SUBJECT_CODE:
        return tree

    source_codes = set(FORMULA_MATH_SOURCE_CODES)
    sources = [node for node in tree if node.get("code") in source_codes]
    if not sources:
        return []

    children = [
        {**child, "parent_id": 0}
        for source in sources
        for child in source.get("children", [])
    ]
    children.sort(key=lambda node: (node.get("sort_order", 0), node.get("id", 0)))
    exam_scopes = {source.get("exam_scope") for source in sources}

    return [
        {
            "id": 0,
            "parent_id": None,
            "exam_scope": exam_scopes.pop() if len(exam_scopes) == 1 else None,
            "node_type": "subject",
            "code": FORMULA_MATH_SUBJECT_CODE,
            "name": FORMULA_MATH_SUBJECT_NAME,
            "description": "初等数学与高等数学聚合目录",
            "sort_order": min(source.get("sort_order", 0) for source in sources),
            "is_active": True,
            "available_count": sum(
                source.get("available_count", 0) for source in sources
            ),
            "children": children,
        }
    ]
