import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.v1 import sync as sync_api
from app.features.sync_merge_service import SyncReport
from app.schemas.sync import SyncPackage


def _package() -> SyncPackage:
    return SyncPackage.model_validate(
        {
            "exported_at": "2026-10-31T00:00:00",
            "manifest": {"question_count": 0, "tag_count": 0, "checksum": "abc"},
            "questions": [],
            "tags": [],
        }
    )


def _run(monkeypatch, granted: set[str], report: SyncReport | None = None):
    merge = AsyncMock(return_value=report or SyncReport())
    audit = AsyncMock()
    monkeypatch.setattr(sync_api, "merge_sync_package", merge)
    monkeypatch.setattr(sync_api, "write_admin_audit", audit)
    monkeypatch.setattr(sync_api, "_get_permission_names", AsyncMock(return_value=granted))
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    admin = SimpleNamespace(id=1, role_id=2, username="ops")
    asyncio.run(sync_api.import_sync_package(_package(), db=db, admin=admin))
    return merge, audit, db


@pytest.mark.parametrize(
    "granted,expected",
    [({"sync:write"}, False), ({"sync:write", "question:review"}, True)],
)
def test_lifecycle_flag_follows_review_permission(monkeypatch, granted, expected):
    merge, _, _ = _run(monkeypatch, granted)
    assert merge.await_args.kwargs["allow_lifecycle"] is expected


def test_successful_import_is_audited_before_commit(monkeypatch):
    _, audit, db = _run(monkeypatch, {"sync:write"})
    audit.assert_awaited_once()
    assert audit.await_args.args[2] == "sync.import"
    db.commit.assert_awaited_once()


def test_failed_import_is_not_audited_and_rolls_back(monkeypatch):
    _, audit, db = _run(monkeypatch, {"sync:write"}, SyncReport(errors=["boom"]))
    audit.assert_not_awaited()
    db.rollback.assert_awaited_once()
