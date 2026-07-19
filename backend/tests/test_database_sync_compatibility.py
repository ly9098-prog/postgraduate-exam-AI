"""Database Sync Compatibility — Verify existing sync is preserved."""
from __future__ import annotations

from app.features.sync_merge_service import (
    MAX_QUESTIONS_PER_SYNC,
    MAX_TAGS_PER_SYNC,
    SyncReport,
    merge_sync_package,
)
from app.schemas.sync import SyncPackage, SyncReportResponse


def test_sync_imports_work():
    """Existing sync components are importable."""
    assert MAX_QUESTIONS_PER_SYNC == 5000
    assert MAX_TAGS_PER_SYNC == 1000


def test_sync_report_dataclass():
    report = SyncReport()
    assert report.questions_new == 0
    assert report.errors == []


def test_sync_package_schema():
    """SyncPackage exists and is importable."""
    from app.schemas.sync import SyncPackage
    assert SyncPackage is not None
