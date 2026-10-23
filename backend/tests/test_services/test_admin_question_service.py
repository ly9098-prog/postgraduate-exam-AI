from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.admin_security import AdminPrincipal
from app.models.admin import AdminUser, QuestionVersion
from app.models.question import Question
from app.schemas.admin_questions import (
    AdminQuestionPatchRequest,
    AdminQuestionToggleActiveRequest,
)
from app.services import admin_question_service
from app.services.admin_question_service import (
    soft_delete_admin_question,
    toggle_active_admin_question,
    update_admin_question,
)


class _Scalars:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values

    def first(self):
        return self.values[0] if self.values else None


class _Result:
    def __init__(self, value=None, values=None):
        self.value = value
        self.values = values if values is not None else ([] if value is None else [value])

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return _Scalars(self.values)

    def all(self):
        return self.values


class _Db:
    def __init__(self, question=None, imports=None, permission_names=None, max_version=None):
        self.question = question
        self.imports = imports or []
        self.permission_names = permission_names or []
        self.max_version = max_version
        self.added = []
        self.commits = 0
        self.rollbacks = 0
        self.flush = AsyncMock(side_effect=self._assign_revision_id)

    def _assign_revision_id(self):
        for item in self.added:
            if isinstance(item, QuestionVersion) and item.id is None:
                item.id = int(getattr(item, "version", 1)) * 100

    async def get(self, model, item_id):
        if model is Question and self.question and self.question.id == item_id:
            return self.question
        return None

    async def scalar(self, statement):
        text = str(statement)
        if "question_versions" in text:
            latest = MagicMock(spec=QuestionVersion)
            latest.id = 200
            latest.version = self.max_version or 1
            latest.state_hash = "stale"
            return latest
        if "question_knowledge_points" in text:
            return None
        return self.question

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def execute(self, statement):
        text = str(statement)
        if "permissions" in text:
            name = self.permission_names[0] if self.permission_names else None
            return _Result(name)
        if "question_imports" in text:
            return _Result(values=self.imports)
        if "questions" in text and "question_hash" in text:
            return _Result(values=[])
        if "question_versions" in text:
            return _Result()
        if "subjects" in text:
            return _Result()
        if "question_knowledge_points" in text:
            return _Result(values=[])
        return _Result(self.question)

    def add(self, item):
        self.added.append(item)


def _principal(user_id=9, role_id=2):
    user = AdminUser(id=user_id, username="operator", password_hash="hash", is_active=True, role_id=role_id)
    return AdminPrincipal(user, {})


def _question(review_status="approved", is_active=True):
    now = datetime(2026, 5, 29)
    return Question(
        id=1,
        subject_id=1,
        question_type="choice",
        content={"text": "题干"},
        options={"A": "1"},
        answer="A",
        analysis="解析",
        difficulty=3,
        import_batch_id="batch-1",
        review_status=review_status,
        is_active=is_active,
        created_at=now,
        updated_at=now,
    )


def _patch_kps(monkeypatch, kps=None):
    """patch load_question_kps / replace_question_knowledge_points（关联表为数据源）。"""
    import app.services.knowledge_point_service as kpsvc

    kps = kps if kps is not None else ["函数"]
    monkeypatch.setattr(
        admin_question_service, "load_question_kps",
        AsyncMock(return_value={1: list(kps)}),
    )
    monkeypatch.setattr(
        kpsvc, "replace_question_knowledge_points", AsyncMock(return_value={}),
    )


@pytest.mark.asyncio
async def test_update_admin_question_snapshots_changes(monkeypatch):
    _patch_kps(monkeypatch)
    question = _question()
    db = _Db(question=question, max_version=2)
    audit = AsyncMock()
    monkeypatch.setattr(admin_question_service, "write_admin_audit", audit)

    result = await update_admin_question(db, 1, AdminQuestionPatchRequest(answer="B", edit_reason="修正"), _principal())

    assert result.answer == "B"
    assert result.review_status == "approved"
    assert result.is_active is True
    version = db.added[0]
    assert isinstance(version, QuestionVersion)
    assert version.version == 3
    assert version.answer == "B"
    assert version.knowledge_point_links == []
    assert audit.await_args.kwargs["severity"] == "important"


@pytest.mark.asyncio
async def test_update_admin_question_keeps_approved_with_review_permission(monkeypatch):
    _patch_kps(monkeypatch)
    question = _question()
    db = _Db(question=question, permission_names=["question:review"])
    audit = AsyncMock()
    monkeypatch.setattr(admin_question_service, "write_admin_audit", audit)

    result = await update_admin_question(db, 1, AdminQuestionPatchRequest(answer="B"), _principal())

    assert result.answer == "B"
    assert result.review_status == "approved"
    assert result.is_active is True


@pytest.mark.asyncio
async def test_soft_delete_and_toggle_active(monkeypatch):
    _patch_kps(monkeypatch)
    question = _question()
    db = _Db(question=question)
    audit = AsyncMock()
    monkeypatch.setattr(admin_question_service, "write_admin_audit", audit)

    deleted = await soft_delete_admin_question(db, 1, _principal())
    assert deleted.is_active is False
    assert audit.await_args.kwargs["severity"] == "critical"

    toggled = await toggle_active_admin_question(db, 1, AdminQuestionToggleActiveRequest(is_active=True), _principal())
    assert toggled.is_active is True


@pytest.mark.asyncio
async def test_toggle_active_rejects_non_approved():
    db = _Db(question=_question(review_status="re_pending", is_active=False))

    with pytest.raises(ValueError, match="非已审核题目不能激活"):
        await toggle_active_admin_question(db, 1, AdminQuestionToggleActiveRequest(is_active=True), _principal())
