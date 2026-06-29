from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from app.core.admin_security import AdminPrincipal
from app.models.admin import AdminUser, Subject
from app.models.question import Question
from app.schemas.admin_subjects import AdminSubjectCreateRequest, AdminSubjectUpdateRequest
from app.services import admin_subject_service
from app.services.admin_subject_service import create_subject, delete_subject, list_subject_tree, update_subject


class _Scalars:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class _Result:
    def __init__(self, value=None, values=None):
        self.value = value
        self.values = values if values is not None else ([] if value is None else [value])

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return _Scalars(self.values)


class _Db:
    def __init__(self, subjects=None, question_count=0):
        self.subjects = subjects or []
        self.question_count = question_count
        self.added = []
        self.deleted = []
        self.flush = AsyncMock()

    async def get(self, model, item_id):
        if model is Subject:
            return next((item for item in self.subjects if item.id == item_id), None)
        if model is Question:
            return None
        return None

    async def execute(self, statement):
        text = str(statement)
        if "questions" in text:
            return _Result()
        if "subjects" in text:
            values = self.subjects
            if "subjects.is_active IS true" in text:
                values = [item for item in values if item.is_active]
            return _Result(values=values)
        return _Result(values=[])

    async def scalar(self, statement):
        text = str(statement)
        if "questions" in text:
            return self.question_count
        if "subjects" in text:
            return sum(1 for item in self.subjects if item.parent_id == 1)
        return 0

    def add(self, item):
        if isinstance(item, Subject):
            item.id = item.id or len(self.subjects) + 1
            item.created_at = datetime(2026, 5, 29)
            item.updated_at = datetime(2026, 5, 29)
            self.subjects.append(item)
        self.added.append(item)

    async def delete(self, item):
        self.deleted.append(item)
        self.subjects.remove(item)


def _principal():
    user = AdminUser(id=9, username="operator", password_hash="hash", is_active=True, role_id=2)
    return AdminPrincipal(user, {})


def _subject(subject_id, code, name, parent_id=None, level=1, path=None, sort_order=0, is_active=True):
    now = datetime(2026, 5, 29)
    return Subject(
        id=subject_id,
        parent_id=parent_id,
        code=code,
        name=name,
        level=level,
        path=path or code,
        sort_order=sort_order,
        is_active=is_active,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_list_subject_tree_builds_hierarchy():
    subjects = [
        _subject(1, "math", "数学", sort_order=1),
        _subject(2, "linear", "线代", parent_id=1, level=2, path="math/linear"),
        _subject(3, "hidden", "隐藏", is_active=False),
    ]

    tree = await list_subject_tree(_Db(subjects))

    assert len(tree) == 1
    assert tree[0]["code"] == "math"
    assert tree[0]["children"][0]["code"] == "linear"


@pytest.mark.asyncio
async def test_create_subject_sets_path_level_and_audit(monkeypatch):
    parent = _subject(1, "math", "数学")
    audit = AsyncMock()
    monkeypatch.setattr(admin_subject_service, "write_admin_audit", audit)

    subject = await create_subject(_Db([parent]), AdminSubjectCreateRequest(code="linear", name="线代", parent_id=1), _principal())

    assert subject.level == 2
    assert subject.path == "math/linear"
    audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_subject_rejects_depth_over_three():
    parent = _subject(3, "deep", "深层", parent_id=2, level=3, path="a/b/deep")

    with pytest.raises(ValueError, match="科目层级不能超过3级"):
        await create_subject(_Db([parent]), AdminSubjectCreateRequest(code="too", name="太深", parent_id=3), _principal())


@pytest.mark.asyncio
async def test_update_subject_moves_subtree_and_rejects_cycle(monkeypatch):
    root = _subject(1, "math", "数学")
    child = _subject(2, "linear", "线代", parent_id=1, level=2, path="math/linear")
    leaf = _subject(3, "matrix", "矩阵", parent_id=2, level=3, path="math/linear/matrix")
    db = _Db([root, child, leaf])
    monkeypatch.setattr(admin_subject_service, "write_admin_audit", AsyncMock())

    with pytest.raises(ValueError, match="不能移动到子科目下级"):
        await update_subject(db, 1, AdminSubjectUpdateRequest(parent_id=2), _principal())

    await update_subject(db, 2, AdminSubjectUpdateRequest(parent_id=None, code="la"), _principal())

    assert child.level == 1
    assert child.path == "la"
    assert leaf.level == 2
    assert leaf.path == "la/matrix"


@pytest.mark.asyncio
async def test_update_subject_allows_code_change_when_referenced_by_id(monkeypatch):
    """Since questions now reference subjects by subject_id (not code),
    changing a subject's code should be allowed even when questions exist."""
    monkeypatch.setattr(admin_subject_service, "write_admin_audit", AsyncMock())
    subj = _subject(1, "math", "数学")
    db = _Db([subj], question_count=1)

    # Should NOT raise — code change is safe because references use subject_id
    result = await update_subject(db, 1, AdminSubjectUpdateRequest(code="new-math"), _principal())
    assert result.code == "new-math"


@pytest.mark.asyncio
async def test_delete_subject_rejects_children_and_question_reference(monkeypatch):
    monkeypatch.setattr(admin_subject_service, "write_admin_audit", AsyncMock())
    root = _subject(1, "math", "数学")
    child = _subject(2, "linear", "线代", parent_id=1, level=2, path="math/linear")

    with pytest.raises(ValueError, match="存在子科目"):
        await delete_subject(_Db([root, child]), 1, _principal())

    with pytest.raises(ValueError, match="已有题目使用该科目"):
        await delete_subject(_Db([root], question_count=1), 1, _principal())

    db = _Db([root])
    await delete_subject(db, 1, _principal())
    assert db.deleted == [root]
