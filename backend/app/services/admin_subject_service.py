from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import AdminPrincipal
from app.core.subject_scope import EXAM408_ROOT_CODE, canonical_408_code
from app.models.admin import Subject
from app.models.question import Question
from app.schemas.admin_subjects import (
    AdminSubjectCreateRequest,
    AdminSubjectUpdateRequest,
)
from app.services.admin_audit_service import write_admin_audit


class SubjectConflictError(ValueError):
    pass


class SubjectBusinessRuleError(ValueError):
    pass


async def list_subject_tree(db: AsyncSession, include_inactive: bool = False) -> list[dict]:
    query = select(Subject).order_by(Subject.level.asc(), Subject.sort_order.asc(), Subject.id.asc())
    if not include_inactive:
        query = query.where(Subject.is_active.is_(True))
    result = await db.execute(query)
    subjects = list(result.scalars().all())

    nodes = {subject.id: _subject_to_tree_node(subject) for subject in subjects}
    roots = []
    for subject in subjects:
        node = nodes[subject.id]
        parent = nodes.get(subject.parent_id) if subject.parent_id else None
        if parent:
            parent["children"].append(node)
        else:
            roots.append(node)
    return roots


async def get_subject(db: AsyncSession, subject_id: int) -> Subject:
    subject = await db.get(Subject, subject_id)
    if not subject:
        raise ValueError("科目不存在")
    return subject


