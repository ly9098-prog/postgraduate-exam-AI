from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import admin_dashboard_service as dashboard_service
from app.services.admin_audit_service import _normalize_audit_range


def test_audit_range_defaults_to_recent_six_months():
    start, end = _normalize_audit_range(None, None)

    assert 180 <= (end - start).days <= 184


def test_audit_range_rejects_more_than_one_year():
    with pytest.raises(ValueError, match="不能超过 1 年"):
        _normalize_audit_range(datetime.utcnow() - timedelta(days=366), datetime.utcnow())


def test_dashboard_daily_range_defaults_to_seven_days():
    start, end = dashboard_service._normalize_daily_range(None, date(2026, 5, 29))

    assert start == date(2026, 5, 23)
    assert end == date(2026, 5, 29)


def test_dashboard_daily_range_rejects_more_than_one_year():
    with pytest.raises(ValueError, match="不能超过 1 年"):
        dashboard_service._normalize_daily_range(date(2025, 1, 1), date(2026, 1, 2))


@pytest.mark.asyncio
async def test_dashboard_overview_returns_cached_data(monkeypatch):
    monkeypatch.setattr(dashboard_service.cache, "get", AsyncMock(return_value={"users_total": 1}))
    compute = AsyncMock()
    monkeypatch.setattr(dashboard_service, "compute_dashboard_overview", compute)

    result = await dashboard_service.get_dashboard_overview(SimpleNamespace())

    assert result == {"users_total": 1}
    compute.assert_not_called()


@pytest.mark.asyncio
async def test_dashboard_overview_degrades_when_lock_unavailable(monkeypatch):
    monkeypatch.setattr(dashboard_service.cache, "get", AsyncMock(return_value=None))
    monkeypatch.setattr(dashboard_service.cache, "acquire_lock", AsyncMock(return_value=False))
    monkeypatch.setattr(dashboard_service, "compute_dashboard_overview", AsyncMock(return_value={"users_total": 2}))

    result = await dashboard_service.get_dashboard_overview(SimpleNamespace())

    assert result == {"users_total": 2}
