"""Comprehensive tests for the admin audit logging system."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    func,
    select,
)
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.admin_security import AdminPrincipal
from app.core.time_utils import utcnow
from app.models.admin import AdminUser, AuditLog
from app.services.admin_audit_service import (
    cleanup_expired_admin_audit_logs,
    get_admin_audit_log,
    list_admin_audit_logs,
    write_admin_audit,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def operator():
    user = AdminUser(id=1, username="admin", password_hash="hash", is_active=True, role_id=1)
    return AdminPrincipal(user, {})


@pytest.fixture
def mock_request():
    class MockClient:
        host = "127.0.0.1"

    class MockRequest:
        client = MockClient()

        @property
        def headers(self):
            return type("Headers", (), {"get": lambda self, key, default=None: "test-agent" if key == "user-agent" else default})()

    return MockRequest()


async def _init_db():
    """Create an isolated in-memory SQLite with only the audit_logs table."""
    engine = create_async_engine("sqlite+aiosqlite://")
    metadata = MetaData()
    Table(
        "audit_logs",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("operator_id", Integer, nullable=True),
        Column("operator_name", String(64), nullable=True),
        Column("action", String(128), nullable=False),
        Column("resource_type", String(64), nullable=True),
        Column("resource_id", String(64), nullable=True),
        Column("severity", String(16), nullable=False),
        Column("detail", JSON, nullable=True),
        Column("ip", String(45), nullable=True),
        Column("user_agent", String(256), nullable=True),
        Column("status", String(16), nullable=False, server_default="success"),
        Column("error_message", Text, nullable=True),
        Column("created_at", DateTime, server_default=func.now()),
    )
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    session = sm()
    return engine, session


# ============================================================================
# Audit Write Tests
# ============================================================================


@pytest.mark.asyncio
async def test_write_audit_basic(operator, mock_request):
    """编辑题目后生成 question.update 日志"""
    engine, db = await _init_db()
    try:
        log = await write_admin_audit(
            db, operator, "question.update", "question", 123,
            severity="important",
            detail={"changed_fields": ["content", "answer"]},
            request=mock_request,
        )
        await db.commit()

        assert log.action == "question.update"
        assert log.resource_type == "question"
        assert log.resource_id == "123"
        assert log.severity == "important"
        assert log.operator_id == 1
        assert log.operator_name == "admin"
    finally:
        await db.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_write_audit_contains_ip_and_user_agent(operator, mock_request):
    """日志包含操作人、资源ID、IP、User-Agent"""
    engine, db = await _init_db()
    try:
        log = await write_admin_audit(
            db, operator, "question.update", "question", 456,
            request=mock_request,
        )
        await db.commit()

        assert log.ip == "127.0.0.1"
        assert log.user_agent == "test-agent"
        assert log.operator_id == 1
        assert log.resource_id == "456"
    finally:
        await db.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_write_audit_without_request(operator):
    """没有 request 时 IP 和 User-Agent 为 None"""
    engine, db = await _init_db()
    try:
        log = await write_admin_audit(db, operator, "test.without_request", "test", 1)
        await db.commit()

        assert log.ip is None
        assert log.user_agent is None
    finally:
        await db.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_write_audit_detail_contains_question_summary(operator, mock_request):
    """日志包含题目摘要"""
    engine, db = await _init_db()
    try:
        detail = {
            "question": {
                "id": 789,
                "content_preview": "关于二叉树的遍历方法",
                "subject_name": "数学",
                "question_type": "choice",
            },
        }
        log = await write_admin_audit(
            db, operator, "question.update", "question", 789,
            detail=detail, request=mock_request,
        )
        await db.commit()

        assert log.detail is not None
        assert log.detail["question"]["content_preview"] == "关于二叉树的遍历方法"
        assert log.detail["question"]["subject_name"] == "数学"
    finally:
        await db.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_write_audit_no_sensitive_data_in_detail(operator, mock_request):
    """detail 中不包含敏感字段（password、api_key 等应被清洗）"""
    engine, db = await _init_db()
    try:
        detail = {
            "username": "admin",
            "password": "supersecret",
            "api_key": "sk-123456",
        }
        log = await write_admin_audit(
            db, operator, "test.sensitive", "test", 1,
            detail=detail, request=mock_request,
        )
        await db.commit()

        assert log.detail["password"] == "[REDACTED]"
        assert log.detail["api_key"] == "[REDACTED]"
        assert log.detail["username"] == "admin"
    finally:
        await db.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_write_failed_audit_safely(tmp_path):
    """失败操作能够安全记录 failed 日志"""
    from app.services.admin_audit_service import write_failed_admin_audit_safely

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'failed_audit.db'}")
    metadata = MetaData()
    Table("audit_logs", metadata,
          Column("id", Integer, primary_key=True, autoincrement=True),
          Column("operator_id", Integer, nullable=True),
          Column("operator_name", String(64), nullable=True),
          Column("action", String(128), nullable=False),
          Column("resource_type", String(64), nullable=True),
          Column("resource_id", String(64), nullable=True),
          Column("severity", String(16), nullable=False),
          Column("detail", JSON, nullable=True),
          Column("ip", String(45), nullable=True),
          Column("user_agent", String(256), nullable=True),
          Column("status", String(16), nullable=False, server_default="success"),
          Column("error_message", Text, nullable=True),
          Column("created_at", DateTime, server_default=func.now()),
          )
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)

    import app.core.database as db_mod
    original = db_mod.async_session
    db_mod.async_session = sm
    try:
        user = AdminUser(id=1, username="admin", password_hash="hash", is_active=True, role_id=1)
        op = AdminPrincipal(user, {})

        class MockClient:
            host = "10.0.0.1"

        class MockReq:
            client = MockClient()
            headers = type("H", (), {"get": lambda self, k, d=None: "agent" if k == "user-agent" else d})()

        log = await write_failed_admin_audit_safely(
            op, "question.update", "question", 999,
            severity="important",
            detail={"reason": "权限不足"},
            request=MockReq(),
            error_message="用户无权限修改题目",
        )
        assert log is not None
        assert log.status == "failed"
        assert log.action == "question.update"
        assert log.error_message == "用户无权限修改题目"
        assert log.operator_id == 1
    finally:
        db_mod.async_session = original
    await engine.dispose()


@pytest.mark.asyncio
async def test_write_failed_audit_safely_no_request(tmp_path):
    """write_failed_admin_audit_safely 不抛出异常，即使没有 request"""
    from app.services.admin_audit_service import write_failed_admin_audit_safely

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'failed_audit2.db'}")
    metadata = MetaData()
    Table("audit_logs", metadata,
          Column("id", Integer, primary_key=True, autoincrement=True),
          Column("operator_id", Integer, nullable=True),
          Column("operator_name", String(64), nullable=True),
          Column("action", String(128), nullable=False),
          Column("resource_type", String(64), nullable=True),
          Column("resource_id", String(64), nullable=True),
          Column("severity", String(16), nullable=False),
          Column("detail", JSON, nullable=True),
          Column("ip", String(45), nullable=True),
          Column("user_agent", String(256), nullable=True),
          Column("status", String(16), nullable=False, server_default="success"),
          Column("error_message", Text, nullable=True),
          Column("created_at", DateTime, server_default=func.now()),
          )
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)

    import app.core.database as db_mod
    original = db_mod.async_session
    db_mod.async_session = sm
    try:
        user = AdminUser(id=1, username="admin", password_hash="hash", is_active=True, role_id=1)
        op = AdminPrincipal(user, {})
        log = await write_failed_admin_audit_safely(op, "test.action", "test", 1, error_message="test error")
        assert log is not None
        assert log.status == "failed"
    finally:
        db_mod.async_session = original
    await engine.dispose()


# ============================================================================
# Audit Query Tests
# ============================================================================


@pytest.mark.asyncio
async def test_list_audit_by_action():
    """按 action 查询"""
    engine, db = await _init_db()
    try:
        now = utcnow()
        for action in ("question.update", "question.delete", "subject.create"):
            db.add(AuditLog(operator_id=1, operator_name="admin", action=action,
                            resource_type="test", severity="normal", status="success",
                            created_at=now))
        await db.commit()

        items, total = await list_admin_audit_logs(db, 1, 20, action="question.update")
        assert total == 1
        assert items[0].action == "question.update"
    finally:
        await db.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_list_audit_by_resource_type():
    """按 resourceType 查询"""
    engine, db = await _init_db()
    try:
        now = utcnow()
        db.add(AuditLog(operator_id=1, operator_name="admin", action="test.a",
                        resource_type="question", severity="normal", status="success", created_at=now))
        db.add(AuditLog(operator_id=1, operator_name="admin", action="test.b",
                        resource_type="subject", severity="normal", status="success", created_at=now))
        await db.commit()

        items, total = await list_admin_audit_logs(db, 1, 20, resource_type="question")
        assert total == 1
    finally:
        await db.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_list_audit_by_status():
    """按 status 查询"""
    engine, db = await _init_db()
    try:
        now = utcnow()
        db.add(AuditLog(operator_id=1, operator_name="admin", action="test.ok",
                        resource_type="test", severity="normal", status="success", created_at=now))
        db.add(AuditLog(operator_id=1, operator_name="admin", action="test.fail",
                        resource_type="test", severity="normal", status="failed", created_at=now))
        await db.commit()

        items, total = await list_admin_audit_logs(db, 1, 20, log_status="failed")
        assert total == 1
        assert items[0].status == "failed"
    finally:
        await db.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_list_audit_by_severity():
    """按 severity 查询"""
    engine, db = await _init_db()
    try:
        now = utcnow()
        db.add(AuditLog(operator_id=1, operator_name="admin", action="test.critical",
                        resource_type="test", severity="critical", status="success", created_at=now))
        db.add(AuditLog(operator_id=1, operator_name="admin", action="test.normal",
                        resource_type="test", severity="normal", status="success", created_at=now))
        await db.commit()

        items, total = await list_admin_audit_logs(db, 1, 20, severity="critical")
        assert total == 1
    finally:
        await db.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_keyword_search_action():
    """keyword 可以搜索 action"""
    engine, db = await _init_db()
    try:
        now = utcnow()
        db.add(AuditLog(operator_id=1, operator_name="admin", action="question.update",
                        resource_type="test", severity="normal", status="success", created_at=now))
        db.add(AuditLog(operator_id=1, operator_name="admin", action="subject.create",
                        resource_type="test", severity="normal", status="success", created_at=now))
        await db.commit()

        items, total = await list_admin_audit_logs(db, 1, 20, keyword="question")
        assert total == 1
    finally:
        await db.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_keyword_search_resource_type():
    """keyword 可以搜索 resource_type"""
    engine, db = await _init_db()
    try:
        now = utcnow()
        db.add(AuditLog(operator_id=1, operator_name="admin", action="test.a",
                        resource_type="question", severity="normal", status="success", created_at=now))
        db.add(AuditLog(operator_id=1, operator_name="admin", action="test.b",
                        resource_type="subject", severity="normal", status="success", created_at=now))
        await db.commit()

        items, total = await list_admin_audit_logs(db, 1, 20, keyword="question")
        assert total == 1
    finally:
        await db.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_keyword_search_operator_name():
    """keyword 可以搜索 operator_name"""
    engine, db = await _init_db()
    try:
        now = utcnow()
        db.add(AuditLog(operator_id=2, operator_name="张三", action="test.search",
                        resource_type="test", severity="normal", status="success", created_at=now))
        db.add(AuditLog(operator_id=1, operator_name="admin", action="test.other",
                        resource_type="test", severity="normal", status="success", created_at=now))
        await db.commit()

        items, total = await list_admin_audit_logs(db, 1, 20, keyword="张三")
        assert total == 1
        assert items[0].operator_name == "张三"
    finally:
        await db.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_end_date_semi_open_interval():
    """半开区间：to 是排他上界，当天 23:59 的日志在 [start, next_midnight) 内可查到"""
    engine, db = await _init_db()
    try:
        now = utcnow()
        today_midnight = datetime(now.year, now.month, now.day)
        next_midnight = today_midnight + timedelta(days=1)
        # Log at 23:59 on "today"
        db.add(AuditLog(operator_id=1, operator_name="admin", action="test.today",
                        resource_type="test", severity="normal", status="success",
                        created_at=today_midnight + timedelta(hours=23, minutes=59)))
        await db.commit()

        # Query: [today-1, next_midnight) → should include the log
        items, total = await list_admin_audit_logs(
            db, 1, 20,
            created_from=today_midnight - timedelta(days=1),
            created_to=next_midnight,
        )
        assert total == 1

        # Query: [today-1, today_midnight) → should NOT include the log
        items2, total2 = await list_admin_audit_logs(
            db, 1, 20,
            created_from=today_midnight - timedelta(days=1),
            created_to=today_midnight,
        )
        assert total2 == 0
    finally:
        await db.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_pagination_count():
    """分页总数正确"""
    engine, db = await _init_db()
    try:
        now = utcnow()
        for i in range(5):
            db.add(AuditLog(operator_id=1, operator_name="admin", action=f"test.page.{i}",
                            resource_type="test", severity="normal", status="success", created_at=now))
        await db.commit()

        items, total = await list_admin_audit_logs(db, 1, 2)
        assert total == 5
        assert len(items) == 2
    finally:
        await db.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_default_date_range():
    """默认日期范围不报错"""
    engine, db = await _init_db()
    try:
        db.add(AuditLog(operator_id=1, operator_name="admin", action="test.default",
                        resource_type="test", severity="normal", status="success",
                        created_at=utcnow()))
        await db.commit()

        items, total = await list_admin_audit_logs(db, 1, 20)
        assert total == 1
    finally:
        await db.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_span_exceeds_one_year_raises():
    """查询跨度超过 1 年时返回明确错误"""
    engine, db = await _init_db()
    try:
        with pytest.raises(ValueError, match="不能超过 1 年"):
            await list_admin_audit_logs(
                db, 1, 20,
                created_from=datetime(2020, 1, 1),
                created_to=datetime(2025, 1, 1),
            )
    finally:
        await db.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_historical_log_with_null_detail():
    """历史日志 detail 为 null 时仍可正常返回"""
    engine, db = await _init_db()
    try:
        log = AuditLog(operator_id=1, operator_name="admin", action="test.old",
                       resource_type="test", severity="normal", status="success", detail=None)
        db.add(log)
        await db.commit()

        item = await get_admin_audit_log(db, log.id)
        assert item.detail is None
    finally:
        await db.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_list_with_operator_id():
    """按 operatorId 查询"""
    engine, db = await _init_db()
    try:
        now = utcnow()
        db.add(AuditLog(operator_id=1, operator_name="admin", action="test.op1",
                        resource_type="test", severity="normal", status="success", created_at=now))
        db.add(AuditLog(operator_id=2, operator_name="user2", action="test.op2",
                        resource_type="test", severity="normal", status="success", created_at=now))
        await db.commit()

        items, total = await list_admin_audit_logs(db, 1, 20, operator_id=2)
        assert total == 1
        assert items[0].operator_id == 2
    finally:
        await db.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_list_with_resource_id():
    """按 resourceId 查询"""
    engine, db = await _init_db()
    try:
        now = utcnow()
        db.add(AuditLog(operator_id=1, operator_name="admin", action="test.r1",
                        resource_type="test", severity="normal", status="success",
                        resource_id="r1", created_at=now))
        db.add(AuditLog(operator_id=1, operator_name="admin", action="test.r2",
                        resource_type="test", severity="normal", status="success",
                        resource_id="r2", created_at=now))
        await db.commit()

        items, total = await list_admin_audit_logs(db, 1, 20, resource_id="r1")
        assert total == 1
    finally:
        await db.close()
        await engine.dispose()


# ============================================================================
# Cleanup Tests
# ============================================================================


@pytest.mark.asyncio
async def test_cleanup_deletes_expired_logs():
    """删除超过保留期的日志"""
    engine, db = await _init_db()
    try:
        now = utcnow()
        db.add(AuditLog(operator_id=1, operator_name="admin", action="test.old",
                        resource_type="test", severity="normal", status="success",
                        created_at=now - timedelta(days=200)))
        db.add(AuditLog(operator_id=1, operator_name="admin", action="test.recent",
                        resource_type="test", severity="normal", status="success",
                        created_at=now - timedelta(days=10)))
        await db.commit()

        deleted = await cleanup_expired_admin_audit_logs(db, retention_days=30, batch_size=100)
        assert deleted >= 1

        remaining = await db.scalar(select(func.count()).select_from(AuditLog))
        assert remaining == 1
    finally:
        await db.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_cleanup_keeps_recent_logs():
    """不删除保留期内的日志"""
    engine, db = await _init_db()
    try:
        now = utcnow()
        for i in range(3):
            db.add(AuditLog(operator_id=1, operator_name="admin", action=f"test.recent.{i}",
                            resource_type="test", severity="normal", status="success",
                            created_at=now - timedelta(days=i)))
        await db.commit()

        deleted = await cleanup_expired_admin_audit_logs(db, retention_days=30, batch_size=100)
        assert deleted == 0
    finally:
        await db.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_cleanup_boundary_time():
    """边界时间处理正确 — 恰好等于 retention 天数的日志应保留"""
    engine, db = await _init_db()
    try:
        boundary = utcnow() - timedelta(days=29, hours=23, minutes=50)
        db.add(AuditLog(operator_id=1, operator_name="admin", action="test.boundary",
                        resource_type="test", severity="normal", status="success",
                        created_at=boundary))
        await db.commit()

        deleted = await cleanup_expired_admin_audit_logs(db, retention_days=30, batch_size=100)
        assert deleted == 0
    finally:
        await db.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_cleanup_past_boundary_is_deleted():
    """刚过保留期边界的日志应被删除"""
    engine, db = await _init_db()
    try:
        past = utcnow() - timedelta(days=30, minutes=1)
        db.add(AuditLog(operator_id=1, operator_name="admin", action="test.past",
                        resource_type="test", severity="normal", status="success",
                        created_at=past))
        await db.commit()

        deleted = await cleanup_expired_admin_audit_logs(db, retention_days=30, batch_size=100)
        assert deleted == 1
    finally:
        await db.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_cleanup_batch_size():
    """支持分批删除"""
    engine, db = await _init_db()
    try:
        now = utcnow()
        for i in range(5):
            db.add(AuditLog(operator_id=1, operator_name="admin", action=f"test.old.{i}",
                            resource_type="test", severity="normal", status="success",
                            created_at=now - timedelta(days=100)))
        await db.commit()

        deleted = await cleanup_expired_admin_audit_logs(db, retention_days=30, batch_size=2)
        assert deleted == 5
    finally:
        await db.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_cleanup_no_expired_data():
    """没有过期数据时返回 0"""
    engine, db = await _init_db()
    try:
        deleted = await cleanup_expired_admin_audit_logs(db, retention_days=30, batch_size=100)
        assert deleted == 0
    finally:
        await db.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_cleanup_idempotent():
    """多次执行具有幂等性"""
    engine, db = await _init_db()
    try:
        now = utcnow()
        db.add(AuditLog(operator_id=1, operator_name="admin", action="test.old",
                        resource_type="test", severity="normal", status="success",
                        created_at=now - timedelta(days=200)))
        await db.commit()

        deleted1 = await cleanup_expired_admin_audit_logs(db, retention_days=30, batch_size=100)
        assert deleted1 == 1

        deleted2 = await cleanup_expired_admin_audit_logs(db, retention_days=30, batch_size=100)
        assert deleted2 == 0
    finally:
        await db.close()
        await engine.dispose()
