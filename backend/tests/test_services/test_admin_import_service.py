from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.admin_security import AdminPrincipal
from app.models.admin import AdminUser
from app.models.question_import import QuestionImport
from app.services import admin_import_service
from app.services.admin_import_service import complete_import_question, create_enrich_task, get_enrich_status, get_import_batch_detail, list_import_batches


class _Scalars:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class _Result:
    def __init__(self, rows=None, values=None):
        self.rows = rows or []
        self.values = values or []

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None

    def scalar_one_or_none(self):
        return self.values[0] if self.values else None

    def scalars(self):
        return _Scalars(self.values)

    def _row_to_mapping(self, row):
        """Convert an ORM model to a SimpleNamespace with extra fields."""
        if hasattr(row, "__table__"):
            data = {c.name: getattr(row, c.name, None) for c in row.__table__.columns}
            data["content_preview"] = ""
            return SimpleNamespace(**data)
        return row

    def mappings(self):
        combined = list(self.rows) + list(self.values)
        return _Result(rows=[self._row_to_mapping(r) for r in combined])


class _Db:
    def __init__(self, imports=None):
        self.imports = imports or []

    async def get(self, _model, _key):
        return None

    async def scalar(self, statement):
        text = str(statement)
        if "count" in text.lower():
            if "GROUP BY" in text:
                return len({item.batch_id for item in self.imports})
            return len(self.imports)
        return 0

    async def execute(self, statement):
        text = str(statement)
        if "admin_ai_settings" in text:
            return _Result()
        if "GROUP BY" in text:
            rows = []
            for batch_id in sorted({item.batch_id for item in self.imports}):
                batch_items = [item for item in self.imports if item.batch_id == batch_id]
                rows.append(_summary_row(batch_items))
            return _Result(rows=rows)
        return _Result(values=self.imports)


def _principal():
    user = AdminUser(id=9, username="operator", password_hash="hash", is_active=True, role_id=2)
    return AdminPrincipal(user, {})


def _import_record(record_id, batch_id="batch-1", status="pending", ai_generated=False):
    now = datetime(2026, 5, 29)
    return QuestionImport(
        id=record_id,
        batch_id=batch_id,
        source_type="manual",
        source_file="file.xlsx",
        subject="math",
        question_type="choice",
        raw_data={"text": "raw"},
        parsed_content={"text": "题干"},
        parsed_options={"A": "1"},
        parsed_answer="A",
        parsed_analysis="解析",
        status=status,
        question_id=None,
        ai_generated=ai_generated,
        ai_answer_flag=False,
        created_at=now,
        updated_at=now,
    )


def _summary_row(items):
    return SimpleNamespace(
        batch_id=items[0].batch_id,
        source_type=items[0].source_type,
        source_file=items[0].source_file,
        total_count=len(items),
        pending_count=sum(1 for item in items if item.status == "pending"),
        approved_count=sum(1 for item in items if item.status == "approved"),
        rejected_count=sum(1 for item in items if item.status == "rejected"),
        published_count=sum(1 for item in items if item.status == "published"),
        ai_count=sum(1 for item in items if item.ai_generated),
        created_at=min(item.created_at for item in items),
        updated_at=max(item.updated_at for item in items),
    )


@pytest.mark.asyncio
async def test_list_import_batches_aggregates_counts():
    db = _Db([_import_record(1), _import_record(2, status="approved", ai_generated=True)])

    batches, total = await list_import_batches(db, 1, 20)

    assert total == 1
    assert batches[0]["total_count"] == 2
    assert batches[0]["pending_count"] == 1
    assert batches[0]["approved_count"] == 1
    assert batches[0]["ai_count"] == 1


@pytest.mark.asyncio
async def test_get_import_batch_detail_returns_paginated_items():
    db = _Db([_import_record(1), _import_record(2, status="approved")])

    detail = await get_import_batch_detail(db, "batch-1", 1, 20)

    assert detail.batch_id == "batch-1"
    assert detail.total_count == 2
    assert len(detail.items) == 2
    assert detail.items[0].parsed_answer == "A"


@pytest.mark.asyncio
async def test_get_import_batch_detail_missing_batch():
    with pytest.raises(ValueError, match="导入批次不存在"):
        await get_import_batch_detail(_Db([]), "missing", 1, 20)


@pytest.mark.asyncio
async def test_complete_import_question_reuses_pipeline_and_audits(monkeypatch):
    record = _import_record(1)
    db = _Db([record])
    audit = AsyncMock()
    parse_allowed = AsyncMock()
    complete = AsyncMock(return_value={"missing": ["answer"], "from_fallback": False, "ai_metadata": {"complete_suggestion": {"answer": "B"}}, "tokens_used": 10, "duration_ms": 20})
    monkeypatch.setattr(admin_import_service, "write_admin_audit", audit)
    monkeypatch.setattr(admin_import_service, "ensure_ai_parse_allowed", parse_allowed)
    monkeypatch.setattr(admin_import_service.question_pipeline, "complete_import", complete)

    result = await complete_import_question(db, 1, _principal())

    assert result["missing"] == ["answer"]
    assert result["item"].id == 1
    parse_allowed.assert_awaited_once()
    complete.assert_awaited_once_with(db, 9, 1)
    audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_complete_import_question_requires_pending():
    db = _Db([_import_record(1, status="approved")])

    with pytest.raises(ValueError, match="仅支持对 pending 记录使用 AI 补全"):
        await complete_import_question(db, 1, _principal())


@pytest.mark.asyncio
async def test_create_enrich_task_writes_cache_and_audit(monkeypatch):
    writes = {}

    async def fake_set(key, value, ttl=300):
        writes[key] = value

    audit = AsyncMock()
    monkeypatch.setattr(admin_import_service.cache, "set", fake_set)
    monkeypatch.setattr(admin_import_service, "write_admin_audit", audit)

    result = await create_enrich_task(_Db([_import_record(1)]), "batch-1", _principal())

    assert result.status == "pending"
    assert f"admin:ai:task:{result.task_id}" in writes
    assert writes["admin:ai:batch:batch-1:task"] == result.task_id
    audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_enrich_task_allows_cache_degrade(monkeypatch):
    async def fake_set(_key, _value, ttl=300):
        return None

    monkeypatch.setattr(admin_import_service.cache, "set", fake_set)
    monkeypatch.setattr(admin_import_service, "write_admin_audit", AsyncMock())

    result = await create_enrich_task(_Db([_import_record(1)]), "batch-1", _principal())

    assert result.batch_id == "batch-1"


@pytest.mark.asyncio
async def test_get_enrich_status_reads_batch_pointer(monkeypatch):
    async def fake_get(key):
        if key == "admin:ai:batch:batch-1:task":
            return "task-1"
        if key == "admin:ai:task:task-1":
            return {"task_id": "task-1", "batch_id": "batch-1", "status": "pending", "created_at": "2026-05-29T00:00:00"}
        return None

    monkeypatch.setattr(admin_import_service.cache, "get", fake_get)

    status = await get_enrich_status("batch-1")

    assert status["task_id"] == "task-1"


@pytest.mark.asyncio
async def test_get_enrich_status_missing_task(monkeypatch):
    monkeypatch.setattr(admin_import_service.cache, "get", AsyncMock(return_value=None))

    with pytest.raises(ValueError, match="AI任务不存在"):
        await get_enrich_status("batch-1")