async def create_subject(
    db: AsyncSession,
    data: AdminSubjectCreateRequest,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> Subject:
    await _ensure_unique_code(db, data.code)
    parent = await _get_parent(db, data.parent_id)
    product_code = canonical_408_code(data.code, data.name)
    if product_code == EXAM408_ROOT_CODE and parent is not None:
        raise SubjectBusinessRuleError("408 根科目必须保持为一级科目")
    if product_code and product_code != EXAM408_ROOT_CODE:
        if parent is None or canonical_408_code(parent.code, parent.name) != EXAM408_ROOT_CODE:
            raise SubjectBusinessRuleError("408 四个核心子科目必须直属 408 根科目")

    level = parent.level + 1 if parent else 1
    if level > 3:
        raise SubjectBusinessRuleError("科目层级不能超过3级")

    subject = Subject(
        parent_id=parent.id if parent else None,
        code=data.code,
        name=data.name,
        level=level,
        path=_build_path(parent.path if parent else None, data.code),
        sort_order=data.sort_order,
        is_active=data.is_active,
    )
    db.add(subject)
    await db.flush()
    await write_admin_audit(
        db,
        operator,
        "subject.create",
        "subject",
        subject.id,
        detail={"after": _subject_state(subject)},
        request=request,
    )
    return subject


async def update_subject(
    db: AsyncSession,
    subject_id: int,
    data: AdminSubjectUpdateRequest,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> Subject:
    subject = await get_subject(db, subject_id)
    before = _subject_state(subject)
    update_data = data.model_dump(exclude_unset=True)
    confirm_core_disable = bool(update_data.pop("confirm_core_disable", False))
    new_code = update_data.get("code", subject.code)
    new_name = update_data.get("name", subject.name)

    current_product_code = canonical_408_code(subject.code, subject.name)
    next_product_code = canonical_408_code(new_code, new_name)
    if current_product_code and next_product_code != current_product_code:
        raise SubjectBusinessRuleError("408 核心科目的产品身份不能改为其他科目")

    if (
        current_product_code == EXAM408_ROOT_CODE
        and update_data.get("is_active") is False
        and subject.is_active
        and not confirm_core_disable
    ):
        raise SubjectBusinessRuleError("停用 408 根科目会隐藏全部 408 学习入口，请确认后重试")

    if new_code != subject.code:
        await _ensure_unique_code(db, new_code, subject.id)
        q_count = await _question_count_for_subject(db, subject.id)
        if q_count > 0:
            raise ValueError("已有题目使用该科目，不能修改编码")

    all_subjects = await _list_all_subjects(db)
    parent_changed = "parent_id" in update_data and update_data["parent_id"] != subject.parent_id
    code_changed = new_code != subject.code
    if parent_changed:
        new_parent_id = update_data["parent_id"]
        if new_parent_id == subject.id:
            raise SubjectBusinessRuleError("不能移动到自身下级")
        if new_parent_id and _is_descendant(all_subjects, subject.id, new_parent_id):
            raise SubjectBusinessRuleError("不能移动到子科目下级")
        parent = await _get_parent(db, new_parent_id)
    else:
        parent = await _get_parent(db, subject.parent_id)

    if current_product_code == EXAM408_ROOT_CODE and parent is not None:
        raise SubjectBusinessRuleError("408 根科目必须保持为一级科目")
    if current_product_code and current_product_code != EXAM408_ROOT_CODE:
        if parent is None or canonical_408_code(parent.code, parent.name) != EXAM408_ROOT_CODE:
            raise SubjectBusinessRuleError("408 四个核心子科目必须直属 408 根科目")

    new_level = parent.level + 1 if parent else 1
    subtree_depth = _subtree_depth(all_subjects, subject.id)
    if new_level + subtree_depth - 1 > 3:
        raise SubjectBusinessRuleError("科目层级不能超过3级")

    for field in ("name", "sort_order", "is_active"):
        if field in update_data:
            setattr(subject, field, update_data[field])
    subject.code = new_code
    subject.parent_id = parent.id if parent else None
    subject.level = new_level
    subject.path = _build_path(parent.path if parent else None, subject.code)

    if parent_changed or code_changed:
        _sync_descendant_paths(all_subjects, subject)

    await write_admin_audit(
        db,
        operator,
        "subject.update",
        "subject",
        subject.id,
        severity="important" if parent_changed or code_changed else "normal",
        detail={"before": before, "after": _subject_state(subject)},
        request=request,
    )
    return subject


async def delete_subject(
    db: AsyncSession,
    subject_id: int,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> None:
    subject = await get_subject(db, subject_id)
    if canonical_408_code(subject.code, subject.name):
        raise SubjectBusinessRuleError("408 核心科目不能删除；如需临时隐藏，请使用停用")
    child_count = await db.scalar(select(func.count()).select_from(Subject).where(Subject.parent_id == subject.id))
    if child_count:
        raise SubjectBusinessRuleError("存在子科目，不能删除")
    question_count = await _question_count_for_subject(db, subject.id)
    if question_count:
        raise SubjectBusinessRuleError("已有题目使用该科目，不能删除")

    before = _subject_state(subject)
    await db.delete(subject)
    await write_admin_audit(
        db,
        operator,
        "subject.delete",
        "subject",
        subject.id,
        severity="critical",
        detail={"before": before},
        request=request,
    )


def _subject_to_tree_node(subject: Subject) -> dict:
    data = _subject_state(subject)
    data["created_at"] = subject.created_at
    data["updated_at"] = subject.updated_at
    data["children"] = []
    return data


def _subject_state(subject: Subject) -> dict:
    return {
        "id": subject.id,
        "parent_id": subject.parent_id,
        "code": subject.code,
        "name": subject.name,
        "level": subject.level,
        "path": subject.path,
        "sort_order": subject.sort_order,
        "is_active": subject.is_active,
    }


def _build_path(parent_path: str | None, code: str) -> str:
    return f"{parent_path}/{code}" if parent_path else code


async def _get_parent(db: AsyncSession, parent_id: int | None) -> Subject | None:
    if parent_id is None:
        return None
    parent = await db.get(Subject, parent_id)
    if not parent:
        raise SubjectBusinessRuleError("父级科目不存在")
    return parent


async def _ensure_unique_code(db: AsyncSession, code: str, exclude_id: int | None = None) -> None:
    query = select(Subject).where(Subject.code == code)
    if exclude_id is not None:
        query = query.where(Subject.id != exclude_id)
    result = await db.execute(query)
    if result.scalar_one_or_none():
        raise SubjectConflictError("科目编码已存在")


async def _question_count_for_subject(db: AsyncSession, subject_id: int) -> int:
    from app.models.question_import import QuestionImport
    q_count = await db.scalar(
        select(func.count()).select_from(Question).where(Question.subject_id == subject_id)
    )
    qi_count = await db.scalar(
        select(func.count()).select_from(QuestionImport).where(QuestionImport.subject_id == subject_id)
    )
    return int((q_count or 0) + (qi_count or 0))


async def _list_all_subjects(db: AsyncSession) -> list[Subject]:
    result = await db.execute(select(Subject).order_by(Subject.level.asc(), Subject.sort_order.asc(), Subject.id.asc()))
    return list(result.scalars().all())


def _children_by_parent(subjects: list[Subject]) -> dict[int | None, list[Subject]]:
    children: dict[int | None, list[Subject]] = {}
    for item in subjects:
        children.setdefault(item.parent_id, []).append(item)
    return children


def _is_descendant(subjects: list[Subject], root_id: int, candidate_id: int) -> bool:
    children = _children_by_parent(subjects)
    stack = list(children.get(root_id, []))
    while stack:
        item = stack.pop()
        if item.id == candidate_id:
            return True
        stack.extend(children.get(item.id, []))
    return False


def _subtree_depth(subjects: list[Subject], root_id: int) -> int:
    children = _children_by_parent(subjects)

    def walk(subject_id: int) -> int:
        child_depths = [walk(child.id) for child in children.get(subject_id, [])]
        return 1 + (max(child_depths) if child_depths else 0)

    return walk(root_id)


def _sync_descendant_paths(subjects: list[Subject], root: Subject) -> None:
    children = _children_by_parent(subjects)

    def walk(parent: Subject) -> None:
        for child in children.get(parent.id, []):
            child.level = parent.level + 1
            child.path = _build_path(parent.path, child.code)
            walk(child)

    walk(root)


# ---------------------------------------------------------------------------
# Subject resolver: legacy string → subject_id (for backward compatibility)
# ---------------------------------------------------------------------------

_SUBJECT_CODE_MAP: dict[str, int] | None = None


async def resolve_subject_id(
    db: AsyncSession, subject: str | int | None
) -> int | None:
    """Resolve a legacy subject string or subject_id to a valid subject_id.

    Accepts:
    - int: used directly as subject_id (validated to exist)
    - str: matched against subjects.code (exact), then suffix after last '-'

    Returns None if the subject cannot be resolved.
    Raises ValueError if the subject is explicitly invalid.
    """
    if subject is None:
        return None
    if isinstance(subject, int):
        subj = await db.get(Subject, subject)
        if subj:
            return subject
        return None

    # Build code → id map (cached per call)
    rows = (await db.execute(select(Subject.id, Subject.code))).all()
    code_map = {row.code.lower(): row.id for row in rows}

    key = subject.lower().strip()
    if key in code_map:
        return code_map[key]
    if "-" in key:
        suffix = key.rsplit("-", 1)[1]
        if suffix in code_map:
            return code_map[suffix]
    return None


async def resolve_subject_ids(
    db: AsyncSession, subject: str | int | None,
    include_descendants: bool = True,
) -> list[int]:
    """Resolve to all subject_ids matching the given subject identifier.

    For simple matches behaves like resolve_subject_id (returns 0-1 items).
    This replaces the old ``Question.subject.like(f"{subject}-%")`` pattern
    by resolving the subject tree: if subject maps to a parent, all descendant
    subject_ids are included (unless include_descendants=False).

    Args:
        db: Database session.
        subject: Subject code (str) or ID (int).
        include_descendants: If True (default), include all descendant subject
            IDs. If False, return only the exact matching subject ID.
            Default True maintains backward compatibility.
    """
    sid = await resolve_subject_id(db, subject)
    if sid is None:
        return []

    if not include_descendants:
        return [sid]

    # Check if this subject has children → include them all
    all_subjs = (await db.execute(
        select(Subject).order_by(Subject.level.asc(), Subject.sort_order.asc(), Subject.id.asc())
    )).scalars().all()
    subjects_list = list(all_subjs)

    descendant_ids = {sid}
    children = _children_by_parent(subjects_list)
    stack = list(children.get(sid, []))
    while stack:
        node = stack.pop()
        descendant_ids.add(node.id)
        stack.extend(children.get(node.id, []))

    return list(descendant_ids)
