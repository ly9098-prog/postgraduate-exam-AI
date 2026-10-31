"""Regression coverage for the ENV-02 login and import-approval audit gaps."""

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import HTTPException, Request, Response
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1 import admin_auth, admin_imports
from app.core.admin_security import AdminPrincipal
from app.core.orm_base import Base
from app.models.admin import AdminUser, AuditLog, Role, Subject
from app.models.question_import import QuestionImport
from app.schemas.admin_auth import AdminLoginRequest


@pytest_asyncio.fixture
async def audit_db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'audit.db'}")
    tables = [
        Role.__table__, AdminUser.__table__, AuditLog.__table__,
        Subject.__table__, QuestionImport.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        role = Role(id=1, name="admin", display_name="Audit test")
        user = AdminUser(
            id=1, username="audit-operator", password_hash="test-only-hash",
            role_id=1, is_active=True,
        )
        db.add_all([role, user, QuestionImport(
            id=1, batch_id="audit-batch", source_type="manual",
            raw_data={}, parsed_content={"text": "Synthetic question"},
            parsed_options={"A": "1", "B": "2"}, parsed_answer="A",
            question_type="single_choice",
        )])
        await db.commit()
    monkeypatch.setattr(admin_auth, "_read_fail_count", AsyncMock(return_value=0))
    monkeypatch.setattr(admin_auth, "_clear_fail_count", AsyncMock())
    monkeypatch.setattr(admin_auth, "_increment_fail_count", AsyncMock(return_value=1))
    from app.features import question_publish_service

    monkeypatch.setattr(
        question_publish_service, "publish_single_question",
        AsyncMock(return_value={"status": "duplicate", "question_id": 73}),
    )
    try:
        yield sessions
    finally:
        await engine.dispose()


def _request() -> Request:
    return Request({
        "type": "http", "method": "POST", "path": "/audit-test",
        "headers": [(b"user-agent", b"env02-audit-test")],
        "client": ("192.0.2.1", 1234),
    })


async def _login(db, monkeypatch, response):
    user = await db.get(AdminUser, 1)
    role = await db.get(Role, 1)
    monkeypatch.setattr(admin_auth, "authenticate_admin", AsyncMock(return_value=user))
    monkeypatch.setattr(
        admin_auth, "build_admin_login_response",
        AsyncMock(return_value=("test-access", "test-refresh", user, role, [])),
    )
    return await admin_auth.login(
        AdminLoginRequest(username=user.username, password="test-only-input"),
        _request(), response, db=db,
    )


async def _approve(db):
    principal = AdminPrincipal(await db.get(AdminUser, 1), {})
    return await admin_imports.approve_import_question_item(
        1, _request(), db=db, current_admin=principal,
    )


@pytest.mark.asyncio
async def test_login_commits_safe_audit_with_login_fields(audit_db, monkeypatch):
    response = Response()
    async with audit_db() as db:
        await _login(db, monkeypatch, response)
    async with audit_db() as db:
        rows = (await db.scalars(select(AuditLog))).all()
        assert len(rows) == 1
        log = rows[0]
        assert (log.action, log.resource_type, log.resource_id) == (
            "system.login", "admin_user", "1",
        )
        assert (log.operator_id, log.operator_name, log.status) == (
            1, "audit-operator", "success",
        )
        assert (log.ip, log.user_agent, log.severity) == (
            "192.0.2.1", "env02-audit-test", "low",
        )
        assert not log.detail
        user = await db.get(AdminUser, 1)
        assert user.last_login_at is not None
        assert user.last_login_ip == log.ip
    assert "admin_refresh_token=" in response.headers["set-cookie"]


@pytest.mark.asyncio
async def test_failed_login_creates_no_success_audit(audit_db, monkeypatch):
    monkeypatch.setattr(
        admin_auth, "authenticate_admin",
        AsyncMock(side_effect=ValueError("invalid credentials")),
    )
    async with audit_db() as db:
        with pytest.raises(HTTPException) as error:
            await admin_auth.login(
                AdminLoginRequest(username="audit-operator", password="test-only-input"),
                _request(), Response(), db=db,
            )
        assert error.value.status_code == 401
    async with audit_db() as db:
        assert (await db.scalars(select(AuditLog))).all() == []
        assert (await db.get(AdminUser, 1)).last_login_at is None


@pytest.mark.asyncio
async def test_approval_audit_persists_once_and_replay_adds_none(audit_db):
    async with audit_db() as db:
        result = await _approve(db)
        assert result.status == "published"
    async with audit_db() as db:
        with pytest.raises(HTTPException) as error:
            await _approve(db)
        assert error.value.status_code == 422
    async with audit_db() as db:
        rows = (await db.scalars(select(AuditLog))).all()
        assert len(rows) == 1
        log = rows[0]
        assert (log.action, log.resource_type, log.resource_id) == (
            "import.approve", "import", "1",
        )
        assert (log.operator_id, log.ip, log.user_agent) == (
            1, "192.0.2.1", "env02-audit-test",
        )
        assert log.severity == "important"
        assert log.detail == {
            "batch_id": "audit-batch", "question_id": 73, "status": "published",
        }
        row = await db.get(QuestionImport, 1)
        assert (row.status, row.reviewed_by, row.question_id) == ("published", 1, 73)


@pytest.mark.asyncio
async def test_publish_rejection_writes_no_success_audit(audit_db, monkeypatch):
    from app.features import question_publish_service

    monkeypatch.setattr(
        question_publish_service, "publish_single_question",
        AsyncMock(return_value={"status": "failed", "reason": "synthetic rejection"}),
    )
    async with audit_db() as db:
        with pytest.raises(HTTPException) as error:
            await _approve(db)
        assert error.value.status_code == 422
    async with audit_db() as db:
        assert (await db.scalars(select(AuditLog))).all() == []
        row = await db.get(QuestionImport, 1)
        assert (row.status, row.reviewed_by, row.question_id) == ("pending", None, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["login", "approve"])
async def test_audit_insert_failure_rolls_back_business(
    audit_db, monkeypatch, operation,
):
    def reject_audit(_mapper, _connection, _target):
        raise RuntimeError("synthetic audit persistence failure")

    response = Response()
    event.listen(AuditLog, "before_insert", reject_audit)
    try:
        async with audit_db() as db:
            with pytest.raises(RuntimeError, match="synthetic audit persistence failure"):
                if operation == "login":
                    await _login(db, monkeypatch, response)
                else:
                    await _approve(db)
    finally:
        event.remove(AuditLog, "before_insert", reject_audit)
    assert "set-cookie" not in response.headers
    async with audit_db() as db:
        assert (await db.scalars(select(AuditLog))).all() == []
        assert (await db.get(AdminUser, 1)).last_login_at is None
        row = await db.get(QuestionImport, 1)
        assert (row.status, row.reviewed_by, row.question_id) == ("pending", None, None)
